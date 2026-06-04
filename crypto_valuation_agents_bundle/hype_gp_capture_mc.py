#!/usr/bin/env python3
import csv, io, json, math, os, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import numpy as np
import requests

OUTDIR = os.path.dirname(__file__)
np.random.seed(42)

_CG_KEY = os.environ.get("COINGECKO_API_KEY", "")
_CG_BASE = "https://pro-api.coingecko.com/api/v3" if _CG_KEY else "https://api.coingecko.com/api/v3"
_CG_HEADERS = {"x-cg-pro-api-key": _CG_KEY} if _CG_KEY else {}

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

CG_ID = "hyperliquid"
N_PATHS = 100_000
MONTHS = 36
GP_MARGIN = 0.985
TOKEN_CAPTURE = 1.0
BUYBACK_RATE = 1.0
# Conservative inflation schedule inherited from original HYPE agent; offset by buybacks.
CORE_MONTHLY_EMISSION = 9_916_667
CORE_MONTHS_LEFT = 20
ERP = 0.04
SELECTED_DISCOUNT_RATE = 0.25  # User override for HYPE
# Blockworks annual Binance Futures volume calibration from original HYPE agent.
BLOCKWORKS_ANNUAL = {2022: 9.543e12, 2023: 8.401e12, 2024: 15.971e12, 2025: 25.241e12}
MULT_BEAR_TROUGH = 20.0
MULT_NORMAL = 15.0
MULT_BULL_PEAK = 10.0


def get_json(url, params=None, method="GET", payload=None, timeout=30):
    hdrs = _CG_HEADERS if "coingecko.com" in url else {}
    if method == "POST":
        r = requests.post(url, json=payload, headers=hdrs, timeout=timeout)
    else:
        r = requests.get(url, params=params, headers=hdrs, timeout=timeout)
    r.raise_for_status()
    return r.json()


def cg_market():
    return get_json(
        f"{_CG_BASE}/coins/markets",
        params={"vs_currency":"usd","ids":CG_ID,"sparkline":"false","price_change_percentage":"24h"},
    )[0]


def cg_prices(days="max"):
    data = get_json(f"{_CG_BASE}/coins/{CG_ID}/market_chart", params={"vs_currency":"usd","days":days})
    by_date = {}
    for ts_ms, price in data["prices"]:
        dt = datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc).date()
        by_date[dt] = float(price)
    return sorted(by_date.items())


def fred_series(series="DGS10"):
    if FRED_API_KEY:
        # Use the FRED API (more reliable in CI than the public fredgraph.csv endpoint)
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": series, "api_key": FRED_API_KEY, "file_type": "json",
                    "observation_start": "2000-01-01", "sort_order": "asc"},
            timeout=30,
        )
        r.raise_for_status()
        vals = []
        for obs in r.json().get("observations", []):
            try:
                vals.append((datetime.strptime(obs["date"], "%Y-%m-%d").date(), float(obs["value"])))
            except Exception:
                pass
        return vals
    # Fallback: public CSV (may be geo-blocked in some CI environments)
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=30)
    r.raise_for_status()
    vals = []
    for row in csv.DictReader(io.StringIO(r.text)):
        try:
            vals.append((datetime.strptime(row['observation_date'], '%Y-%m-%d').date(), float(row[series])))
        except Exception:
            pass
    return vals


def sp500_prices():
    vals = fred_series("SP500")
    return [(d,v) for d,v in vals if v > 0]


def log_returns(series, cutoff=None, min_n=60):
    if cutoff:
        s=[(d,v) for d,v in series if d >= cutoff]
        if len(s) < min_n:
            s=series
    else:
        s=series
    vals=[]
    last=None
    for d,v in s:
        if last and last > 0 and v > 0:
            vals.append(math.log(v/last))
        last=v
    return np.array(vals, dtype=float)


def defillama_revenue():
    data = get_json("https://api.llama.fi/summary/fees/hyperliquid?dataType=dailyRevenue")
    chart = data.get("totalDataChart", [])
    rows=[]
    if chart:
        for ts, val in chart:
            rows.append((datetime.fromtimestamp(ts, tz=timezone.utc).date(), float(val or 0)))
    else:
        for ts, parts in data.get("totalDataChartBreakdown", []):
            total=0.0
            if isinstance(parts, dict):
                for vals in parts.values():
                    if isinstance(vals, dict):
                        total += sum(float(x or 0) for x in vals.values())
                    else:
                        total += float(vals or 0)
            rows.append((datetime.fromtimestamp(ts, tz=timezone.utc).date(), total))
    rows = [(d,v) for d,v in rows if v==v]
    rows.sort()
    return rows


