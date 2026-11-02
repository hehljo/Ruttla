"""Healthy source coverage before individual runner/writer mutations."""
from __future__ import annotations

import json
import unittest

from _support import cli_json, make_tree
from ruttla.checks.universal.proof_runner import ID, _fixture, _writers


class ProofRunnerTests(unittest.TestCase):
    def scan(self, files, *args):
        with make_tree(files) as root:
            return cli_json(root, "--check", ID, *args)

    def test_00_healthy_then_original_defect(self):
        code, report = self.scan(_fixture(), "--strict")
        self.assertEqual(code, 0)
        self.assertEqual(report["results"][0]["status"], "pass")
        code, report = self.scan(_fixture(True), "--strict")
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0]["findings"][0]["severity"], "warning")
        self.assertIn("audio_assets", report["results"][0]["findings"][0]["message"])

    def test_warning_is_advisory_by_default(self):
        code, report = self.scan(_fixture(True))
        self.assertEqual(code, 0)
        self.assertEqual(report["results"][0]["status"], "fail")
        self.assertEqual(report["blocking_findings"], 0)

    def test_absent_subjects_are_unmeasured(self):
        for files in ({"src/game.py": "pass\n"},
                      {k: v for k, v in _fixture().items() if not k.endswith(".sh")},
                      {".ruttla-contracts.json": '{"version": 1}'}):
            with self.subTest(files=list(files)):
                code, report = self.scan(files)
                self.assertEqual(code, 2)
                self.assertEqual(report["results"][0]["status"], "unmeasured")

    def test_verified_step_wrapper_and_array_prefix(self):
        files = _fixture()
        files["tools/run_all_gates.sh"] = '''#!/bin/bash
step() {
  local name="$1"; shift
  "$@" > "logs/$name.log" 2>&1
}
XVFB=(xvfb-run -a -s "-screen 0 1280x1024x24")
step audio "${XVFB[@]}" python3 tools/test_audio.py
step ruttla ruttla --changed-only --format agent
'''
        self.assertEqual(self.scan(files, "--strict")[0], 0)
        files["tools/run_all_gates.sh"] = files["tools/run_all_gates.sh"].replace('  "$@" >', '  echo "$@" >')
        self.assertEqual(self.scan(files, "--strict")[0], 2)

    def test_comments_strings_definitions_and_reader_do_not_write(self):
        for source in ('# write_receipt(root, "audio_assets", b, c, 1, 0)\n',
                       'text = \'write_receipt(root, "audio_assets", b, c, 1, 0)\'\n',
                       'from ruttla.contracts import named_proof\nnamed_proof(root, "audio_assets")\n',
                       'def write_receipt(*args): pass\nwrite_receipt(root, "audio_assets", b, c, 1, 0)\n'):
            files = _fixture()
            files["tools/test_audio.py"] = source
            with self.subTest(source=source):
                self.assertEqual(self.scan(files, "--strict")[0], 1)
        for runner in ('# python3 tools/test_audio.py\n',
                       'echo "python3 tools/test_audio.py"\n',
                       'unused() { python3 tools/test_audio.py; }\n'):
            files = _fixture(True)
            files["tools/run_all_gates.sh"] = runner + files["tools/run_all_gates.sh"]
            with self.subTest(runner=runner):
                self.assertEqual(self.scan(files, "--strict")[0], 1)

    def test_alias_keyword_and_constant_alternatives(self):
        source = '''from ruttla.contracts import write_receipt as receipt
import ruttla.contracts as contracts
ROOT_ID = "other"
def main():
    proof_id = "audio_assets" if args.rendered else "headless"
    receipt(root=root, proof_id=proof_id)
    contracts.write_receipt(root, ROOT_ID, b, c, 1, 0)
'''
        self.assertEqual(_writers(source), {"audio_assets", "headless", "other"})
        files = _fixture()
        files["tools/test_audio.py"] = source
        self.assertEqual(self.scan(files, "--strict")[0], 0)

    def test_dynamic_writer_or_conditional_launch_is_unmeasured(self):
        files = _fixture()
        files["tools/test_audio.py"] = 'from ruttla.contracts import write_receipt\nwrite_receipt(root, args.proof_id, b, c, 1, 0)\n'
        self.assertEqual(self.scan(files, "--strict")[0], 2)
        files = _fixture()
        files["tools/run_all_gates.sh"] = 'if false; then\n python3 tools/test_audio.py\nfi\npython3 tools/test_audio_gate.py\nruttla\n'
        self.assertEqual(self.scan(files, "--strict")[0], 2)

    def test_separate_runners_are_not_merged(self):
        files = _fixture(True)
        files["tools/another.sh"] = 'python3 tools/test_audio.py\nruttla\n'
        code, report = self.scan(files, "--strict")
        self.assertEqual(code, 1)
        self.assertEqual(len(report["results"][0]["findings"]), 1)

    def test_nested_contract_scope_does_not_supply_parent_writer(self):
        files = _fixture(True)
        files.update({"nested/" + name: text for name, text in _fixture().items()})
        code, report = self.scan(files, "--strict")
        self.assertEqual(code, 1)
        self.assertEqual(len(report["results"][0]["findings"]), 1)

    def test_tab_config_interface(self):
        files = _fixture()
        files["tools/run_all_gates.sh"] = '''CONFIG=tools/gates.conf
while IFS= read -r line; do
 step "${fields[@]}"
done < "$CONFIG"
ruttla --changed-only --format agent
'''
        files["tools/gates.conf"] = 'audio\tpython3\ttools/test_audio.py\n'
        self.assertEqual(self.scan(files, "--strict")[0], 0)
        files["tools/gates.conf"] = 'audio\tpython3\ttools/test_audio_gate.py\n'
        self.assertEqual(self.scan(files, "--strict")[0], 1)

    def test_nested_literal_shell_entrypoint(self):
        files = _fixture()
        files["tools/run_all_gates.sh"] = 'bash tools/audio.sh\nruttla\n'
        files["tools/audio.sh"] = 'python3 tools/test_audio.py\n'
        self.assertEqual(self.scan(files, "--strict")[0], 0)
        files["tools/audio.sh"] = 'python3 tools/test_audio_gate.py\n'
        self.assertEqual(self.scan(files, "--strict")[0], 1)

    def test_python_subprocess_runner(self):
        files = _fixture()
        files.pop("tools/run_all_gates.sh")
        files["tools/run_all_gates.py"] = ("import subprocess as sp\nimport sys\n"
            'sp.run([sys.executable, "tools/test_audio.py"])\n'
            'sp.run(["ruttla", "--format", "agent"])\n')
        self.assertEqual(self.scan(files, "--strict")[0], 0)
        files["tools/run_all_gates.py"] = files["tools/run_all_gates.py"].replace("tools/test_audio.py", "tools/test_audio_gate.py")
        self.assertEqual(self.scan(files, "--strict")[0], 1)

    def test_dynamic_command_and_reader_only_runner_are_unmeasured(self):
        files = _fixture()
        files["tools/run_all_gates.sh"] = '$PY tools/test_audio.py\nruttla\n'
        self.assertEqual(self.scan(files, "--strict")[0], 2)
        files["tools/run_all_gates.sh"] = 'echo "tools/test_audio.py"\nruttla\n'
        self.assertEqual(self.scan(files, "--strict")[0], 2)

    def test_imported_api_shadow_is_unknown(self):
        for tail in ('write_receipt = other\n', 'def write_receipt(*args): pass\n'):
            files = _fixture()
            files["tools/test_audio.py"] = ('from ruttla.contracts import write_receipt\n' + tail
                + 'write_receipt(root, "audio_assets", before, cases, 1, 0)\n')
            with self.subTest(tail=tail):
                self.assertEqual(self.scan(files, "--strict")[0], 2)

    def test_dynamic_process_inside_test_does_not_hide_missing_writer(self):
        files = _fixture()
        files["tools/test_audio_gate.py"] = 'import subprocess\nsubprocess.run(command)\n'
        self.assertEqual(self.scan(files, "--strict")[0], 0)
        files["tools/run_all_gates.sh"] = 'python3 tools/test_audio_gate.py\nruttla\n'
        self.assertEqual(self.scan(files, "--strict")[0], 1)

    def test_shell_variable_assignment_is_not_a_dynamic_command(self):
        for defect, expected in ((False, 0), (True, 1)):
            files = _fixture(defect)
            files["tools/run_all_gates.sh"] = 'LOGS="${1:-build/qa/$(date +%s)}"\n' + files["tools/run_all_gates.sh"]
            with self.subTest(defect=defect):
                self.assertEqual(self.scan(files, "--strict")[0], expected)
