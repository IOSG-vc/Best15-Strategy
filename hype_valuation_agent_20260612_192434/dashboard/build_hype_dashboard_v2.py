# DEPRECATED — This standalone dashboard builder is superseded by:
#   crypto_valuation_agents_bundle/webapp/agents/hype.py  (active model)
#   crypto_valuation_agents_bundle/hype_gp_capture_12m_start_run.py
#
# This script still reads from old JSON output with the supply/emission scenario keys
# (base_db_observed_emissions, etc.) which no longer exist in the new model output.
# Do not run this script against new model output.

import json, re, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, '/Users/momir_mini/.openclaw/workspace/altcoin_research')
import numpy as np
import hype_gp_capture_mc as h
import hype_gp_capture_12m_start_run as m

RES_PATH = Path('/Users/momir_mini/.openclaw/workspace/altcoin_research/hype_3y_gp_capture_12m_start_run.json')
MCP_PATH = Path('/tmp/defillama_hype_mcp_answer.txt')
res = json.load(open(RES_PATH))
# Extract MCP JSON from one-shot output.
mcp_text = MCP_PATH.read_text() if MCP_PATH.exists() else '{}'
match = re.search(r'\{.*\}\s*$', mcp_text, re.S)
mcp = json.loads(match.group(0)) if match else {}

rev = h.defillama_revenue()
rev_vals = np.array([v for _, v in rev], dtype=float)
rev30 = float(mcp.get('current_protocol_metrics', {}).get('revenue_30d_usd') or rev_vals[-30:].sum())
rev180 = float(mcp.get('current_protocol_metrics', {}).get('revenue_180d_usd') or rev_vals[-180:].sum())
vol30_mcp = float(mcp.get('current_protocol_metrics', {}).get('derivatives_volume_30d_usd') or 0)
vol180_mcp = float(mcp.get('current_protocol_metrics', {}).get('derivatives_volume_180d_usd') or 0)
rev30_ann = rev30 * 365 / 30
rev180_ann = rev180 * 365 / 180
scaled_daily, shares = h.scaled_binance_futures_daily()
bn30 = sum(v for _, v in scaled_daily[-30:])
bn180 = sum(v for _, v in scaled_daily[-180:])
ms30_mcp = vol30_mcp / bn30 if vol30_mcp and bn30 else None
ms180_mcp = vol180_mcp / bn180 if vol180_mcp and bn180 else None
ms_ratio_mcp = ms30_mcp / ms180_mcp if ms30_mcp and ms180_mcp else None
# fallback/revenue-implied rolling chart series
bn = dict(scaled_daily)
rows=[]
for d,v in rev:
    if d in bn and bn[d] > 0:
        rows.append((d, v / m.NET_REVENUE_TAKE_RATE, bn[d], v))
series=[]
for i in range(len(rows)):
    d=rows[i][0]; ms30=ms180=None
    if i >= 29:
        hl=sum(x[1] for x in rows[i-29:i+1]); b=sum(x[2] for x in rows[i-29:i+1]); ms30=hl/b if b else None
    if i >= 179:
        hl=sum(x[1] for x in rows[i-179:i+1]); b=sum(x[2] for x in rows[i-179:i+1]); ms180=hl/b if b else None
    series.append((d,ms30,ms180))
latest=[x for x in series if x[1] is not None][-1]
prev30=[x for x in series if x[1] is not None and x[0] <= latest[0]-timedelta(days=30)][-1][1]
velocity_pp_30d = ((ms30_mcp or latest[1]) - prev30) * 100
chart=[x for x in series if x[1] is not None and x[2] is not None][-240:]

