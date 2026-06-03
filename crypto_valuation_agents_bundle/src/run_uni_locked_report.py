#!/usr/bin/env python3
import csv, io, json, math, statistics, sys, time
from collections import defaultdict
from datetime import datetime, date, timezone
from urllib.request import Request, urlopen
import numpy as np

UA='Mozilla/5.0 Hermes UNI locked valuation cron'

def get_json(url, timeout=30):
    req=Request(url, headers={'User-Agent':UA, 'Accept':'application/json'})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def get_text(url, timeout=30):
    req=Request(url, headers={'User-Agent':UA})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode()

def ts_date(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()

def ym(d): return (d.year, d.month)
def yms(y,m): return f'{y:04d}-{m:02d}'

def money(x):
    ax=abs(x)
    if ax>=1e12: return f'${x/1e12:.2f}T'
    if ax>=1e9: return f'${x/1e9:.2f}B'
    if ax>=1e6: return f'${x/1e6:.1f}M'
    return f'${x:,.0f}'
def volfmt(x): return money(x).replace('$','$')
def bps(x): return f'{x:.2f}bps'
def px(x): return f'${x:.2f}'
def mult(x): return f'{x:.1f}x'
def pct(x): return f'{100*x:.0f}%'

def parse_chart(data):
    out=[]
    for ts,val in data['totalDataChart']:
        if val is None: continue
        d=ts_date(ts)
        out.append((d,float(val)))
    out.sort()
    return out

caveats=[]
# DeFiLlama data
vol_data=get_json('https://api.llama.fi/summary/dexs/uniswap?dataType=dailyVolume')
fee_data=get_json('https://api.llama.fi/summary/fees/uniswap?dataType=dailyFees')
vol_daily=parse_chart(vol_data)
fee_daily=parse_chart(fee_data)
vol_by_date=dict(vol_daily); fee_by_date=dict(fee_daily)
latest_vol_date=max(vol_by_date); latest_fee_date=max(fee_by_date)
latest_data_date=min(latest_vol_date, latest_fee_date)
# latest full 30D ending at latest common date
all_dates=sorted(set(vol_by_date)&set(fee_by_date))
latest_dates=[d for d in all_dates if d<=latest_data_date][-30:]
latest30_vol=sum(vol_by_date[d] for d in latest_dates)
latest30_fees=sum(fee_by_date[d] for d in latest_dates)
recent_lp_bps=latest30_fees/latest30_vol*10000

# monthly completed aggregates: complete month means before current month of latest_data_date
cur_ym=ym(latest_data_date)
monthly_vol=defaultdict(float); monthly_fee=defaultdict(float)
for d,v in vol_daily:
    if ym(d) < cur_ym:
        monthly_vol[ym(d)] += v
for d,v in fee_daily:
    if ym(d) < cur_ym:
        monthly_fee[ym(d)] += v
months=sorted(k for k,v in monthly_vol.items() if k>= (2021,1) and v>0 and k in monthly_fee)
# require up to latest completed month
last12=months[-12:]
trailing12_median_vol=statistics.median([monthly_vol[m] for m in last12])
trailing12_vol=sum(monthly_vol[m] for m in last12)
trailing12_fees=sum(monthly_fee[m] for m in last12)
trailing12_lp_bps=trailing12_fees/trailing12_vol*10000
lp_fee_bps=recent_lp_bps  # latest live, cross-check against T12M
base_seed=min(latest30_vol, trailing12_median_vol)
# log return bootstrap from monthly volumes 2021+ completed months
month_vols=np.array([monthly_vol[m] for m in months], dtype=float)
logrets=np.diff(np.log(month_vols))
# winsor not specified: pure bootstrap
rng=np.random.default_rng(20260525)
N=80000
idx=rng.integers(0, len(logrets), size=(N,36))
rets=logrets[idx]
paths=base_seed*np.exp(np.cumsum(rets, axis=1))
y3_ttm_vol=paths[:, -12:].sum(axis=1)

# Market data CoinGecko
cg=get_json('https://api.coingecko.com/api/v3/coins/uniswap?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false&sparkline=false')
md=cg['market_data']
spot=float(md['current_price']['usd'])
market_cap=float(md['market_cap']['usd'])
fdv=float(md.get('fully_diluted_valuation',{}).get('usd') or 0)
circ=float(md.get('circulating_supply') or market_cap/spot)
max_supply=float(md.get('max_supply') or md.get('total_supply') or (fdv/spot if fdv else circ))
if not max_supply or max_supply<circ: max_supply=circ

# Discount rate: Yahoo/FRED 10Y + S&P, CG UNI chart
try:
    # Yahoo ^TNX is the CBOE 10Y yield index quoted as percent points.
    tnx=get_json('https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d')
    rf_pct=float(tnx['chart']['result'][0]['meta'].get('regularMarketPrice'))
    rf_date='Yahoo ^TNX latest'
    rf=rf_pct/100.0
except Exception as e1:
    try:
        dgs=get_text('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10', timeout=15)
        rows=list(csv.DictReader(io.StringIO(dgs)))
        vals=[(r['observation_date'], float(r['DGS10'])) for r in rows if r.get('DGS10') not in ('','.')]
        rf_date, rf_pct=vals[-1]
        rf=rf_pct/100.0
    except Exception as e2:
        caveats.append(f'10Y yield fetch failed; used 4.5% fallback (Yahoo {e1}; FRED {e2})')
        rf_date, rf_pct, rf='fallback',4.5,0.045
try:
    sp_y=get_json('https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=1y&interval=1d')
    sp_vals=[x for x in sp_y['chart']['result'][0]['indicators']['quote'][0]['close'] if x is not None]
    sp_rets=np.diff(np.log(np.array(sp_vals[-366:], dtype=float)))
    sp_stdev=float(np.std(sp_rets, ddof=1))
except Exception as e1:
    try:
        sp=get_text('https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500', timeout=15)
        rows=list(csv.DictReader(io.StringIO(sp)))
        sp_vals=[float(r['SP500']) for r in rows if r.get('SP500') not in ('','.')]
        sp_vals=sp_vals[-366:]
        sp_rets=np.diff(np.log(np.array(sp_vals)))
        sp_stdev=float(np.std(sp_rets, ddof=1))
    except Exception as e2:
        caveats.append(f'S&P fetch failed; used 1.0% daily stdev fallback (Yahoo {e1}; FRED {e2})')
        sp_stdev=0.010
try:
    uni_hist=get_json('https://api.coingecko.com/api/v3/coins/uniswap/market_chart?vs_currency=usd&days=365&interval=daily')
    prices=[]
    seen=set()
    for ms,p in uni_hist['prices']:
        d=datetime.fromtimestamp(ms/1000, tz=timezone.utc).date()
        if d in seen: continue
        seen.add(d); prices.append(float(p))
    prices=prices[-366:]
    uni_rets=np.diff(np.log(np.array(prices)))
    uni_stdev=float(np.std(uni_rets, ddof=1))
except Exception as e:
    caveats.append(f'UNI history fetch failed; used 7.0% daily stdev fallback ({e})')
    uni_stdev=0.070
DR=rf + 0.03*(uni_stdev/sp_stdev)

# Economics
frontend_bps=0.30
current_lp_protocol_bps=0.826
current_take_bps=current_lp_protocol_bps+frontend_bps
full_take_bps=lp_fee_bps*0.25+frontend_bps
multiple=15.0
disc=(1+DR)**3

def value_arrays(take_bps, supply):
    gp=y3_ttm_vol*take_bps/10000.0
    pv=gp*multiple/supply/disc
    return gp,pv
cur_gp, cur_pv=value_arrays(current_take_bps, circ)
full_gp, full_pv=value_arrays(full_take_bps, circ)
_, full_pv_fdv=value_arrays(full_take_bps, max_supply)
q=[25,50,75]
def qs(arr): return np.percentile(arr,q)
cur_gp_q, cur_pv_q=qs(cur_gp), qs(cur_pv)
full_gp_q, full_pv_q=qs(full_gp), qs(full_pv)
vol_q=qs(y3_ttm_vol)
fdv_pv_q=qs(full_pv_fdv)
vol_mean=float(np.mean(y3_ttm_vol)); cur_gp_mean=float(np.mean(cur_gp)); cur_pv_mean=float(np.mean(cur_pv)); full_gp_mean=float(np.mean(full_gp)); full_pv_mean=float(np.mean(full_pv)); fdv_pv_mean=float(np.mean(full_pv_fdv))
prob_gt_spot=float(np.mean(full_pv>spot)); prob_gt_3x=float(np.mean(full_pv>3*spot))
# current sanity
current_ann_vol=latest30_vol*365.0/30.0
current_state_ann_gp=current_ann_vol*current_take_bps/10000.0
full_ann_gp=current_ann_vol*full_take_bps/10000.0
mcap_cur=market_cap/current_state_ann_gp
mcap_full=market_cap/full_ann_gp
fdv_full=(fdv if fdv else spot*max_supply)/full_ann_gp

report=[]
report.append('UNI locked valuation update — 3Y GP-capture, full-activation economics')
report.append('```text')
report.append('1) Key assumptions')
report.append(f'Spot / mcap            {px(spot)} / {money(market_cap)}')
report.append(f'Data freshness          DFL vol+fees thru {latest_data_date}; spot CG live')
report.append(f'Base seed               {money(base_seed)} monthly (min 30D {money(latest30_vol)}, T12M med {money(trailing12_median_vol)})')
report.append(f'LP fee bps              {bps(lp_fee_bps)} recent 30D (T12M {bps(trailing12_lp_bps)})')
report.append(f'Take bps                current {bps(current_take_bps)} | full-act {bps(full_take_bps)}')
report.append(f'Discount rate           {100*DR:.1f}% (10Y {rf_pct:.2f}%, UNI/SPX stdev {uni_stdev/sp_stdev:.1f}x)')
report.append(f'Supply / multiple       {circ/1e6:.1f}M circ; {max_supply/1e6:.1f}M full / {multiple:.0f}x GP')
report.append('```')
report.append('```text')
report.append('2) Model results')
report.append('Metric                    P25        P50        P75       EV/mean')
report.append(f'Y3 TTM volume          {money(vol_q[0]):>9} {money(vol_q[1]):>9} {money(vol_q[2]):>9} {money(vol_mean):>9}')
report.append(f'Current-state GP       {money(cur_gp_q[0]):>9} {money(cur_gp_q[1]):>9} {money(cur_gp_q[2]):>9} {money(cur_gp_mean):>9}')
report.append(f'Current-state PV/UNI   {px(cur_pv_q[0]):>9} {px(cur_pv_q[1]):>9} {px(cur_pv_q[2]):>9} {px(cur_pv_mean):>9}')
report.append(f'Full-act Y3 GP         {money(full_gp_q[0]):>9} {money(full_gp_q[1]):>9} {money(full_gp_q[2]):>9} {money(full_gp_mean):>9}')
report.append(f'Full-act PV/UNI        {px(full_pv_q[0]):>9} {px(full_pv_q[1]):>9} {px(full_pv_q[2]):>9} {px(full_pv_mean):>9}')
report.append(f'FDV/full-supply PV     {px(fdv_pv_q[0]):>9} {px(fdv_pv_q[1]):>9} {px(fdv_pv_q[2]):>9} {px(fdv_pv_mean):>9}')
report.append('```')
report.append('```text')
report.append('3) Sanity checks / current multiples')
report.append(f'Current annualized volume       {money(current_ann_vol)}')
report.append(f'Current-state annual GP         {money(current_state_ann_gp)}')
report.append(f'Full-activation annual GP       {money(full_ann_gp)}')
report.append(f'MCap / current-state GP         {mult(mcap_cur)}')
report.append(f'MCap / full-activation GP       {mult(mcap_full)}')
report.append(f'FDV / full-activation GP        {mult(fdv_full)}')
report.append(f'Prob full-act PV > spot         {pct(prob_gt_spot)}')
report.append(f'Prob full-act PV > 3x spot      {pct(prob_gt_3x)}')
report.append('```')
if caveats:
    report.append('Caveats: ' + '; '.join(caveats))
print('\n'.join(report))
