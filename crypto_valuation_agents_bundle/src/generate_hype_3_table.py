import json, re, math, os, datetime
from pathlib import Path
import requests

WD = Path('/Users/momir_mini/.openclaw/workspace/altcoin_research')
J = json.loads((WD/'hype_3y_gp_capture_12m_start_run.json').read_text())
prev_txt = (WD/'hype_latest_3_table_report.md').read_text() if (WD/'hype_latest_3_table_report.md').exists() else ''
locked_txt = (WD/'hype_locked_report_2026-05-08.md').read_text()


def money(x):
    ax=abs(x)
    if ax>=1e12: return f"${x/1e12:.2f}T"
    if ax>=1e9: return f"${x/1e9:.2f}B"
    if ax>=1e6: return f"${x/1e6:.1f}M"
    return f"${x:,.0f}"

def price(x): return f"${x:.2f}"
def mult(x): return f"{x:.1f}x"
def pct(x): return f"{x*100:.1f}%"
def hype_m(x): return f"{x/1e6:.1f}M"

def extract(pattern, text, cast=float):
    m=re.search(pattern, text)
    if not m: return None
    s=m.group(1).replace('$','').replace(',','').replace('M','e6').replace('B','e9').replace('x','').replace('%','')
    try: return cast(eval(s))
    except Exception:
        try: return cast(s)
        except Exception: return m.group(1)

# HYPE volume data via CoinGecko, with previous report fallback for 30D/peak if API fails.
hype_current_vol = None; hype_30d_vol = None; hype_peak_vol = None; hype_peak_date = None; vol_note='live'
try:
    r=requests.get('https://api.coingecko.com/api/v3/coins/markets', params={'vs_currency':'usd','ids':'hyperliquid','sparkline':'false'}, timeout=20, headers={'User-Agent':'hype-report/1.0'})
    r.raise_for_status(); mkt=r.json()[0]
    hype_current_vol=float(mkt.get('total_volume') or 0)
    r=requests.get('https://api.coingecko.com/api/v3/coins/hyperliquid/market_chart', params={'vs_currency':'usd','days':'365','interval':'daily'}, timeout=30, headers={'User-Agent':'hype-report/1.0'})
    r.raise_for_status(); chart=r.json(); vols=chart.get('total_volumes', [])
    last30=vols[-30:] if len(vols)>=30 else vols
    hype_30d_vol=sum(v for _,v in last30)/len(last30)
    peak=max(vols, key=lambda tv: tv[1])
    hype_peak_vol=float(peak[1]); hype_peak_date=datetime.datetime.utcfromtimestamp(peak[0]/1000).date().isoformat()
except Exception as e:
    vol_note=f'fallback stale ({type(e).__name__})'
    hype_current_vol = extract(r'HYPE native 24h vol\s+\$([0-9.]+B)', prev_txt) or extract(r'HYPE current native 24h vol\s+\$([0-9.]+B)', locked_txt)
    hype_30d_vol = extract(r'HYPE 30D vol proxy\s+\$([0-9.]+B)', prev_txt) or extract(r'HYPE 30D avg vol proxy\s+\$([0-9.]+B)', locked_txt)
    hype_peak_vol = extract(r'HYPE hist peak proxy\s+\$([0-9.]+B)', prev_txt) or extract(r'HYPE historical peak vol proxy\s+\$([0-9.]+B)', locked_txt)
    m=re.search(r'HYPE hist peak proxy\s+\$[0-9.]+B on ([0-9-]+)', prev_txt) or re.search(r'HYPE historical peak vol proxy\s+\$[0-9.]+B on ([0-9-]+)', locked_txt)
    hype_peak_date=m.group(1) if m else 'n/a'

market=J['market']; rev=J['revenue']; mc=J['mc']; scs=J['scenarios']
base=scs['base_db_observed_emissions']; opt=scs['upside_db_observed_plus_optionality']; bear=scs['bear_worst_case_emissions']
vs=base['volume_sanity']
start_gp=rev['current_annualized_gp']; ttm=rev['ttm_gp']

