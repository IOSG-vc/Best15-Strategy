#!/usr/bin/env python3
import math
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/Users/iosgmini/end_02_v3_k3_one_step_10_90_add20_138')
INP = ROOT / 'outputs_fresh_130_sqrtn_k3_cbrtM_20260610_rerun/attachments_for_momir/fresh_rerun_daily_requested_columns.csv'
OUT = ROOT / 'sh_locked_convention_diagnostics_20260611'
OUT.mkdir(exist_ok=True)
ANN = 365.25
COST = 0.001

VARIANTS = {
    'A_locked_SH': dict(vol_window=180, z_threshold=1.5, half_life=126, jump=0.20, floor=0.15, midpoint=2.0, slope=5.0),
    'B_floor35': dict(vol_window=180, z_threshold=1.5, half_life=126, jump=0.20, floor=0.35, midpoint=2.0, slope=5.0),
    'C_strong': dict(vol_window=365, z_threshold=1.5, half_life=91, jump=0.35, floor=0.15, midpoint=2.0, slope=5.0),
}
WINDOWS = {
    'full_2020_26': ('2020-01-01', '2026-06-10'),
    '2020_22': ('2020-01-01', '2021-12-31'),
    '2022_24': ('2022-01-01', '2023-12-31'),
    '2024_26': ('2024-01-01', '2026-06-10'),
}
CRASH_WINDOWS = {
    'mar_2020': ('2020-03-01', '2020-03-31'),
    'may_jul_2021': ('2021-05-01', '2021-07-31'),
    'nov_2021_jun_2022': ('2021-11-01', '2022-06-30'),
    'calendar_2024_latest': ('2024-01-01', '2026-06-10'),
}

def load_base():
    df = pd.read_csv(INP, parse_dates=['date']).set_index('date').sort_index()
    df = df.loc['2020-01-01':'2026-06-10'].copy()
    df.index = df.index.tz_localize(None).normalize()
    df['btc_return'] = df['btc_return'].astype(float)
    df['baseline_exposure'] = df['k3_cbrtM_exposure'].astype(float)
    return df