base=res['scenarios']['base_db_observed_emissions']; bull=res['scenarios']['upside_db_observed_plus_optionality']; bear=res['scenarios']['bear_worst_case_emissions']; zero=res['scenarios']['zero_emissions_sensitivity']
market=res['market']; mc=res['mc']; usdc=res['usdc_yield']; spot=market['spot']
ms90_seed = float(mc['market_share']['ms90'])
# For page coherence, display and chart the same market-share windows used by the model artifact.
_model_ms = res['mc']['market_share']
ms30_mcp = _model_ms.get('ms30', ms30_mcp)
ms90_seed = float(_model_ms.get('ms90', ms90_seed))
ms180_mcp = _model_ms.get('ms180', ms180_mcp)
ms_ratio_mcp = (ms30_mcp / ms180_mcp) if ms30_mcp and ms180_mcp else ms_ratio_mcp
total_supply=market['total_supply'] or market['fdv']/spot
circ_supply=market['circ_supply']
current_mcap=market.get('mcap') or circ_supply*spot
predicted_gross_issuance_3y=base['modeled_gross_release_3y']
buyback_target_supply=circ_supply+predicted_gross_issuance_3y
current_perp_ann=base['current_perp_monthly_gp']*12; current_usdc_ann=base['current_usdc_yield_annual_gp']; current_total_ann=current_perp_ann+current_usdc_ann
fee_plus_usdc_ann=rev30_ann+current_usdc_ann
years_fee_plus_usdc=buyback_target_supply/max(fee_plus_usdc_ann/spot,1)
years_buyback_target=current_total_ann and buyback_target_supply/(current_total_ann/spot)  # legacy/internal: modeled perps + USDC
years_fdv_supply=total_supply/max(current_total_ann/spot,1)
p50_supply=base['y3_supply']['p50']; p50_y3_gp=base['y3_ttm_gp']['p50']; p50_price=base['undiscounted_y3_token_price']['p50']; p50_pv=base['discounted_token_price']['p50']
y3_burn_est=market['circ_supply']+base['modeled_gross_release_3y']-p50_supply
mean_daily_vol_y3=p50_y3_gp/m.NET_REVENUE_TAKE_RATE/365
vstats=base['p50_path_y3_daily_volume']
# Price distribution table
qs=['p5','p10','p20','p25','p30','p40','p50','p60','p70','p75','p80','p90','p95']
dist=base['discounted_distribution']
# Historical model-shaped diagnostic: replay the current model mechanics where historical inputs exist.
# This is still a proxy, not a full production MC replay: historical supply/unlocks and MCP-reported volume history are unavailable,
# so it uses revenue-implied HL volume for rolling windows, the same Binance proxy, current supply assumptions, and current USDC-yield calibration.
# Use DefiLlama Coins for full available HYPE price history (CoinGecko free endpoint rejects >365D without an API key).
def llama_hype_prices(start_date='2024-11-29'):
    import requests
    out={}
    start=datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end=datetime.now(timezone.utc)
    cur=start
    while cur < end:
        ts=int(cur.timestamp())
        url=f'https://coins.llama.fi/chart/coingecko:hyperliquid?start={ts}&span=499&period=1d'
        data=requests.get(url,timeout=30).json().get('coins',{}).get('coingecko:hyperliquid',{}).get('prices',[])
        if not data:
            break
        for row in data:
            d=datetime.fromtimestamp(row['timestamp'],timezone.utc).date()
            out[d]=float(row['price'])
        last=datetime.fromtimestamp(data[-1]['timestamp'],timezone.utc)
        nxt=(last+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        if nxt <= cur:
            break
        cur=nxt
        if len(out)>900:
            break
    return sorted(out.items())
prices=dict(llama_hype_prices())
row_by_date={d:i for i,(d,_,_,_) in enumerate(rows)}
common=[]
for d in sorted(prices):
    if d not in row_by_date: continue
    i=row_by_date[d]
    if i < 179: continue
    p0=prices[d]
    p30=prices.get(d+timedelta(days=30)); p90=prices.get(d+timedelta(days=90))
    r30=None if p30 is None else p30/p0-1
    r90=None if p90 is None else p90/p0-1
    hl30=sum(x[1] for x in rows[i-29:i+1]); bn30w=sum(x[2] for x in rows[i-29:i+1])
    hl90=sum(x[1] for x in rows[i-89:i+1]); bn90w=sum(x[2] for x in rows[i-89:i+1])
    hl180=sum(x[1] for x in rows[i-179:i+1]); bn180w=sum(x[2] for x in rows[i-179:i+1])
    ms30_hist=hl30/bn30w if bn30w else 0
    ms90_hist=hl90/bn90w if bn90w else 0
    ms180_hist=hl180/bn180w if bn180w else 0
    amp=min(max(ms30_hist/max(ms180_hist,1e-12),1.0),m.MS_AMPLIFIER_CAP)
    terminal_share=min(ms90_hist*np.exp(np.log(amp)/6.0*(m.MS_MOMENTUM_DECAY_MONTHS/2.0)),m.MS_SHARE_CAP)
    # Use 90D Binance activity as current venue backdrop, then the model's share velocity rule to Y3.
    bn_daily_90=bn90w/90.0
    y3_perp_gp=bn_daily_90*365.0*terminal_share*m.NET_REVENUE_TAKE_RATE
    current_perp_ann=max(base['current_perp_monthly_gp']*12,1.0)
    usdc_gp=base['current_usdc_yield_annual_gp']*max(y3_perp_gp/current_perp_ann,0.0)**0.85
    y3_gp=y3_perp_gp+usdc_gp
    model_pv=(y3_gp*15.0*1.10/max(p50_supply,1.0))/((1+m.SELECTED_DR)**3)
    ratio=model_pv/p0 if p0 else 0
    bucket='GOOD' if ratio>1.25 else ('BAD' if ratio<0.75 else 'NEUTRAL')
    realized=(r30 is not None or r90 is not None)
    common.append((d,bucket,ratio,r30,r90,model_pv,realized,terminal_share,ms90_hist,ms30_hist,ms180_hist))

# Normalize the diagnostic line so the latest point equals the locked current Base P50 PV.
# Otherwise the visual is a separate deterministic proxy and can contradict the published MC output.
if common:
    latest_model=max(common[-1][5], 1e-12)
    bt_model_scale=p50_pv/latest_model
    _scaled=[]
    for d,bucket,ratio,r30,r90,model_pv,realized,terminal_share,ms90_hist,ms30_hist,ms180_hist in common:
        model_pv=float(model_pv)*bt_model_scale
        px=prices.get(d)
        ratio=model_pv/px if px else 0.0
        bucket='GOOD' if ratio>1.25 else ('BAD' if ratio<0.75 else 'NEUTRAL')
        _scaled.append((d,bucket,ratio,r30,r90,model_pv,realized,terminal_share,ms90_hist,ms30_hist,ms180_hist))
    common=_scaled
else:
    bt_model_scale=1.0

def bstats(bucket):
    xs=[x for x in common if x[1]==bucket and x[6]]
    r30=[x[3] for x in xs if x[3] is not None]; r90=[x[4] for x in xs if x[4] is not None]
    return {'n':len(xs),'avg30':float(np.mean(r30)) if r30 else None,'avg90':float(np.mean(r90)) if r90 else None,'last':[str(x[0]) for x in xs[-5:]]}
bt={b:bstats(b) for b in ['GOOD','NEUTRAL','BAD']}
latest_signal=common[-1] if common else None
latest_realized_signal=next((x for x in reversed(common) if x[6]), None)



# Distribution visual: Base PV percentiles + EV marker.
dist_points=[(q.upper(), dist[q]) for q in qs]
ev_val=base['probability_weighted_ev_price']
DW,DH=980,330; dL,dR,dT,dB=58,30,24,48
vals_dist=[v for _,v in dist_points]+[ev_val]
dmin=0; dmax=max(vals_dist)*1.12
bar_w=(DW-dL-dR)/len(dist_points)*0.62
def dxy(idx,val):
    x=dL+(DW-dL-dR)*(idx+0.5)/len(dist_points)
    y=dT+(DH-dT-dB)*(1-val/dmax)
    return x,y
bars=[]
for i,(label,val) in enumerate(dist_points):
    x,y=dxy(i,val); hgt=DH-dB-y
    fill='#171717' if label=='P50' else '#d8d8d8'
    bars.append(f'<rect x="{x-bar_w/2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{hgt:.1f}" rx="4" fill="{fill}"><title>{label}: ${val:.2f}</title></rect>')
    bars.append(f'<text x="{x:.1f}" y="{DH-26}" text-anchor="middle" class="axis">{label}</text>')
    if label in ('P5','P25','P50','P75','P95'):
        bars.append(f'<text x="{x:.1f}" y="{y-7:.1f}" text-anchor="middle" class="axis">${val:.0f}</text>')
ev_y=dT+(DH-dT-dB)*(1-ev_val/dmax)
grid_dist=[]
for t in np.linspace(0,dmax,5):
    y=dT+(DH-dT-dB)*(1-t/dmax)
    grid_dist.append(f'<line x1="{dL}" x2="{DW-dR}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eee"/><text x="8" y="{y+4:.1f}" class="axis">${t:.0f}</text>')
dist_svg=f'''<svg viewBox="0 0 {DW} {DH}" role="img" aria-label="Selected-model PV price distribution"><style>.axis{{font:11px Geist Mono,monospace;fill:#666}}</style><rect width="{DW}" height="{DH}" rx="12" fill="#fff"/>{''.join(grid_dist)}{''.join(bars)}<line x1="{dL}" x2="{DW-dR}" y1="{ev_y:.1f}" y2="{ev_y:.1f}" stroke="#0072f5" stroke-width="2.4" stroke-dasharray="6 5"/><text x="{DW-dR-5}" y="{ev_y-7:.1f}" text-anchor="end" class="axis">EV ${ev_val:.0f}</text></svg>'''

# Backtest visual: actual HYPE price vs run-rate PV model line.
bt_series=[]
for d,bucket,ratio,r30v,r90v,model,realized,terminal_share,ms90_hist,ms30_hist,ms180_hist in common:
    px=prices.get(d)
    if not px: continue
    bt_series.append((d, px, model, bucket, realized))
if bt_series:
    BW,BH=980,320; bL,bR,bT,bB=58,24,18,38
    vals_bt=[v for _,px,model,_,_ in bt_series for v in (px,model) if v and v>0]
    lo=max(1e-6,min(vals_bt)*0.8); hi=max(vals_bt)*1.18
    loglo,loghi=np.log(lo),np.log(hi)
    def bxy(idx,val):
        x=bL+(BW-bL-bR)*idx/max(1,(len(bt_series)-1))
        y=bT+(BH-bT-bB)*(1-(np.log(max(val,1e-6))-loglo)/(loghi-loglo))
        return x,y
    price_path=' '.join(('M' if i==0 else 'L')+f'{bxy(i,px)[0]:.1f},{bxy(i,px)[1]:.1f}' for i,(_,px,_,_,_) in enumerate(bt_series))
    model_path=' '.join(('M' if i==0 else 'L')+f'{bxy(i,model)[0]:.1f},{bxy(i,model)[1]:.1f}' for i,(_,_,model,_,_) in enumerate(bt_series))
    dots=[]
    colors={'GOOD':'#00a862','NEUTRAL':'#999','BAD':'#f31260'}
    step=max(1,len(bt_series)//90)
    for j,(d,px,model,bucket,realized) in enumerate(bt_series[::step]):
        idx=j*step
        x,y=bxy(idx,px)
        opacity=".75" if realized else ".35"
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{colors.get(bucket,"#999")}" opacity="{opacity}"><title>{d} {bucket}: spot ${px:.2f}, model ${model:.2f}</title></circle>')
    bgrid=[]
    for t in np.geomspace(lo,hi,5):
        y=bxy(0,t)[1]
        bgrid.append(f'<line x1="{bL}" x2="{BW-bR}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eee"/><text x="8" y="{y+4:.1f}" class="axis">${t:.0f}</text>')
    backtest_svg=f'''<svg viewBox="0 0 {BW} {BH}" role="img" aria-label="HYPE model backtest chart"><style>.axis{{font:12px Geist Mono,monospace;fill:#666}}</style><rect width="{BW}" height="{BH}" rx="12" fill="#fff"/>{''.join(bgrid)}<path d="{model_path}" fill="none" stroke="#0072f5" stroke-width="2.6"/><path d="{price_path}" fill="none" stroke="#171717" stroke-width="2.6"/><g>{''.join(dots)}</g><text x="{bL}" y="{BH-10}" class="axis">{bt_series[0][0]}</text><text x="{BW-140}" y="{BH-10}" class="axis">{bt_series[-1][0]}</text><text x="{BW-330}" y="24" class="axis">black=spot · blue=model-shaped PV normalized to current P50 · faded=unscored</text></svg>'''
else:
    backtest_svg='<div class="desc">No backtest observations available.</div>'


# Historical buyback horizon: years to acquire current circulating supply + modeled 3Y gross issuance
# using that date's HYPE price and trailing-30D annualized DefiLlama fee revenue only.
burn_series=[]
for d in sorted(prices):
    if d not in row_by_date: continue
    i=row_by_date[d]
    if i < 29: continue
    p0=prices[d]
    rev30_hist=sum(x[3] for x in rows[i-29:i+1])
    ann_rev=rev30_hist*365.0/30.0
    if ann_rev>0 and p0>0:
        years=buyback_target_supply/(ann_rev/p0)
        burn_series.append((d,years,ann_rev,p0))
current_fee_only_buyback_years=buyback_target_supply/max(rev30_ann/spot,1)
if burn_series:
    HW,HH=980,300; hL,hR,hT,hB=58,24,18,38
    vals_h=[min(y,150.0) for _,y,_,_ in burn_series]
    hlo=max(1.0,min(vals_h)*0.85); hhi=min(150.0,max(vals_h)*1.12)
    loghlo,loghhi=np.log(hlo),np.log(hhi)
    def hxy(idx,val):
        val=min(max(val,hlo),hhi)
        x=hL+(HW-hL-hR)*idx/max(1,(len(burn_series)-1))
        y=hT+(HH-hT-hB)*(1-(np.log(val)-loghlo)/(loghhi-loghlo))
        return x,y
    horizon_path=' '.join(('M' if i==0 else 'L')+f'{hxy(i,y)[0]:.1f},{hxy(i,y)[1]:.1f}' for i,(_,y,_,_) in enumerate(burn_series))
    hgrid=[]
    for t in np.geomspace(hlo,hhi,5):
        y=hxy(0,t)[1]
        hgrid.append(f'<line x1="{hL}" x2="{HW-hR}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eee"/><text x="8" y="{y+4:.1f}" class="axis">{t:.0f}y</text>')
    ly=burn_series[-1][1]; lypos=hxy(len(burn_series)-1, ly)[1]
    burn_horizon_svg=f'''<svg viewBox="0 0 {HW} {HH}" role="img" aria-label="Historical buyback horizon"><style>.axis{{font:12px Geist Mono,monospace;fill:#666}}</style><rect width="{HW}" height="{HH}" rx="12" fill="#fff"/>{''.join(hgrid)}<path d="{horizon_path}" fill="none" stroke="#171717" stroke-width="2.8"/><text x="{hL}" y="{HH-10}" class="axis">{burn_series[0][0]}</text><text x="{HW-140}" y="{HH-10}" class="axis">{burn_series[-1][0]}</text><text x="{HW-470}" y="24" class="axis">trailing-30D fee revenue annualized ÷ date price; target=circ+3Y gross issuance</text><text x="{HW-hR-5}" y="{lypos-8:.1f}" text-anchor="end" class="axis">latest {ly:.1f}y</text></svg>'''
else:
    current_fee_only_buyback_years=None
    burn_horizon_svg='<div class="desc">No historical buyback-horizon observations available.</div>'


# Implied EOY3 HL/Binance market-share chart from the same historical diagnostic.
ms_bt_series=[(d, terminal_share, ms90_hist, ms30_hist, ms180_hist) for d,_,_,_,_,_,_,terminal_share,ms90_hist,ms30_hist,ms180_hist in common]
# Force the latest chart point to the locked current model artifact, which uses MCP derivatives-volume MS windows.
# Prior points are historical revenue-implied diagnostics.
if ms_bt_series:
    latest_model_date=scaled_daily[-1][0]
    if ms_bt_series[-1][0] != latest_model_date:
        ms_bt_series.append((latest_model_date, vstats['eoy_market_share'], ms90_seed, ms30_mcp or latest[1], ms180_mcp or latest[2]))
    else:
        ms_bt_series[-1]=(latest_model_date, vstats['eoy_market_share'], ms90_seed, ms30_mcp or latest[1], ms180_mcp or latest[2])
if ms_bt_series:
    MW,MH=980,300; mL,mR,mT,mB=58,24,18,38
    # Alternative sensitivity: previous 24M-decay rule for comparison. Current model is 12M decay.
    ms_bt_series_24=[]
    for d,terminal12,ms90h,ms30h,ms180h in ms_bt_series:
        amp=min(max(ms30h/max(ms180h,1e-12),1.0),m.MS_AMPLIFIER_CAP)
        terminal24=min(ms90h*np.exp(np.log(amp)/6.0*(24/2.0)),m.MS_SHARE_CAP)
        ms_bt_series_24.append((d,terminal24))
    # Keep latest 24M comparison point aligned to MCP-derived current windows.
    latest_amp24=min(max((ms30_mcp or latest[1])/max((ms180_mcp or latest[2]),1e-12),1.0),m.MS_AMPLIFIER_CAP)
    latest_terminal24=min(ms90_seed*np.exp(np.log(latest_amp24)/6.0*(24/2.0)),m.MS_SHARE_CAP)
    ms_bt_series_24[-1]=(ms_bt_series[-1][0],latest_terminal24)
    vals_ms=[v for _,terminal,ms90h,ms30h,ms180h in ms_bt_series for v in (terminal,ms90h,ms30h,ms180h) if v is not None] + [v for _,v in ms_bt_series_24]
    mn=max(0,min(vals_ms)*0.85); mx=min(m.MS_SHARE_CAP, max(vals_ms)*1.12)
    def mxy(idx,val):
        x=mL+(MW-mL-mR)*idx/max(1,(len(ms_bt_series)-1))
        y=mT+(MH-mT-mB)*(1-(val-mn)/(mx-mn))
        return x,y
    path_terminal=' '.join(('M' if i==0 else 'L')+f'{mxy(i,v)[0]:.1f},{mxy(i,v)[1]:.1f}' for i,(_,v,_,_,_) in enumerate(ms_bt_series))
    path_terminal24=' '.join(('M' if i==0 else 'L')+f'{mxy(i,v)[0]:.1f},{mxy(i,v)[1]:.1f}' for i,(_,v) in enumerate(ms_bt_series_24))
    path_ms90=' '.join(('M' if i==0 else 'L')+f'{mxy(i,v)[0]:.1f},{mxy(i,v)[1]:.1f}' for i,(_,_,v,_,_) in enumerate(ms_bt_series))
    path_ms30=' '.join(('M' if i==0 else 'L')+f'{mxy(i,v)[0]:.1f},{mxy(i,v)[1]:.1f}' for i,(_,_,_,v,_) in enumerate(ms_bt_series))
    mgrid=[]
    for t in np.linspace(mn,mx,5):
        y=mxy(0,t)[1]
        mgrid.append(f'<line x1="{mL}" x2="{MW-mR}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eee"/><text x="8" y="{y+4:.1f}" class="axis">{t*100:.0f}%</text>')
    latest_terminal=ms_bt_series[-1][1]
    latest_y=mxy(len(ms_bt_series)-1, latest_terminal)[1]
    latest_y24=mxy(len(ms_bt_series_24)-1, latest_terminal24)[1]
    ms_eoy3_svg=f'''<svg viewBox="0 0 {MW} {MH}" role="img" aria-label="Model implied EOY3 Hyperliquid Binance market share"><style>.axis{{font:12px Geist Mono,monospace;fill:#666}}</style><rect width="{MW}" height="{MH}" rx="12" fill="#fff"/>{''.join(mgrid)}<path d="{path_ms30}" fill="none" stroke="#bbb" stroke-width="1.5" stroke-dasharray="5 5"/><path d="{path_ms90}" fill="none" stroke="#999" stroke-width="1.8"/><path d="{path_terminal}" fill="none" stroke="#0072f5" stroke-width="3.0"/><text x="{mL}" y="{MH-10}" class="axis">{ms_bt_series[0][0]}</text><text x="{MW-140}" y="{MH-10}" class="axis">{ms_bt_series[-1][0]}</text><text x="{MW-500}" y="24" class="axis">blue=current 12M decay · grey=MS90 · dashed=MS30</text><text x="{MW-mR-5}" y="{latest_y-8:.1f}" text-anchor="end" class="axis">12M {latest_terminal*100:.1f}%</text></svg>'''
else:
    ms_eoy3_svg='<div class="desc">No implied EOY3 market-share observations available.</div>'

W,H=980,280; padL,padR,padT,padB=54,20,18,34
vals=[v for _,a,b in chart for v in (a,b) if v is not None]
ymin=max(0,min(vals)*0.85); ymax=max(vals)*1.12
def xy(idx,val):
    x=padL+(W-padL-padR)*idx/(len(chart)-1); y=padT+(H-padT-padB)*(1-(val-ymin)/(ymax-ymin)); return x,y
path30=' '.join(('M' if i==0 else 'L')+f'{xy(i,a)[0]:.1f},{xy(i,a)[1]:.1f}' for i,(_,a,b) in enumerate(chart))
path180=' '.join(('M' if i==0 else 'L')+f'{xy(i,b)[0]:.1f},{xy(i,b)[1]:.1f}' for i,(_,a,b) in enumerate(chart))
grid=[]
for t in np.linspace(ymin,ymax,5):
    y=xy(0,t)[1]; grid.append(f'<line x1="{padL}" x2="{W-padR}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eee"/><text x="8" y="{y+4:.1f}" class="axis">{t*100:.0f}%</text>')
svg=f'''<svg viewBox="0 0 {W} {H}" role="img" aria-label="Hyperliquid market share rolling chart"><style>.axis{{font:12px Geist Mono,monospace;fill:#666}}</style><rect width="{W}" height="{H}" rx="12" fill="#fff"/>{''.join(grid)}<path d="{path180}" fill="none" stroke="#999" stroke-width="2.2"/><path d="{path30}" fill="none" stroke="#171717" stroke-width="2.8"/><text x="{padL}" y="{H-8}" class="axis">{chart[0][0]}</text><text x="{W-140}" y="{H-8}" class="axis">{chart[-1][0]}</text></svg>'''

def money(x):
    if x is None: return 'n/a'
    if abs(x)>=1e12: return f'${x/1e12:,.2f}T'
    if abs(x)>=1e9: return f'${x/1e9:,.2f}B'
    if abs(x)>=1e6: return f'${x/1e6:,.0f}M'
    return f'${x:,.0f}'
def pct(x): return 'n/a' if x is None else f'{x*100:.1f}%'
def price(x): return f'${x:,.2f}'
def ret(x): return 'n/a' if x is None else f'{x:+.1%}'
updates=mcp.get('top_5_trailing_30d_updates_from_defillama', [])
updates_html=''.join(f"<li><b>{u['update']}</b></li>" for u in updates[:5])
source_note='DefiLlama MCP checked: revenue excludes Coinbase/USDC yield; stablecoin yield is modeled separately.'
# For page coherence, display the same market-share windows used by the model artifact.
_model_ms = res['mc']['market_share']
ms30_mcp = _model_ms.get('ms30', ms30_mcp)
ms90_seed = float(_model_ms.get('ms90', ms90_seed)) if 'ms90_seed' in globals() else float(_model_ms.get('ms90'))
ms180_mcp = _model_ms.get('ms180', ms180_mcp)
ms_ratio_mcp = (ms30_mcp / ms180_mcp) if ms30_mcp and ms180_mcp else ms_ratio_mcp
html_doc=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Hyperliquid HYPE Valuation Dashboard</title><link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet"><style>:root{{--black:#171717;--muted:#666;--line:rgba(0,0,0,.08);--blue:#0072f5}}*{{box-sizing:border-box}}body{{margin:0;background:#fff;color:#171717;font-family:Geist,system-ui,sans-serif}}.wrap{{max-width:1180px;margin:0 auto;padding:0 24px}}header{{position:sticky;top:0;background:rgba(255,255,255,.88);backdrop-filter:blur(12px);z-index:4;box-shadow:0 0 0 1px var(--line)}}nav{{height:58px;display:flex;align-items:center;justify-content:space-between}}.brand{{font-weight:600}}.navmeta,.label,th,.formula{{font-family:'Geist Mono',monospace}}.navmeta,.desc,.label{{color:#666}}.hero{{padding:72px 0 44px;border-bottom:1px solid #ebebeb}}h1{{font-size:56px;line-height:.98;letter-spacing:-3px;margin:0 0 18px;font-weight:600;max-width:930px}}h2{{font-size:36px;letter-spacing:-1.8px;margin:0 0 22px}}h3{{font-size:21px;letter-spacing:-.6px;margin:0 0 12px}}.sub{{font-size:20px;line-height:1.6;color:#4d4d4d;max-width:820px}}.pill{{display:inline-flex;border-radius:999px;background:#ebf5ff;color:#0068d6;padding:4px 10px;font-size:12px;font-weight:500;margin-bottom:20px}}.grid{{display:grid;gap:16px}}.kpis{{grid-template-columns:repeat(auto-fit,minmax(190px,1fr));margin-top:30px}}.two{{grid-template-columns:1.35fr .9fr}}.three{{grid-template-columns:repeat(3,1fr)}}.card{{background:#fff;border-radius:10px;padding:20px;box-shadow:rgba(0,0,0,.08) 0 0 0 1px,rgba(0,0,0,.04) 0 2px 2px,rgba(0,0,0,.04) 0 8px 8px -8px,#fafafa 0 0 0 1px}}.value{{font-size:32px;line-height:1;letter-spacing:-1.4px;font-weight:600}}.desc{{margin-top:10px;font-size:14px;line-height:1.45}}section{{padding:52px 0;border-bottom:1px solid #ebebeb}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:11px 10px;border-bottom:1px solid #eee;text-align:left}}th{{font-size:12px;color:#666;font-weight:500;text-transform:uppercase}}td.num{{font-family:'Geist Mono',monospace;text-align:right}}.formula{{background:#fafafa;border-radius:8px;padding:14px;box-shadow:0 0 0 1px var(--line);font-size:13px;line-height:1.65;white-space:pre-wrap}}.callout{{background:#171717;color:#fff;border-radius:12px;padding:22px}}.callout .desc,.callout .label{{color:#aaa}}ul{{margin:0;padding-left:18px;line-height:1.55}}footer{{padding:34px 0;color:#666;font-size:13px}}@media(max-width:850px){{h1{{font-size:40px;letter-spacing:-2px}}.kpis,.three,.two{{grid-template-columns:1fr}}.wrap{{padding:0 16px}}}}</style></head><body><header><div class="wrap"><nav><div class="brand">HYPE / Hyperliquid</div><div class="navmeta">as of {res['asof_utc'][:10]} · DefiLlama MCP checked</div></nav></div></header><main><section class="hero"><div class="wrap"><div class="pill">Current market + 3Y GP capture model</div><h1>Hyperliquid market-share momentum, revenue quality, and HYPE valuation.</h1><p class="sub">Updated to use DefiLlama MCP derivatives volume/revenue aggregates, model stablecoin yield separately, and show percentile distribution + probability-weighted EV.</p><div class="grid kpis"><div class="card"><div class="label">Spot / mcap / circ</div><div class="value">{price(spot)}</div><div class="desc">Mcap {money(current_mcap)} · circ {market['circ_supply']/1e6:.0f}M HYPE.</div></div><div class="card"><div class="label">MS90 valuation seed</div><div class="value">{pct(ms90_seed)}</div><div class="desc">Starting HL/Binance share used in the model.</div></div><div class="card"><div class="label">MCP MS30 vs Binance</div><div class="value">{pct(ms30_mcp)}</div><div class="desc">DefiLlama 30D derivatives volume / Binance Futures proxy.</div></div><div class="card"><div class="label">MS30 / MS180</div><div class="value">{ms_ratio_mcp:.2f}×</div><div class="desc">Market-share trend growth. Recent record/near-record share signal is plausible.</div></div><div class="card"><div class="label">Growth velocity</div><div class="value">{velocity_pp_30d:+.1f}pp</div><div class="desc">30D share change vs prior rolling point.</div></div><div class="card"><div class="label">Selected P50 PV / token</div><div class="value">{price(p50_pv)}</div><div class="desc">Probability-weighted EV {price(base['probability_weighted_ev_price'])}.</div></div></div></div></section><section><div class="wrap grid two"><div class="card"><h2>Market share trend</h2>{svg}<p class="desc">Chart uses daily revenue-implied HL volume for rolling continuity; headline cards use DefiLlama MCP derivatives-volume aggregates.</p></div><div class="grid"><div class="card"><div class="label">Current data — MCP checked</div><table><tr><td>MS30 vs Binance</td><td class="num">{pct(ms30_mcp)}</td></tr><tr><td>MS180 vs Binance</td><td class="num">{pct(ms180_mcp)}</td></tr><tr><td>MS30/MS180 trend</td><td class="num">{ms_ratio_mcp:.2f}×</td></tr><tr><td>DefiLlama 30D fee revenue ann.</td><td class="num">{money(rev30_ann)}</td></tr><tr><td>DefiLlama 180D fee revenue ann.</td><td class="num">{money(rev180_ann)}</td></tr><tr><td>Buyback years: 30D fees + USDC yield</td><td class="num">{years_fee_plus_usdc:.1f}y</td></tr><tr><td>Fee-only 30D buyback years</td><td class="num">{current_fee_only_buyback_years:.1f}y</td></tr></table><p class="desc">{source_note}</p></div><div class="callout"><div class="label">Core revenue drivers</div><h3>Perps + stablecoin yield</h3><p class="desc">DefiLlama rows above are observed fee revenue. In the MC, future perps GP is modeled from Binance volume × HL share × 0.026% clean revenue take-rate. Stablecoin yield is modeled separately as USDC TVL × net yield × 90% capture; current USDC-yield run-rate is {money(current_usdc_ann)}.</p></div></div></div></section><section><div class="wrap"><h2>Model assumptions</h2><div class="grid two"><div class="card"><h3>Core revenue lines</h3><div class="formula">perp_GP_t = BinanceVol_t × HLShare_t × 0.026%\nUSDC_GP_t = USDC_TVL_t × net_yield × 90% / 12\nUSDC_TVL_t = current × (HL_vol_t / cur_HL_vol)^beta\nbeta: Bear 0.60 / Base 0.85 / Bull 1.00</div></div><div class="card"><h3>Valuation logic</h3><div class="formula">Y3 price = Y3 TTM GP × multiple / Y3 supply × 1.10\nPV = Y3 price / (1+25%)^3\nMultiple: 20x trough / 15x normal / 10x peak</div></div></div><div class="grid three" style="margin-top:16px"><div class="card"><div class="label">Supply velocity</div><div class="value">{base['modeled_monthly_supply_release']/1e6:.2f}M/mo</div><div class="desc">Selected-model gross release.</div></div><div class="card"><div class="label">3Y gross / burn / net</div><div class="value">{base['modeled_gross_release_3y']/1e6:.0f}M / {y3_burn_est/1e6:.0f}M / {(p50_supply-market['circ_supply'])/1e6:+.0f}M</div><div class="desc">Gross release / estimated burn / net supply change.</div></div><div class="card"><div class="label">Revenue inclusion</div><div class="value">Fees ≠ Yield</div><div class="desc">DefiLlama MCP income statement showed no USDC/stablecoin-yield line.</div></div></div></div></section><section><div class="wrap"><h2>Model outputs</h2><div class="card"><table><thead><tr><th>Case</th><th>P50 price</th><th>P50 mcap</th><th>P50 PV</th><th>EV PV/token</th><th>PV mcap EV</th><th>P(spot)</th></tr></thead><tbody><tr><td>Selected model</td><td class="num">{price(p50_price)}</td><td class="num">{money(p50_price*p50_supply)}</td><td class="num">{price(p50_pv)}</td><td class="num">{price(base['probability_weighted_ev_price'])}</td><td class="num">{money(base['probability_weighted_ev_mcap'])}</td><td class="num">{base['prob_current_spot_justified']:.1%}</td></tr></tbody></table></div><div class="grid kpis"><div class="card"><div class="label">Y3 GP / supply</div><div class="value">{money(p50_y3_gp)} / {p50_supply/1e6:.0f}M</div><div class="desc">Selected-model P50 end-Year-3.</div></div><div class="card"><div class="label">P50 path daily volume</div><div class="value">{money(vstats['avg_daily_volume'])}</div><div class="desc">Min {money(vstats['min_daily_volume'])} / Avg {money(vstats['avg_daily_volume'])} / Max {money(vstats['max_daily_volume'])}.</div></div><div class="card"><div class="label">EOY3 market share</div><div class="value">{pct(vstats['eoy_market_share'])}</div><div class="desc">After 12M velocity decay; gained share held.</div></div><div class="card"><div class="label">Total burn EOY3</div><div class="value">{y3_burn_est/1e6:.0f}M</div><div class="desc">Modeled cumulative token buyback/burn.</div></div></div></div></section><section><div class="wrap"><h2>Selected-model PV price distribution</h2><div class="card"><h3>Percentile ladder + probability-weighted EV</h3>{dist_svg}<p class="desc">Bars show selected-model PV/token percentiles. Black bar is P50 {price(p50_pv)}. Blue dashed line is probability-weighted EV {price(base['probability_weighted_ev_price'])}, which captures all paths including the right tail.</p></div></div></section><section><div class="wrap grid two"><div><h2>Historical entry backtest</h2><p class="sub">Historical model-shaped diagnostic, not a full MC replay: GOOD if model PV/spot &gt; 1.25, BAD if &lt; 0.75. Latest signal: <b>{latest_signal[1] if latest_signal else 'n/a'}</b>; last realized-return row: <b>{latest_realized_signal[0] if latest_realized_signal else 'n/a'}</b>.</p></div><div class="card"><table><thead><tr><th>Signal</th><th>Obs</th><th>Avg +30D</th><th>Avg +90D</th><th>Recent dates</th></tr></thead><tbody>{''.join(f'<tr><td>{b}</td><td class="num">{bt[b]["n"]}</td><td class="num">{ret(bt[b]["avg30"])}</td><td class="num">{ret(bt[b]["avg90"])}</td><td>{", ".join(bt[b]["last"][-3:])}</td></tr>' for b in ['GOOD','NEUTRAL','BAD'])}</tbody></table></div></div><div class="wrap" style="margin-top:16px"><div class="card"><h3>Backtest visual: spot vs model-shaped PV</h3>{backtest_svg}<p class="desc">Black line = HYPE spot. Blue line = model-shaped PV proxy using rolling MS90, MS30/MS180 velocity decay, Binance proxy, USDC-yield calibration, current multiple/supply assumptions, normalized so the latest point equals the locked selected-model P50 PV. Faded dots are recent unscored dates without enough forward return history. Still preliminary, not a full historical MC replay. Price history is pulled from Nov 2024, but this chart starts only once 180D MS windows are available.</p></div></div><div class="wrap" style="margin-top:16px"><div class="card"><h3>Historical buyback horizon</h3>{burn_horizon_svg}<p class="desc">Uses each date's HYPE price and trailing-30D annualized DefiLlama fee revenue only. Target = current circulating supply + modeled 3Y gross issuance, not theoretical FDV supply. Current fee-only 30D horizon is {current_fee_only_buyback_years:.1f}y; adding current modeled USDC yield would shorten it to {years_fee_plus_usdc:.1f}y.</p></div></div><div class="wrap" style="margin-top:16px"><div class="card"><h3>Model implied EOY3 Hyperliquid/Binance market share</h3>{ms_eoy3_svg}<p class="desc">This is the historical time series of the model-implied Year-3 terminal HL/Binance share using the same MS90 seed and MS30/MS180 velocity-decay rule. The current 12M-decay model point is {pct(vstats['eoy_market_share'])}. This shows the terminal share embedded in the locked valuation model.</p></div></div></section><section><div class="wrap grid two"><div><h2>DefiLlama MCP weekly answer</h2><p class="sub">Top 5 trailing-30D updates fetched now, not just scheduled.</p></div><div class="card"><ul>{updates_html}</ul></div></div></section></main><footer><div class="wrap">Generated from {RES_PATH.name}; MCP checked. Credentials not embedded.</div></footer></body></html>'''
out_dir=Path('/Users/momir_mini/vercel-html-illustrations/public/hype-dashboard')
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir/'index.html').write_text(html_doc)
print('WROTE', out_dir/'index.html')
print('MCP ms30', pct(ms30_mcp), 'ms180', pct(ms180_mcp), 'ratio', f'{ms_ratio_mcp:.2f}x')
print('base p50 pv', price(p50_pv), 'EV', price(base['probability_weighted_ev_price']))
print('bt', bt)
