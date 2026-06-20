#!/usr/bin/env python3
"""
Private Fund Weekly Slack Report
=================================
Reads data/performance.json + data/private_fund_positions.json,
fetches live prices, and posts a brief to a Slack Incoming Webhook.

Usage:
    SLACK_WEBHOOK_URL=https://hooks.slack.com/... python3 scripts/weekly_fund_report.py
    COINGECKO_API_KEY=CG-xxx python3 scripts/weekly_fund_report.py  # optional Pro key
"""
import json, os, sys, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request, urllib.error

REPO_ROOT = Path(__file__).parent.parent
PERF_FILE = REPO_ROOT / "data" / "performance.json"
POS_FILE  = REPO_ROOT / "data" / "private_fund_positions.json"

SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "")
CG_API_KEY    = os.environ.get("COINGECKO_API_KEY", "")

CRYPTO_IDS = [
    "bitcoin", "ethereum", "solana", "binancecoin",
    "hyperliquid", "chainlink", "zcash", "uniswap",
    "morpho", "sky", "venice-token",
]
STOCK_TICKERS = {"mstr": "MSTR", "coin": "COIN", "hood": "HOOD", "crcl": "CRCL"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_usd(n: float, decimals: int = 0) -> str:
    return f"{n:,.{decimals}f}"

def fmt_pct(n: float, sign: bool = True) -> str:
    s = f"{n:+.2f}%" if sign else f"{n:.2f}%"
    return s

def _get_json(url: str, headers: dict = {}) -> dict | None:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── Price fetching ────────────────────────────────────────────────────────────

def fetch_live_prices() -> dict[str, float]:
    prices: dict[str, float] = {}
    cg_base = "https://pro-api.coingecko.com/api/v3" if CG_API_KEY else "https://api.coingecko.com/api/v3"
    headers = {"x-cg-pro-api-key": CG_API_KEY} if CG_API_KEY else {}
    ids = ",".join(CRYPTO_IDS)
    data = _get_json(f"{cg_base}/simple/price?ids={ids}&vs_currencies=usd", headers)
    if data:
        for cid, v in data.items():
            prices[cid] = v["usd"]

    # Stocks via Yahoo Finance
    for asset_id, ticker in STOCK_TICKERS.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        data = _get_json(url, {"User-Agent": "Mozilla/5.0"})
        try:
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            prices[asset_id] = price
        except Exception:
            pass
    return prices


# ── TWR computation (mirrors the TypeScript dashboard logic) ──────────────────

def compute_twr(
    inception_fund: float,
    inception_deployed: float,
    history: list,
    current_value: float,
    current_deployed: float,
    full_exposure: bool = False,
) -> float | None:
    period_start = inception_fund
    period_deployed = inception_deployed
    chained = 1.0
    for entry in history:
        if entry.get("fundValueBeforeCashFlow") is None:
            return None
        ret = entry["fundValueBeforeCashFlow"] / period_start - 1
        factor = (1 + ret / (period_deployed / period_start)) if full_exposure else (1 + ret)
        chained *= factor
        period_start = entry["fundValueBeforeCashFlow"] + entry["cashFlow"]
        period_deployed = entry["deployed"]
    last_ret = current_value / period_start - 1
    last_factor = (1 + last_ret / (current_deployed / period_start)) if full_exposure else (1 + last_ret)
    chained *= last_factor
    return chained - 1


# ── Main ──────────────────────────────────────────────────────────────────────

def build_report() -> dict:
    perf = json.loads(PERF_FILE.read_text())
    pos_data = json.loads(POS_FILE.read_text())

    private_daily = perf["strategies"]["private"]["dailyData"]
    btc_daily     = perf["assets"]["bitcoin"]["dailyData"]
    private_metrics = perf["strategies"]["private"].get("metrics", {})
    last_updated  = perf.get("lastUpdated", "")

    positions = {p["id"]: p for p in pos_data["positions"]}
    execution_date   = pos_data["executionDate"]
    inception_date   = pos_data["inceptionDate"]
    inception_fund   = pos_data["inceptionFundSize"]
    inception_dep    = pos_data.get("inceptionDeployed", pos_data["totalDeployed"])
    total_deployed   = pos_data["totalDeployed"]
    rebal_history    = pos_data.get("rebalanceHistory", [])

    total_cash_flows = sum(e["cashFlow"] for e in rebal_history)
    net_invested     = inception_fund + total_cash_flows

    last_reb = rebal_history[-1] if rebal_history else None
    fund_val_after_last_cf = (
        last_reb["fundValueBeforeCashFlow"] + last_reb["cashFlow"]
        if last_reb and last_reb.get("fundValueBeforeCashFlow") is not None
        else inception_fund
    )
    cash_portion = fund_val_after_last_cf - total_deployed

    # Live prices
    live_prices = fetch_live_prices()
    is_live = bool(live_prices)

    # Position-level live P&L
    assets_by_id = perf.get("assets", {})
    portfolio: list[dict] = []
    total_pnl = 0.0
    for w in perf["strategies"]["private"].get("latestWeights", []):
        cid = w["coin"]
        pos = positions.get(cid)
        if not pos or not pos["allocation"]:
            continue
        exec_price = pos["executionPrice"]
        amount     = pos["amount"]
        allocation = pos["allocation"]
        lp = live_prices.get(cid)
        if lp and exec_price > 0:
            cur_price  = lp
            ret_pct    = (lp / exec_price - 1) * 100
            pnl_dollar = amount * (lp - exec_price)
        else:
            asset_data = assets_by_id.get(cid, {}).get("dailyData", [])
            exec_pt    = next((d for d in asset_data if d["date"] == execution_date), None)
            base_cr    = exec_pt["cumReturn"] if exec_pt else 1.0
            last_cr    = asset_data[-1]["cumReturn"] if asset_data else 1.0
            ret_since  = last_cr / base_cr - 1
            cur_price  = exec_price * (1 + ret_since)
            ret_pct    = ret_since * 100
            pnl_dollar = allocation * ret_since
        total_pnl += pnl_dollar
        portfolio.append({
            "id": cid,
            "name": assets_by_id.get(cid, {}).get("displayName", cid.upper()),
            "weight": w["weight"],
            "ret_pct": round(ret_pct, 2),
            "pnl_dollar": round(pnl_dollar, 2),
            "exec_price": exec_price,
            "cur_price": cur_price,
        })

    whole_fund_value = total_deployed + total_pnl + cash_portion
    whole_fund_pnl   = whole_fund_value - net_invested

    twr_raw = compute_twr(inception_fund, inception_dep, rebal_history, whole_fund_value, total_deployed)
    twr_pct = twr_raw * 100 if twr_raw is not None else (whole_fund_pnl / net_invested * 100 if net_invested else 0)

    # 7-day window: compare cumReturn from 7 trading days ago
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    def _7d_return(daily: list) -> float | None:
        if not daily:
            return None
        end_cr   = daily[-1]["cumReturn"]
        start_pt = next((d for d in reversed(daily) if d["date"] <= cutoff), None)
        if not start_pt:
            return None
        return (end_cr / start_pt["cumReturn"] - 1) * 100

    fund_7d = _7d_return(private_daily)
    btc_7d  = _7d_return(btc_daily)

    # Inception returns
    btc_inception = (btc_daily[-1]["cumReturn"] - 1) * 100 if btc_daily else 0

    # Sort for top movers
    sorted_asc  = sorted(portfolio, key=lambda x: x["ret_pct"])
    top_gainers = sorted(portfolio, key=lambda x: x["ret_pct"], reverse=True)[:4]
    top_laggards = sorted_asc[:4]

    return {
        "date": today,
        "last_updated": last_updated,
        "is_live": is_live,
        "inception_date": inception_date,
        "execution_date": execution_date,
        "inception_fund": inception_fund,
        "net_invested": net_invested,
        "total_deployed": total_deployed,
        "cash_portion": cash_portion,
        "whole_fund_value": whole_fund_value,
        "whole_fund_pnl": whole_fund_pnl,
        "twr_pct": twr_pct,
        "fund_7d": fund_7d,
        "btc_7d": btc_7d,
        "btc_inception": btc_inception,
        "sharpe": private_metrics.get("sharpe"),
        "max_dd": private_metrics.get("maxDrawdown"),
        "win_rate": private_metrics.get("winRate"),
        "portfolio": portfolio,
        "top_gainers": top_gainers,
        "top_laggards": top_laggards,
        "total_pnl_deployed": (total_pnl / total_deployed * 100) if total_deployed else 0,
    }


def sign(n: float) -> str:
    return "+" if n >= 0 else "-"

def color_for(n: float) -> str:
    return "good" if n >= 0 else "danger"

def emoji_for(n: float) -> str:
    return ":chart_with_upwards_trend:" if n >= 0 else ":chart_with_downwards_trend:"


def build_slack_payload(r: dict) -> dict:
    fund_color = color_for(r["twr_pct"])
    week_color = color_for(r["fund_7d"] or 0)

    header_text = (
        f":bar_chart: *IOSG Private Fund — Weekly Brief* | {r['date']}"
    )

    # Fund overview block
    price_label = "live" if r["is_live"] else "eod"
    overview_lines = [
        f"*Inception Capital:*  ${fmt_usd(r['inception_fund'])}  (since {r['inception_date']})",
        f"*Net Invested:*  ${fmt_usd(r['net_invested'])}  _(after cash flows)_",
        f"*Deployed (50% signal):*  ${fmt_usd(r['total_deployed'])}",
        f"*Cash Portion:*  ${fmt_usd(r['cash_portion'])}",
        f"*Current Fund Value ({price_label}):*  *${fmt_usd(r['whole_fund_value'])}*",
        f"*Total P&L:*  *{sign(r['whole_fund_pnl'])}${fmt_usd(abs(r['whole_fund_pnl']))}*  _{'+' if r['whole_fund_pnl'] >= 0 else ''}{r['whole_fund_pnl'] / r['net_invested'] * 100:.2f}% on invested_",
        f"*TWR since inception:*  *{'+' if r['twr_pct'] >= 0 else ''}{r['twr_pct']:.2f}%*  {emoji_for(r['twr_pct'])}",
    ]

    # 7-day section
    def pp(n: float) -> str:
        return f"{'+' if n >= 0 else ''}{n:.2f}%"

    fund_7d_str = pp(r['fund_7d']) if r['fund_7d'] is not None else "n/a"
    btc_7d_str  = pp(r['btc_7d'])  if r['btc_7d']  is not None else "n/a"
    alpha_7d    = (r['fund_7d'] - r['btc_7d']) if (r['fund_7d'] is not None and r['btc_7d'] is not None) else None
    alpha_str   = f"{pp(alpha_7d)} vs BTC" if alpha_7d is not None else ""

    weekly_lines = [
        f"*Fund Index (7d):*  {emoji_for(r['fund_7d'] or 0)} *{fund_7d_str}*",
        f"*Bitcoin (7d):*  {emoji_for(r['btc_7d'] or 0)} {btc_7d_str}",
    ]
    if alpha_str:
        weekly_lines.append(f"*Alpha (7d):*  {emoji_for(alpha_7d)} _{alpha_str}_")

    # vs Bitcoin since inception
    weekly_lines.append("")
    alpha_inception = r["twr_pct"] - r["btc_inception"]
    weekly_lines.append(
        f"*Fund vs BTC (inception):*  Fund {pp(r['twr_pct'])}  |  BTC {pp(r['btc_inception'])}  →  Alpha {pp(alpha_inception)}"
    )

    # Risk metrics
    sharpe_str  = f"{r['sharpe']:.2f}" if r['sharpe'] is not None else "—"
    maxdd_str   = f"{r['max_dd']:.2f}%" if r['max_dd'] is not None else "—"
    winrate_str = f"{r['win_rate']:.1f}%" if r['win_rate'] is not None else "—"
    risk_text   = f"Sharpe: *{sharpe_str}*  |  Max DD: *{maxdd_str}*  |  Win Rate: *{winrate_str}*"

    # Top movers
    def mover_line(a: dict) -> str:
        e = "🟢" if a["ret_pct"] >= 0 else "🔴"
        ret_str = f"{'+'  if a['ret_pct'] >= 0 else ''}{a['ret_pct']:.2f}%"
        pnl_str = f"{'+'  if a['pnl_dollar'] >= 0 else '-'}${fmt_usd(abs(a['pnl_dollar']))}"
        return f"{e} *{a['name']}* ({a['weight']:.1f}%)  {ret_str}  ({pnl_str})"

    gainers_text  = "\n".join(mover_line(a) for a in r["top_gainers"])
    laggards_text = "\n".join(mover_line(a) for a in r["top_laggards"])

    # Full positions table (compact text)
    pos_lines = ["```", f"{'Asset':<18} {'Wt':>5}  {'ExecPx':>10}  {'Now':>10}  {'Ret%':>7}  {'P&L $':>9}"]
    pos_lines.append("-" * 68)
    for a in sorted(r["portfolio"], key=lambda x: -x["weight"]):
        cp = a["cur_price"]
        cp_str = f"${cp:,.2f}" if cp >= 1 else f"${cp:.4f}"
        ep_str = f"${a['exec_price']:,.2f}" if a["exec_price"] >= 1 else f"${a['exec_price']:.4f}"
        sign_r = "+" if a["ret_pct"] >= 0 else ""
        sign_p = "+" if a["pnl_dollar"] >= 0 else "-"
        pos_lines.append(
            f"{a['name']:<18} {a['weight']:>4.1f}%  {ep_str:>10}  {cp_str:>10}  {sign_r}{a['ret_pct']:>5.1f}%  {sign_p}${abs(a['pnl_dollar']):>7,.0f}"
        )
    dep_ret = r["total_pnl_deployed"]
    total_pnl_sum = sum(a['pnl_dollar'] for a in r['portfolio'])
    sign_dep = "+" if dep_ret >= 0 else ""
    sign_tp  = "+" if total_pnl_sum >= 0 else "-"
    pos_lines.append("-" * 68)
    pos_lines.append(f"{'TOTAL DEPLOYED':.<30} {sign_dep}{dep_ret:.2f}%  {sign_tp}${fmt_usd(abs(total_pnl_sum))}")
    pos_lines.append("```")
    positions_text = "\n".join(pos_lines)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"IOSG Private Fund — Weekly Brief | {r['date']}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(overview_lines)}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": ":calendar: *Last 7 Days & Inception Comparison*\n" + "\n".join(weekly_lines)}},
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f":trophy: *Top Gainers (vs execution)*\n{gainers_text}"},
                {"type": "mrkdwn", "text": f":rotating_light: *Laggards (vs execution)*\n{laggards_text}"},
            ],
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":shield: *Risk Metrics (since {r['inception_date']})*\n{risk_text}"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":clipboard: *All Positions* _(data: {r['last_updated']}, prices: {'live' if r['is_live'] else 'eod'})\n{positions_text}"}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Generated {r['date']} · Crypto via CoinGecko · Stocks via Yahoo Finance · execution {r['execution_date']}"}],
        },
    ]
    return {"blocks": blocks}


def post_to_slack(payload: dict) -> bool:
    if not SLACK_WEBHOOK:
        print("ERROR: SLACK_WEBHOOK_URL not set. Set it as an environment variable.")
        return False
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        SLACK_WEBHOOK, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = r.read().decode()
            if resp == "ok":
                print("Slack message sent successfully.")
                return True
            print(f"Slack response: {resp}")
            return False
    except urllib.error.HTTPError as e:
        print(f"Slack HTTP error {e.code}: {e.read().decode()}")
        return False
    except Exception as e:
        print(f"Slack send error: {e}")
        return False


def main():
    print("Building report…")
    r = build_report()
    print(f"  Fund value: ${fmt_usd(r['whole_fund_value'])}  |  TWR: {r['twr_pct']:.2f}%  |  7d: {r['fund_7d']:.2f}%" if r['fund_7d'] else "")
    payload = build_slack_payload(r)

    if "--dry-run" in sys.argv:
        print(json.dumps(payload, indent=2))
        return

    post_to_slack(payload)


if __name__ == "__main__":
    main()
