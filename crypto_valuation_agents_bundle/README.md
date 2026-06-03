# Crypto valuation agents bundle

Files:
- `COMBINED_CODE.md` — single forwardable document with all cron prompts and source inline.
- `cron_jobs_sanitized.json` — sanitized Hermes cron definitions; no private Discord chat IDs.
- `recreate_cron_jobs.py` — helper to recreate the cron jobs via Hermes CLI; edit `WORKDIR`/`DELIVER` first.
- `src/` — source/locked-model files used by the jobs.

Runtime notes:
- Python deps: `requests`, `numpy`, and standard library. Some scripts may optionally use live public APIs.
- ETHFI may use a Dune API key if available; do not hardcode it. Put it in the recipient's env/secrets setup.
- Schedules: Mon/Fri 09:00 for per-token jobs; Friday 18:00 for EOW ranking.
- Hermes skill used by UNI/JUP/EOW: `crypto-gp-capture-valuation`.
