"""Runner behavior with synthetic commands; no Godot/project tests executed."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import unittest

from _support import make_tree

TEMPLATE = Path(__file__).parent / "fixtures/sammellauf_template/run_all_gates.sh"


@unittest.skipUnless(shutil.which("bash") and shutil.which("flock"), "Bash/flock required")
class SammellaufTemplateTests(unittest.TestCase):
    def run_case(self, config, *, low_space=False, fail_ruttla=False, fail_df=False, locked=False, repeat=False):
        files = {"tools/run_all_gates.sh": TEMPLATE.read_text(), "tools/gates.conf": config,
                 "bin/ruttla": '#!/bin/sh\nprintf "ruttla\\n" >> "$TRACE"\nexit ' + ("1" if fail_ruttla else "0") + '\n',
                 "bin/ok": '#!/bin/sh\nprintf "ok:%s\\n" "$*" >> "$TRACE"\n',
                 "bin/bad": '#!/bin/sh\nprintf "bad\\n" >> "$TRACE"\nexit 7\n'}
        if fail_df:
            files["bin/df"] = '#!/bin/sh\nexit 5\n'
        with make_tree(files) as tmp:
            root = Path(tmp)
            for path in (root / "bin").iterdir():
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(root / "bin") + os.pathsep + os.environ["PATH"],
                       TRACE=str(root / "trace.txt"), MIN_FREI_GB="999999" if low_space else "0")
            env.pop("LOG_BASE", None)
            held_lock = None
            if locked:
                import fcntl
                lock_path = root / "build/qa/sammellauf.lock"
                lock_path.parent.mkdir(parents=True)
                held_lock = lock_path.open("w")
                fcntl.flock(held_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            proc = subprocess.run(["bash", "tools/run_all_gates.sh"], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=15)
            if held_lock:
                held_lock.close()
            if repeat:
                proc = subprocess.run(["bash", "tools/run_all_gates.sh"], cwd=root, env=env,
                                      capture_output=True, text=True, timeout=15)
            summaries = list(root.glob("build/qa/gates-*/summary.txt"))
            self.assertEqual(len(summaries), 2 if repeat else 1)
            summary = summaries[0].read_text()
            self.assertIn(proc.stdout.splitlines()[-1], summary)
            trace = (root / "trace.txt").read_text().splitlines() if (root / "trace.txt").exists() else []
            logs = {p.name: p.read_text() for p in summaries[0].parent.glob("*.log")}
            return proc.returncode, summary, trace, logs

    def test_00_healthy_then_failed_step_still_runs_ruttla_last(self):
        code, summary, trace, logs = self.run_case('one\tok\targument with spaces\n')
        self.assertEqual(code, 0)
        self.assertIn('GRÜN: alle Schritte', summary)
        self.assertEqual(trace, ['ok:argument with spaces', 'ruttla'])
        self.assertEqual(set(logs), {'disk.log', 'one.log', 'ruttla.log'})
        code, summary, trace, _ = self.run_case('broken\tbad\nnext\tok\n')
        self.assertEqual(code, 1)
        self.assertIn('EXIT=7', summary)
        self.assertIn('ROT: broken', summary)
        self.assertEqual(trace, ['bad', 'ok:', 'ruttla'])

    def test_empty_and_invalid_configs_do_not_run_steps(self):
        for config in ('# comment\n', 'name ok\n', 'x\tok\nx\tok\n', 'ruttla\tok\n', 'x\truttla\n', 'x\tok\t\n'):
            with self.subTest(config=config):
                code, summary, trace, _ = self.run_case(config)
                self.assertEqual(code, 1)
                self.assertIn('ROT:', summary)
                self.assertEqual(trace, [])

    def test_space_and_measurement_failure_are_unmeasured(self):
        for options in ({'low_space': True}, {'fail_df': True}):
            with self.subTest(options=options):
                code, summary, trace, _ = self.run_case('x\tok\n', **options)
                self.assertEqual(code, 2)
                self.assertIn('nicht gemessen', summary)
                self.assertEqual(trace, [])

    def test_ruttla_failure_is_red(self):
        code, summary, trace, _ = self.run_case('x\tok\n', fail_ruttla=True)
        self.assertEqual(code, 1)
        self.assertIn('ROT: ruttla', summary)
        self.assertEqual(trace[-1], 'ruttla')

    def test_arguments_are_not_shell_evaluated(self):
        code, _, trace, _ = self.run_case('x\tok\t$(exit 9)\t$HOME\t*\n')
        self.assertEqual(code, 0)
        self.assertEqual(trace[0], 'ok:$(exit 9) $HOME *')

    def test_lock_and_unique_run_directories(self):
        code, summary, trace, _ = self.run_case('x\tok\n', locked=True)
        self.assertEqual(code, 2)
        self.assertIn('ein Sammellauf läuft bereits', summary)
        self.assertEqual(trace, [])
        code, _, trace, _ = self.run_case('x\tok\n', repeat=True)
        self.assertEqual(code, 0)
        self.assertEqual(trace, ['ok:', 'ruttla', 'ok:', 'ruttla'])