def binance_btc_futures_daily():
    # Binance API is often geo-blocked; data.binance.vision public ZIPs work.
    import zipfile
    rows=[]
    now = datetime.now(timezone.utc)
    y, m = 2022, 1
    while (y < now.year) or (y == now.year and m <= now.month):
        url = f"https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-{y}-{m:02d}.zip"
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and r.content[:2] == b'PK':
            z = zipfile.ZipFile(io.BytesIO(r.content))
            name = z.namelist()[0]
            text = z.read(name).decode('utf-8')
            reader = csv.reader(io.StringIO(text))
            for row in reader:
                if not row or row[0] == 'open_time':
                    continue
                try:
                    open_time = int(row[0])
                    quote_vol = float(row[7])
                    # Some files use microsecond timestamps; normalize.
                    if open_time > 10_000_000_000_000:
                        open_time = open_time // 1000
                    d = datetime.fromtimestamp(open_time/1000, tz=timezone.utc).date()
                    rows.append((d, quote_vol))
                except Exception:
                    pass
        # advance month
        m += 1
        if m == 13:
            y += 1; m = 1
        time.sleep(0.03)
    rows.sort()
    return rows


def monthly_sums(rows):
    m=defaultdict(float)
    for d,v in rows:
        m[(d.year,d.month)] += v
    return [(k, v) for k,v in sorted(m.items()) if v > 0]


def conservative_monthly_start(rows, trailing_30):
    """Start from min(last 30D data, median monthly value over last 6 calendar months)."""
    months = monthly_sums(rows)
    last6 = [v for _, v in months[-6:]]
    if not last6:
        return trailing_30, float('nan'), trailing_30
    med6 = float(np.median(np.array(last6, dtype=float)))
    return min(float(trailing_30), med6), med6, float(trailing_30)


def choose_monthly_return_distribution():
    daily = binance_btc_futures_daily()
    # Scale BTCUSDT quote volume to total Binance futures volume using Blockworks
    # annual total Binance futures volume, then use total-futures log returns.
    annual_btc = defaultdict(float)
    for d, v in daily:
        annual_btc[d.year] += v
    shares = {yr: annual_btc[yr] / bw for yr, bw in BLOCKWORKS_ANNUAL.items() if annual_btc.get(yr, 0) > 0 and bw > 0}
    latest_share = shares[max(shares.keys())]
    scaled_daily = []
    for d, v in daily:
        share = shares.get(d.year, latest_share)
        scaled_daily.append((d, v / share))
    monthly = monthly_sums(scaled_daily)
    vals = [v for _,v in monthly]
    rets=[]
    for a,b in zip(vals[:-1], vals[1:]):
        if a>0 and b>0:
            rets.append(math.log(b/a))
    rets=np.array(rets, dtype=float)
    lo,hi=np.percentile(rets,[1,99])
    return monthly, np.clip(rets, lo, hi), shares


def discount_rate():
    # Only used for the "calculated reference" rate shown in the report.
    # The model always uses SELECTED_DISCOUNT_RATE for actual MC paths.
    try:
        hp = cg_prices("365")
        spy = sp500_prices()
        rf = fred_series("DGS10")[-1][1] / 100.0
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=365)
        hp_ret = log_returns(hp, cutoff=cutoff)
        spy_ret = log_returns(spy, cutoff=cutoff)
        if len(hp_ret) < 60: hp_ret = log_returns(hp)
        if len(spy_ret) < 60: spy_ret = log_returns(spy)[-252:]
        hp_std=float(np.std(hp_ret, ddof=1)); spy_std=float(np.std(spy_ret, ddof=1))
        dr = rf + ERP * (hp_std / spy_std)
        return dr, rf, hp_std, spy_std, len(hp_ret), len(spy_ret)
    except Exception as e:
        print(f"[HYPE] discount_rate() fetch failed ({e}); using NaN for reference fields")
        return float('nan'), float('nan'), float('nan'), float('nan'), 0, 0


def percentile_ranks(x):
    order=np.argsort(x)
    ranks=np.empty_like(order, dtype=float)
    ranks[order] = (np.arange(len(x))+1)/len(x)
    return ranks


