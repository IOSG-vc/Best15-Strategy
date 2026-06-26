# CycleSignal crash cluster / SH crash-gate overlay — latest local code

Latest code file found locally by modified time and methodology relevance:

- Source: `/Users/iosgmini/end_02_v3_k3_one_step_10_90_add20_138/diagnose_sh_locked_convention.py`
- Copied as: `crash_cluster_overlay_latest_locked_convention.py`
- Source mtime: `2026-06-11 12:24:57`
- SHA256: `a7e06691d260e5b32793903a9ef54181c0ecc8997f4fbb3a02130c45efe157e2`

What this version does:

- Applies the SH crash gate as a post-V4 multiplicative exposure overlay.
- Uses the locked CycleSignal convention: prior-day exposure earns today's BTC return (`exp.shift(1) * btc_return`) and turnover cost after final exposure.
- Keeps event response lagged by one day: crash event on day `t` affects intensity/exposure from `t+1` onward.
- Variants in code:
  - `A_locked_SH`
  - `B_floor35`
  - `C_strong`

Inputs expected by the script as currently written:

`/Users/iosgmini/end_02_v3_k3_one_step_10_90_add20_138/outputs_fresh_130_sqrtn_k3_cbrtM_20260610_rerun/attachments_for_momir/fresh_rerun_daily_requested_columns.csv`

Main output directory:

`/Users/iosgmini/end_02_v3_k3_one_step_10_90_add20_138/sh_locked_convention_diagnostics_20260611`

Included reference metrics:

- `aggregate_metrics_by_window.csv`

Note: an older Frank reproduction script also exists at `incoming_v4_sh_crash_gate_repro/run_v4_sh_overlay_current_test.py`, but that package used same-day-style accounting for the incoming artifact. The file attached here is the newer locked-convention diagnostic/overlay version.