# Create exact three sections.
lines=[]
lines.append('# HYPE 3Y GP-Capture — Latest 3-Table Report')
lines.append(f"As of: `{J['asof_utc']}`")
lines.append(f"Spot: **{price(market['spot'])}**")
lines.append('')
lines.append('## Key assumptions')
lines.append('```text')
rows=[
('Horizon','36 months'),('MC paths',f"{mc['paths']:,}"),('Discount rate','25% selected HYPE rate'),('Start rule','min(30D rev, 12M median rev)'),('30D revenue',money(rev['trailing_30d_revenue'])),('12M median monthly rev',money(rev['median_12m_monthly_revenue'])),('Selected start GP/mo',money(rev['conservative_start_monthly_revenue'])),('Annualized start GP',money(start_gp)),('TTM GP',money(ttm)),('GP denominator','DeFiLlama dailyRevenue = net GP'),('GP margin','100% on DeFiLlama revenue'),('Token capture','100%'),('Base emissions','0.962M HYPE/mo DB observed'),('Worst-case emissions','9.92M HYPE/mo only in bear'),('Buybacks','100% net GP reduces future supply'),('Optionality','Base +10% Y3 value sensitivity'),('Multiple regime','20x trough / 15x normal / 10x peak'),('Multiple denom.','Year-3 trailing 12M GP'),('Proxy mean / stdev',f"{mc['monthly_log_return_mean']*100:.2f}% / {mc['monthly_log_return_std']*100:.2f}%")]
for k,v in rows: lines.append(f"{k:<24} {v}")
lines.append('```')
lines.append('')
lines.append('## Model results')
lines.append('```text')
lines.append(f"{'Metric':<24} {'Base':>10} {'+10% opt':>10} {'Bear':>10}")
lines.append(f"{'-'*24} {'-'*10} {'-'*10} {'-'*10}")
for label, key, fmt in [
('Disc FV P50',('discounted_token_price','p50'),price),('Disc EV / mean',('discounted_ev',),price),('Disc FV P25',('discounted_token_price','p25'),price),('Disc FV P75',('discounted_token_price','p75'),price),('Disc FV P90',('discounted_token_price','p90'),price),('Y3 P50 undiscounted',('undiscounted_y3_token_price','p50'),price),('Y3 TTM GP P50',('y3_ttm_gp','p50'),money),('Y3 supply P50',('y3_supply','p50'),hype_m),('P(spot justified)',('prob_current_spot_justified',),pct),('P(3x+)',('prob_3x_vs_spot',),pct)]:
    def get(sc):
        val=sc
        for kk in key: val=val[kk]
        return fmt(val)
    lines.append(f"{label:<24} {get(base):>10} {get(opt):>10} {get(bear):>10}")