def intensity_gate(r, p):
    minp = min(p['vol_window'], max(30, p['vol_window']//4))
    vol = r.rolling(p['vol_window'], min_periods=minp).std().replace(0, np.nan)
    z = r / vol
    event = (z <= -p['z_threshold']).astype(float).fillna(0.0)
    decay = math.exp(-math.log(2) / p['half_life'])
    vals = []
    inten = 0.0
    for ev in event.shift(1).fillna(0.0).values:
        inten = decay * inten + p['jump'] * float(ev)
        vals.append(float(inten))
    intensity = pd.Series(vals, index=r.index, name='intensity')
    gate = (p['floor'] + (1-p['floor']) / (1 + np.exp(p['slope'] * (intensity - p['midpoint'])))).clip(p['floor'], 1.0)
    return event, intensity, gate, z

def build_daily(df):
    dailies = {}
    base_exp = df['baseline_exposure']
    r = df['btc_return']
    # locked convention: prior-day exposure earns today's BTC return; no initial turnover cost at eval cut.
    base_turnover = base_exp.diff().abs().fillna(0.0)
    base_ret = base_exp.shift(1).fillna(base_exp.iloc[0]) * r - base_turnover * COST
    base = pd.DataFrame({
        'btc_close': df['close'], 'btc_return': r, 'strategy': 'baseline_v4_cbrtM_locked',
        'exposure': base_exp, 'gate': 1.0, 'intensity': 0.0, 'severity_event_date': 0.0,
        'turnover': base_turnover, 'cost_return': base_turnover*COST, 'strategy_return': base_ret,
    }, index=df.index)
    base['equity'] = (1+base['strategy_return']).cumprod()
    dailies['baseline_v4_cbrtM_locked'] = base
    for name, p in VARIANTS.items():
        event, inten, gate, z = intensity_gate(r, p)
        exp = base_exp * gate
        turnover = exp.diff().abs().fillna(0.0)
        ret = exp.shift(1).fillna(exp.iloc[0]) * r - turnover * COST
        dd = pd.DataFrame({
            'btc_close': df['close'], 'btc_return': r, 'strategy': name,
            'exposure': exp, 'gate': gate, 'intensity': inten, 'severity_event_date': event,
            'turnover': turnover, 'cost_return': turnover*COST, 'strategy_return': ret,
        }, index=df.index)
        dd['equity'] = (1+dd['strategy_return']).cumprod()
        dailies[name] = dd
    return dailies

def metric(ret, exp=None, turnover=None, cost=None):
    r = ret.dropna().astype(float)
    if len(r) < 2:
        return {}
    eq = (1+r).cumprod()
    n = len(r)
    cagr = eq.iloc[-1] ** (ANN/n) - 1
    ann_ret_arith = r.mean() * ANN
    vol = r.std(ddof=1) * math.sqrt(ANN)
    down = r[r<0]
    downvol = down.std(ddof=1) * math.sqrt(ANN) if len(down)>1 else np.nan
    mdd = (eq/eq.cummax()-1).min()
    return {
        'days': n,
        'total_return': eq.iloc[-1]-1,
        'cagr': cagr,
        'arith_ann_return': ann_ret_arith,
        'ann_vol': vol,
        'cagr_sharpe': cagr/vol if vol>0 else np.nan,
        'arith_sharpe': ann_ret_arith/vol if vol>0 else np.nan,
        'sortino_cagr': cagr/downvol if downvol and downvol>0 else np.nan,
        'max_drawdown': mdd,
        'calmar': cagr/abs(mdd) if mdd<0 else np.nan,
        'avg_exposure': exp.mean() if exp is not None else np.nan,
        'latest_exposure': exp.iloc[-1] if exp is not None else np.nan,
        'avg_turnover': turnover.mean() if turnover is not None else np.nan,
        'fee_drag': cost.sum() if cost is not None else np.nan,
    }

def period_sharpe(r):
    r = r.dropna().astype(float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return np.nan
    return r.mean()/r.std(ddof=1)*math.sqrt(ANN)

def period_return(r):
    return (1+r.dropna()).prod()-1

def resample_periods(series, freq, start, end):
    s = series.loc[start:end]
    return list(s.resample(freq))

def win_counts(dailies):
    rows=[]
    freqs = [('monthly','ME'),('quarterly','QE'),('annual','YE')]
    base = dailies['baseline_v4_cbrtM_locked']['strategy_return']
    for win, (start,end) in WINDOWS.items():
        for fname,freq in freqs:
            for name,d in dailies.items():
                if name == 'baseline_v4_cbrtM_locked':
                    continue
                ret_w=ret_l=ret_t=sh_w=sh_l=sh_t=periods=0
                ret_delta_sum=ret_delta_pos_sum=ret_delta_neg_sum=0.0
                for _, br in base.loc[start:end].resample(freq):
                    idx=br.index
                    vr=d['strategy_return'].reindex(idx).dropna(); br=br.reindex(vr.index).dropna()
                    if len(vr)<2 or len(br)<2: continue
                    periods += 1
                    vr_ret, br_ret = period_return(vr), period_return(br)
                    vr_sh, br_sh = period_sharpe(vr), period_sharpe(br)
                    delta = vr_ret - br_ret
                    ret_delta_sum += delta
                    if delta > 0: ret_delta_pos_sum += delta
                    elif delta < 0: ret_delta_neg_sum += delta
                    ret_w += vr_ret > br_ret; ret_l += vr_ret < br_ret; ret_t += vr_ret == br_ret
                    sh_w += vr_sh > br_sh; sh_l += vr_sh < br_sh; sh_t += vr_sh == br_sh
                rows.append({'window':win,'freq':fname,'strategy':name,'periods':periods,
                             'ret_wins':ret_w,'ret_losses':ret_l,'ret_ties':ret_t,
                             'arith_sharpe_wins':sh_w,'arith_sharpe_losses':sh_l,'arith_sharpe_ties':sh_t,
                             'sum_period_return_delta':ret_delta_sum,
                             'positive_delta_sum':ret_delta_pos_sum,
                             'negative_delta_sum':ret_delta_neg_sum})
    return pd.DataFrame(rows)

def period_contrib(dailies):
    rows=[]
    base = dailies['baseline_v4_cbrtM_locked']['strategy_return']
    for freq_name, freq in [('monthly','ME'),('quarterly','QE'),('annual','YE')]:
        for name,d in dailies.items():
            if name == 'baseline_v4_cbrtM_locked': continue
            for label, br in base.resample(freq):
                idx=br.index
                vr=d['strategy_return'].reindex(idx).dropna(); br=br.reindex(vr.index).dropna()
                if len(vr)<2 or len(br)<2: continue
                rows.append({
                    'freq':freq_name,'period_end':label.strftime('%Y-%m-%d'),'strategy':name,
                    'baseline_return':period_return(br),'strategy_return':period_return(vr),
                    'return_delta':period_return(vr)-period_return(br),
                    'baseline_arith_sharpe':period_sharpe(br),'strategy_arith_sharpe':period_sharpe(vr),
                    'arith_sharpe_delta':period_sharpe(vr)-period_sharpe(br),
                })
    return pd.DataFrame(rows)

def aggregate_metrics(dailies):
    rows=[]
    for win,(start,end) in WINDOWS.items():
        bmet = None
        for name,d in dailies.items():
            x=d.loc[start:end]
            m=metric(x['strategy_return'], x['exposure'], x['turnover'], x['cost_return'])
            m.update({'window':win,'strategy':name,'start':start,'end':end})
            rows.append(m)
    df=pd.DataFrame(rows)
    base_cols=['cagr_sharpe','cagr','arith_sharpe','ann_vol','max_drawdown','total_return']
    out=[]
    for win,g in df.groupby('window', sort=False):
        b=g[g.strategy=='baseline_v4_cbrtM_locked'].iloc[0]
        for _,r in g.iterrows():
            rr=r.to_dict()
            for c in base_cols:
                rr['d_'+c]=r[c]-b[c]
            out.append(rr)
    return pd.DataFrame(out)

def crash_metrics(dailies):
    rows=[]
    for win,(start,end) in CRASH_WINDOWS.items():
        b=None
        for name,d in dailies.items():
            x=d.loc[start:end]
            m=metric(x['strategy_return'], x['exposure'], x['turnover'], x['cost_return'])
            m.update({'crash_window':win,'strategy':name,'start':start,'end':end})
            rows.append(m)
    df=pd.DataFrame(rows)
    out=[]
    for win,g in df.groupby('crash_window', sort=False):
        b=g[g.strategy=='baseline_v4_cbrtM_locked'].iloc[0]
        for _,r in g.iterrows():
            rr=r.to_dict()
            for c in ['total_return','cagr_sharpe','max_drawdown','avg_exposure','fee_drag']:
                rr['d_'+c]=r[c]-b[c]
            out.append(rr)
    return pd.DataFrame(out)

def main():
    df=load_base(); dailies=build_daily(df)
    for name,d in dailies.items(): d.to_csv(OUT/f'{name}_daily.csv')
    agg=aggregate_metrics(dailies); wins=win_counts(dailies); contrib=period_contrib(dailies); crash=crash_metrics(dailies)
    gate=[]
    for name,d in dailies.items():
        if name=='baseline_v4_cbrtM_locked': continue
        g=d['gate']
        gate.append({'strategy':name,'gate_mean':g.mean(),'gate_median':g.median(),'gate_min':g.min(),'days_gate_lt_0p95':int((g<.95).sum()),'days_gate_lt_0p75':int((g<.75).sum()),'days_gate_lt_0p50':int((g<.5).sum()),'events':int(d['severity_event_date'].sum()),'avg_intensity':d['intensity'].mean(),'max_intensity':d['intensity'].max()})
    gate=pd.DataFrame(gate)
    # contribution summaries
    cs=[]
    for (freq,name),g in contrib.groupby(['freq','strategy']):
        pos=g[g.return_delta>0]; neg=g[g.return_delta<0]
        cs.append({'freq':freq,'strategy':name,'periods':len(g),'positive_delta_periods':len(pos),'negative_delta_periods':len(neg),'zero_delta_periods':int((g.return_delta==0).sum()),'sum_return_delta':g.return_delta.sum(),'sum_positive_delta':pos.return_delta.sum(),'sum_negative_delta':neg.return_delta.sum(),'top5_positive_delta':pos.return_delta.sort_values(ascending=False).head(5).sum(),'top5_negative_delta':neg.return_delta.sort_values().head(5).sum()})
    cs=pd.DataFrame(cs)
    agg.to_csv(OUT/'aggregate_metrics_by_window.csv',index=False)
    wins.to_csv(OUT/'win_counts_by_window.csv',index=False)
    contrib.to_csv(OUT/'period_delta_details.csv',index=False)
    cs.to_csv(OUT/'period_delta_contribution_summary.csv',index=False)
    crash.to_csv(OUT/'crash_window_metrics.csv',index=False)
    gate.to_csv(OUT/'gate_stats.csv',index=False)
    # Print compact summaries
    print('OUT', OUT)
    print('\nFULL AGG')
    print(agg[agg.window=='full_2020_26'][['strategy','cagr_sharpe','cagr','arith_sharpe','ann_vol','max_drawdown','avg_exposure','latest_exposure','d_cagr_sharpe','d_cagr','d_max_drawdown']].to_string(index=False))
    print('\nSUBPERIOD CAGR_SHARPE / CAGR / MAXDD DELTAS')
    print(agg[agg.strategy!='baseline_v4_cbrtM_locked'][['window','strategy','cagr_sharpe','cagr','max_drawdown','d_cagr_sharpe','d_cagr','d_max_drawdown']].to_string(index=False))
    print('\nWIN COUNTS')
    print(wins[['window','freq','strategy','periods','ret_wins','ret_losses','arith_sharpe_wins','arith_sharpe_losses','sum_period_return_delta']].to_string(index=False))
    print('\nPERIOD DELTA CONTRIBUTION SUMMARY')
    print(cs.to_string(index=False))
    print('\nGATE')
    print(gate.to_string(index=False))

if __name__ == '__main__':
    main()