def multiple_for_ranks(ranks):
    return np.where(ranks <= 0.20, MULT_BEAR_TROUGH, np.where(ranks >= 0.80, MULT_BULL_PEAK, MULT_NORMAL)).astype(float)


CORE_QUANTILES = [25, 50, 75]
CHART_QUANTILES = [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95]


def pct_dict(x, qs=CORE_QUANTILES):
    return {f"p{q}": float(np.percentile(x, q)) for q in qs}


def run_model():
    market=cg_market()
    spot=float(market['current_price']); mcap=float(market['market_cap'])
    fdv=market.get('fully_diluted_valuation'); fdv=float(fdv) if fdv else float('nan')
    circ=float(market.get('circulating_supply') or (mcap/spot))
    total_supply=market.get('total_supply'); total_supply=float(total_supply) if total_supply else float('nan')

    rev=defillama_revenue(); rev_vals=np.array([v for _,v in rev], dtype=float)
    last_date=rev[-1][0]
    trailing_30=float(rev_vals[-30:].sum()); trailing_90=float(rev_vals[-90:].sum())
    current_monthly_rev, median_6m_monthly_rev, last_30d_rev = conservative_monthly_start(rev, trailing_30)
    current_annual_rev=current_monthly_rev*365/30
    current_annual_gp=current_annual_rev*GP_MARGIN
    ttm_rev=float(rev_vals[-365:].sum()) if len(rev_vals)>=365 else float(rev_vals.sum()*365/len(rev_vals))
    ttm_gp=ttm_rev*GP_MARGIN

    btc_monthly, ret_arr, btcusdt_shares=choose_monthly_return_distribution()
    draws=np.random.choice(ret_arr, size=(N_PATHS, MONTHS), replace=True)
    growth=np.exp(np.cumsum(draws, axis=1))
    monthly_gp=current_monthly_rev*growth*GP_MARGIN
    y3_ttm_gp=monthly_gp[:,-12:].sum(axis=1)
    # Multiple should depend on the Year-3 volume/GP regime used for the denominator,
    # not a single final-month growth print. Since GP is proportional to volume here,
    # rank Y3 trailing 12M GP as the volume-regime proxy.
    ranks=percentile_ranks(y3_ttm_gp)
    multiple=multiple_for_ranks(ranks)

    supply=np.full(N_PATHS, circ, dtype=float)
    for t in range(MONTHS):
        start=max(0,t-11)
        gp_window=monthly_gp[:,start:t+1].sum(axis=1)*(12.0/(t-start+1))
        interim_rank=percentile_ranks(gp_window)
        interim_mult=multiple_for_ranks(interim_rank)
        prices=(gp_window*interim_mult*TOKEN_CAPTURE)/np.maximum(supply,1)
        buy_tokens=(monthly_gp[:,t]*BUYBACK_RATE)/np.maximum(prices,0.01)
        buy_tokens=np.minimum(buy_tokens, supply*0.80)
        emissions = CORE_MONTHLY_EMISSION if t < CORE_MONTHS_LEFT else 0.0
        supply = supply + emissions - buy_tokens
    y3_supply=supply
    y3_token_price=(y3_ttm_gp*multiple*TOKEN_CAPTURE)/np.maximum(y3_supply,1)

    dr,rf,hp_std,spy_std,n_hp,n_spy=discount_rate()
    selected_dr = SELECTED_DISCOUNT_RATE
    sens=[max(0,selected_dr-0.10), max(0,selected_dr-0.05), selected_dr, selected_dr+0.05, selected_dr+0.10]
    sens=sorted(set([round(x,6) for x in sens]))
    pv_selected = y3_token_price/((1+selected_dr)**3)

    quantile_components = {}
    for q in CHART_QUANTILES:
        target = np.percentile(pv_selected, q)
        idx = int(np.argmin(np.abs(pv_selected - target)))
        quantile_components[f"p{q}"] = {
            "discounted_price": float(pv_selected[idx]),
            "undiscounted_y3_price": float(y3_token_price[idx]),
            "y3_ttm_gp": float(y3_ttm_gp[idx]),
            "multiple": float(multiple[idx]),
            "y3_supply": float(y3_supply[idx]),
            "volume_regime_percentile": float(ranks[idx]),
        }

    return {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "market": {"spot":spot,"mcap":mcap,"fdv":fdv,"circ_supply":circ,"total_supply":total_supply},
        "revenue": {"defillama_last_date":str(last_date),"trailing_30d_revenue":trailing_30,"median_6m_monthly_revenue":median_6m_monthly_rev,"conservative_start_monthly_revenue":current_monthly_rev,"trailing_90d_revenue":trailing_90,"current_annualized_revenue_30d":current_annual_rev,"current_annualized_gp_30d":current_annual_gp,"ttm_revenue":ttm_rev,"ttm_gp":ttm_gp,"gp_margin":GP_MARGIN},
        "mc": {"paths":N_PATHS,"months":MONTHS,"btc_futures_months":len(btc_monthly),"volume_proxy":"total Binance futures, BTCUSDT-scaled via Blockworks annual totals","btcusdt_shares":{str(k):float(v) for k,v in btcusdt_shares.items()},"monthly_log_return_mean":float(np.mean(ret_arr)),"monthly_log_return_std":float(np.std(ret_arr,ddof=1)),"monthly_log_return_p25":float(np.percentile(ret_arr,25)),"monthly_log_return_p50":float(np.percentile(ret_arr,50)),"monthly_log_return_p75":float(np.percentile(ret_arr,75))},
        "discount": {"selected":float(selected_dr),"calculated":float(dr),"risk_free":float(rf),"erp":ERP,"hype_daily_stdev":hp_std,"spy_daily_stdev":spy_std,"n_hype_days":n_hp,"n_spy_days":n_spy,"sensitivity_rates":sens},
        "outputs": {"y3_ttm_gp":pct_dict(y3_ttm_gp),"y3_supply":pct_dict(y3_supply),"multiple_counts":{"10x_peak":int((multiple==10).sum()),"15x_normal":int((multiple==15).sum()),"20x_trough":int((multiple==20).sum())},"y3_token_price":pct_dict(y3_token_price),"discounted_token_price":pct_dict(pv_selected),"price_distribution":{"discounted":pct_dict(pv_selected, CHART_QUANTILES),"undiscounted_y3":pct_dict(y3_token_price, CHART_QUANTILES)},"quantile_components":quantile_components,"ev_mean":float(np.mean(pv_selected)),"undiscounted_ev_mean":float(np.mean(y3_token_price)),"prob_impairment_vs_spot":float(np.mean(pv_selected<spot)),"prob_current_spot_justified":float(np.mean(pv_selected>=spot)),"prob_3x_vs_spot":float(np.mean(pv_selected>=3*spot)),"undiscounted_prob_impairment_vs_spot":float(np.mean(y3_token_price<spot)),"undiscounted_prob_current_spot_justified_y3":float(np.mean(y3_token_price>=spot)),"undiscounted_prob_3x_vs_spot":float(np.mean(y3_token_price>=3*spot))},
        "pv_sensitivity": {f"{r:.1%}": pct_dict(y3_token_price/((1+r)**3)) for r in sens},
    }


