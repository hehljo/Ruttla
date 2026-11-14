"""Offline rule verification with retained logs; never builds/deploys the app."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import fcntl
import json
import os
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', required=True, type=Path, help='Directory for fresh retained logs (may be on an external disk)')
    parser.add_argument('--target', type=Path, help='Optional read-only real project control')
    options = parser.parse_args()
    base = options.output_root.resolve()
    base.mkdir(parents=True, exist_ok=True)
    with (base / 'safe-area.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run = base / ('safe-area-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
        run.mkdir()
        report = {'status': 'running', 'scope': 'offline source checks; no native runtime acceptance', 'steps': []}
        commands = [
            ('healthy-defects', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_safe_area.py']),
            ('unit-suite', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests']),
            ('self-tests', [sys.executable, 'master_gate.py', '--self-test']),
            ('catalogue', [sys.executable, 'scripts/gen_rule_docs.py', '--check']),
            ('self-scan', [sys.executable, 'master_gate.py', '.', '--strict', '--format', 'agent']),
            ('changed', [sys.executable, 'master_gate.py', '.', '--changed-only', '--format', 'agent']),
        ]
        if options.target:
            commands.append(('app-control', [sys.executable, 'master_gate.py', str(options.target.resolve()), '--check', 'web.safe_area_margin_padding_doubled', '--format', 'agent']))
        environment = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
        print(f'SAFE_AREA_ARTIFACTS {run}', flush=True)
        for name, command in commands:
            with (run / (name + '.log')).open('w') as log:
                try:
                    code = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=600).returncode
                except subprocess.TimeoutExpired:
                    code = 124
            report['steps'].append({'id': name, 'exit': code, 'log': name + '.log'})
            report['status'] = 'failed' if code else 'running'
            (run / 'result.json').write_text(json.dumps(report, indent=2))
            print(f'SAFE_AREA_GATE {name} exit={code}', flush=True)
            if code:
                print((run / (name + '.log')).read_text()[-5000:], flush=True)
                return code
        report['status'] = 'passed'
        (run / 'result.json').write_text(json.dumps(report, indent=2))
        return 0


if __name__ == '__main__':
    sys.exit(main())
