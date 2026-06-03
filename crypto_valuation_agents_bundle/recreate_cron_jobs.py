#!/usr/bin/env python3
"""Recreate the valuation cron jobs in Hermes.
Edit WORKDIR and delivery target below before running.
Run: python recreate_cron_jobs.py
"""
import json, subprocess, tempfile
from pathlib import Path

WORKDIR = str(Path.cwd() / 'src')  # change if you put src elsewhere
DELIVER = 'origin'                 # or 'discord', 'telegram', 'local'
TOOLSETS = 'terminal,file,web'

jobs = json.loads(Path('cron_jobs_sanitized.json').read_text())['jobs']
for j in jobs:
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt') as f:
        f.write(j['prompt'])
        prompt_file = f.name
    cmd = [
        'hermes', 'cron', 'create', j['schedule'],
        '--name', j['name'],
        '--prompt-file', prompt_file,
        '--deliver', DELIVER,
        '--toolsets', TOOLSETS,
        '--workdir', WORKDIR,
    ]
    for skill in j.get('skills') or []:
        cmd += ['--skill', skill]
    print('Creating:', j['name'])
    print(' '.join(cmd))
    subprocess.run(cmd, check=True)