def fmt_money(x):
    if x is None or not (x==x): return 'n/a'
    ax=abs(x)
    if ax>=1e9: return f"${x/1e9:,.2f}B"
    if ax>=1e6: return f"${x/1e6:,.1f}M"
    if ax>=1e3: return f"${x/1e3:,.1f}K"
    return f"${x:,.2f}"


def write_report(res):
    o=res['outputs']; m=res['market']; r=res['revenue']; d=res['discount']; mc=res['mc']
    spot=m['spot']
    y3=o['y3_token_price']
    discounted=o['discounted_token_price']
    pv_calc=discounted

    def row(label, p25, p50, p75, money=True):
        if money:
            return f"| {label:<22} | ${p25:>8.2f} | ${p50:>8.2f} | ${p75:>8.2f} |"
        return f"| {label:<22} | {p25:>9} | {p50:>9} | {p75:>9} |"

    verdict = "expensive on discounted median"
    if discounted['p50'] > spot * 1.25:
        verdict = "attractive on discounted median"
    elif discounted['p50'] >= spot * 0.85:
        verdict = "roughly fair on discounted median"

    lines=[]
    lines.append("# HYPE 3Y GP-Capture MC — Concise Result")
    lines.append(f"As of: {res['asof_utc']}")
    lines.append("")
    lines.append("## Key Insight")
    lines.append(f"- **Verdict:** {verdict}.")
    lines.append(f"- Current spot **${spot:.2f}** vs **discounted fair value P50 of ${discounted['p50']:.2f}** using HYPE's selected **25.0%** discount rate.")
    lines.append(f"- Discounted P25/P50/P75 is **${discounted['p25']:.2f} / ${discounted['p50']:.2f} / ${discounted['p75']:.2f}**; undiscounted Y3 P50 is **${y3['p50']:.2f}**.")
    lines.append(f"- Upside is still meaningful on discounted basis: **{o['prob_3x_vs_spot']:.1%} probability of 3x+**, but impairment risk is **{o['prob_impairment_vs_spot']:.1%}**.")
    lines.append("")
    lines.append("## Market + GP Base")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Spot | ${spot:.2f} |")
    lines.append(f"| Market cap | {fmt_money(m['mcap'])} |")
    lines.append(f"| FDV | {fmt_money(m['fdv'])} |")
    lines.append(f"| Circulating supply | {m['circ_supply']/1e6:,.1f}M HYPE |")
    lines.append(f"| DeFiLlama revenue latest date | {r['defillama_last_date']} |")
    lines.append(f"| 30D protocol revenue | {fmt_money(r['trailing_30d_revenue'])} |")
    lines.append(f"| Median monthly revenue, last 6M | {fmt_money(r['median_6m_monthly_revenue'])} |")
    lines.append(f"| Conservative monthly start | {fmt_money(r['conservative_start_monthly_revenue'])} |")
    lines.append(f"| Annualized start GP @ 98.5% margin | {fmt_money(r['current_annualized_gp_30d'])} |")
    lines.append(f"| TTM GP @ 98.5% margin | {fmt_money(r['ttm_gp'])} |")
    lines.append("")
    lines.append("## Main Output — Discounted Fair Value")
    lines.append("")
    lines.append("| Distribution | P25 | P50 | P75 |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| Discounted token price @ 25% | ${discounted['p25']:.2f} | ${discounted['p50']:.2f} | ${discounted['p75']:.2f} |")
    lines.append(f"| Undiscounted Y3 token price | ${y3['p25']:.2f} | ${y3['p50']:.2f} | ${y3['p75']:.2f} |")
    lines.append(f"| Y3 trailing 12M GP | {fmt_money(o['y3_ttm_gp']['p25'])} | {fmt_money(o['y3_ttm_gp']['p50'])} | {fmt_money(o['y3_ttm_gp']['p75'])} |")
    lines.append(f"| Y3 supply | {o['y3_supply']['p25']/1e6:,.1f}M | {o['y3_supply']['p50']/1e6:,.1f}M | {o['y3_supply']['p75']/1e6:,.1f}M |")
    lines.append("")
    lines.append("## Price Distribution for Chart")
    lines.append("")
    lines.append("Main chart series = discounted fair value at 25%. Undiscounted Y3 is supporting context.")
    lines.append("")
    lines.append("```text")
    lines.append("Pct   Discounted PV   Undisc. Y3")
    lines.append("----  -------------   ----------")
    for q in CHART_QUANTILES:
        key=f"p{q}"
        lines.append(f"P{q:<3}  ${o['price_distribution']['discounted'][key]:>10.2f}   ${o['price_distribution']['undiscounted_y3'][key]:>9.2f}")
    lines.append("```")
    lines.append("")
    lines.append("## Probability Summary")
    lines.append("")
    lines.append("| Metric | Probability |")
    lines.append("|---|---:|")
    lines.append(f"| Impairment vs current spot, discounted | {o['prob_impairment_vs_spot']:.1%} |")
    lines.append(f"| Current spot justified, discounted | {o['prob_current_spot_justified']:.1%} |")
    lines.append(f"| 3x+ vs current spot, discounted | {o['prob_3x_vs_spot']:.1%} |")
    lines.append("")
    lines.append("## Discounted Entry Sensitivity")
    lines.append("")
    lines.append(f"Selected HYPE discount rate: **{d['selected']:.1%}**. Model-calculated liquid-token rate shown for reference: **{d['calculated']:.1%}** = {d['risk_free']:.2%} risk-free + {d['erp']:.1%} ERP × {d['hype_daily_stdev']/d['spy_daily_stdev']:.2f}x HYPE/S&P stdev ratio")
    lines.append("")
    lines.append("| Discount rate | PV P25 | PV P50 | PV P75 |")
    lines.append("|---:|---:|---:|---:|")
    for rate, vals in res['pv_sensitivity'].items():
        lines.append(f"| {rate} | ${vals['p25']:.2f} | ${vals['p50']:.2f} | ${vals['p75']:.2f} |")
    lines.append("")
    lines.append("## Why P75 Jumps vs P50")
    lines.append("")
    lines.append("The multiple is regime-dependent, but the **representative P50/P60/P75 PV paths are all still in the normal Year-3 trailing-volume regime**. The peak-volume haircut only starts above the 80th percentile of Year-3 trailing GP/volume, where the model drops from 15x to 10x.")
    lines.append("")
    lines.append("| Component at PV quantile path | P50 | P75 | P75/P50 |")
    lines.append("|---|---:|---:|---:|")
    qc=o['quantile_components']; q50=qc['p50']; q75=qc['p75']
    lines.append(f"| Discounted price | ${q50['discounted_price']:.2f} | ${q75['discounted_price']:.2f} | {q75['discounted_price']/q50['discounted_price']:.2f}x |")
    lines.append(f"| Y3 trailing 12M GP | {fmt_money(q50['y3_ttm_gp'])} | {fmt_money(q75['y3_ttm_gp'])} | {q75['y3_ttm_gp']/q50['y3_ttm_gp']:.2f}x |")
    lines.append(f"| Multiple | {q50['multiple']:.0f}x | {q75['multiple']:.0f}x | {q75['multiple']/q50['multiple']:.2f}x |")
    lines.append(f"| Volume regime pctile | {q50['volume_regime_percentile']:.1%} | {q75['volume_regime_percentile']:.1%} | n/a |")
    lines.append(f"| Y3 supply | {q50['y3_supply']/1e6:,.1f}M | {q75['y3_supply']/1e6:,.1f}M | {q75['y3_supply']/q50['y3_supply']:.2f}x |")
    lines.append("")
    lines.append("So the jump is not coming from assigning a richer multiple to P75. P75 is still below the top-20% peak-volume bucket, so it keeps the normal 15x multiple; above P80 the model applies the peak-cycle haircut to 10x, but GP can still be high enough for prices to keep rising.")
    lines.append("")
    lines.append("## Core Assumptions")
    lines.append("")
    lines.append("```text")
    lines.append("Assumption                  Setting")
    lines.append("--------------------------  -----------------------------------------------")
    lines.append("Horizon                     36 months")
    lines.append(f"Paths                       {mc['paths']:,}")
    lines.append("Discount rate               25% selected for HYPE")
    lines.append("Calculated discount ref     shown separately via liquid-token framework")
    lines.append("GP denominator              protocol revenue × 98.5% GP margin")
    lines.append("Token capture               100%, no discount")
    lines.append("Buybacks                    reduce future supply, offset by emissions")
    lines.append(f"Inflation/emissions         {CORE_MONTHLY_EMISSION/1e6:.1f}M HYPE/month for {CORE_MONTHS_LEFT} months")
    lines.append("Multiple regime             20x trough / 15x normal / 10x peak volume")
    lines.append("Multiple denominator        Year-3 trailing 12M GP")
    lines.append("Market proxy                BTCUSDT Binance futures monthly volume, 2022+")
    lines.append(f"Monthly log-return mean/std {mc['monthly_log_return_mean']:.2%} / {mc['monthly_log_return_std']:.2%}")
    lines.append("Current benchmark           current spot price")
    lines.append("Output focus                discounted fair value P25/P50/P75")
    lines.append("```")
    lines.append("")
    lines.append("## Caveats / Next Checks")
    lines.append("- DeFiLlama revenue is used as GP base; should verify against protocol-native revenue/fee data.")
    lines.append("- Supply benefit depends on whether assistance fund purchases should be treated as removed effective float.")
    lines.append("- Multiple regime is inherited from prior HYPE model; next refinement is peer multiple sanity check + historical calibration.")
    report='\n'.join(lines)+"\n"
    with open(os.path.join(OUTDIR,'hype_3y_gp_capture_result.md'),'w') as f: f.write(report)
    with open(os.path.join(OUTDIR,'hype_3y_gp_capture_result.json'),'w') as f: json.dump(res,f,indent=2)
    return os.path.join(OUTDIR,'hype_3y_gp_capture_result.md'), report

if __name__ == '__main__':
    res=run_model(); path, report=write_report(res); print(report); print('\nSaved:', path)