lines.append('```')
lines.append('')
lines.append('## Sanity checks + current multiples')
lines.append('```text')
sanity=[
('Current spot',price(market['spot'])),('Market cap',money(market['mcap'])),('FDV',money(market['fdv'])),('Circ supply',f"{market['circ_supply']/1e6:.1f}M HYPE"),('Total supply',f"{market['total_supply']/1e6:.1f}M HYPE"),('MCap / TTM GP',mult(market['mcap']/ttm)),('FDV / TTM GP',mult(market['fdv']/ttm)),('MCap / start GP',mult(market['mcap']/start_gp)),('FDV / start GP',mult(market['fdv']/start_gp)),('Current monthly GP',money(rev['conservative_start_monthly_revenue'])),('Buyback cap @ spot',f"{base['current_buy_tokens_per_month']/1e6:.2f}M HYPE/mo"),('Base emissions','0.96M HYPE/mo'),('Net supply now',f"{base['net_monthly_supply_now']/1e6:+.2f}M HYPE/mo"),('Years buy full supply',f"{base['buyback_years_simple']:.1f}y"),('Y3 TTM GP P50',money(base['y3_ttm_gp']['p50'])),('Clean treasury take-rate','0.026% of notional'),('Implied Y3 HYPE vol',money(vs['implied_hype_daily_volume_y3_p50'])),('Binance current vol',money(vs['current_binance_futures_daily_volume'])),('Binance peak vol',money(vs['peak_binance_futures_daily_volume'])),('Implied / Binance cur',pct(vs['implied_vs_current_binance'])),('Implied / Binance peak',pct(vs['implied_vs_peak_binance'])),('HYPE native 24h vol',money(hype_current_vol)),('HYPE 30D vol proxy',money(hype_30d_vol)+(f" ({vol_note})" if vol_note!='live' else '')),('HYPE hist peak proxy',money(hype_peak_vol)+f" on {hype_peak_date}"),('Implied / HYPE cur',pct(vs['implied_hype_daily_volume_y3_p50']/hype_current_vol) if hype_current_vol else 'n/a'),('Implied / HYPE 30D',pct(vs['implied_hype_daily_volume_y3_p50']/hype_30d_vol) if hype_30d_vol else 'n/a'),('Implied / HYPE peak',pct(vs['implied_hype_daily_volume_y3_p50']/hype_peak_vol) if hype_peak_vol else 'n/a')]
for k,v in sanity: lines.append(f"{k:<24} {v}")
lines.append('```')
lines.append('')
lines.append('**Bottom line:** P50 remains below spot, while EV/mean remains above spot due to right-skew. Base buybacks are now only slightly above DB-observed emissions, and simple buyback-years has crossed the 20y watch level.')
report='\n'.join(lines)+'\n'
(WD/'hype_latest_3_table_report.md').write_text(report)

# Drift metrics: use locked and previous markdown where possible.
def locked_val(label):
    # Finds '$nn.nM/B' or 'nn.ny/nn.n%' style after exact-ish label
    return None

# Parse previous current report values from the pre-overwrite text.
def rex(label, unit=None):
    pat=re.escape(label)+r'\s+([^\n]+)'
    m=re.search(pat, prev_txt)
    return m.group(1).strip() if m else None

# Numeric drift helpers from known fields in locked report.
locked_spot = extract(r'Spot:\s+\*\*\$([0-9.]+)\*\*', locked_txt)
prev_spot = extract(r'Spot:\s+\*\*\$([0-9.]+)\*\*', prev_txt)
locked_30d = extract(r'30D revenue\s+\$([0-9.]+M)', locked_txt)
prev_30d = extract(r'30D revenue\s+\$([0-9.]+M)', prev_txt)
locked_ttm = extract(r'TTM GP\s+\$([0-9.]+M)', locked_txt)
prev_ttm = extract(r'TTM GP\s+\$([0-9.]+M)', prev_txt)
locked_buyyears = extract(r'Years to buy full supply\s+([0-9.]+)y', locked_txt)
prev_buyyears = extract(r'Years buy full supply\s+([0-9.]+)y', prev_txt)
locked_curvol = extract(r'HYPE current native 24h vol\s+\$([0-9.]+B)', locked_txt) or extract(r'HYPE native 24h vol\s+\$([0-9.]+B)', locked_txt)
prev_curvol = extract(r'HYPE native 24h vol\s+\$([0-9.]+B)', prev_txt)

summary={
 'report': report,
 'vol_note': vol_note,
 'hype_current_vol': hype_current_vol,
 'hype_30d_vol': hype_30d_vol,
 'hype_peak_vol': hype_peak_vol,
 'hype_peak_date': hype_peak_date,
 'locked': {'spot':locked_spot,'30d':locked_30d,'ttm':locked_ttm,'buyyears':locked_buyyears,'curvol':locked_curvol},
 'prev': {'spot':prev_spot,'30d':prev_30d,'ttm':prev_ttm,'buyyears':prev_buyyears,'curvol':prev_curvol}
}
(WD/'hype_report_summary.json').write_text(json.dumps(summary, indent=2))
print(str(WD/'hype_latest_3_table_report.md'))
print('vol_note', vol_note)
