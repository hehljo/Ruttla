"""Real index modes and command-context controls precede isolated defects."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from _support import cli, ensure_checks_loaded, make_tree, require_engine

ensure_checks_loaded()
from ruttla.checks.universal.git_hooks import HOOK_NAMES, _probe, check_git_hooks
from ruttla.checks.web.netlify_deploy import check_netlify_deploy
from ruttla.core import Config, Context, Severity, Status
from ruttla.registry import REGISTRY
from ruttla.selftest import _materialise, run_case


class GitHookModes(unittest.TestCase):
    def git(self, root, *args, input=None):
        return subprocess.run(["git", "-C", root, *args], input=input, text=True,
                              capture_output=True, check=True).stdout.strip()

    def test_healthy_index_precedes_isolated_mode_defect(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(_materialise(root, _probe("100755")))
            run = lambda: check_git_hooks(Context(root, Config()))
            healthy = run()
            self.assertEqual((healthy.status, healthy.units_examined), (Status.PASS, 1))
            # Working-tree mode alone must not replace the Git index contract.
            os.chmod(Path(root, ".husky/pre-commit"), 0o644)
            self.assertEqual(run().status, Status.PASS)
            self.git(root, "update-index", "--chmod=-x", ".husky/pre-commit")
            os.chmod(Path(root, ".husky/pre-commit"), 0o755)
            broken = run()
            self.assertEqual((broken.status, broken.units_examined, len(broken.findings)),
                             (Status.FAIL, 1, 1))
            self.assertIn("100644", broken.findings[0].evidence)

    def test_custom_relative_and_absolute_hook_directory_with_spaces(self):
        for absolute in (False, True):
            with self.subTest(absolute=absolute), tempfile.TemporaryDirectory() as root:
                _materialise(root, _probe("100755", "my hooks/commit-msg", "my hooks"))
                if absolute:
                    self.git(root, "config", "core.hooksPath", str(Path(root, "my hooks")))
                self.assertEqual(check_git_hooks(Context(root, Config())).status, Status.PASS)
                self.git(root, "update-index", "--chmod=-x", "my hooks/commit-msg")
                self.assertEqual(check_git_hooks(Context(root, Config())).status, Status.FAIL)

    def test_every_documented_hook_name_is_a_candidate(self):
        with tempfile.TemporaryDirectory() as root:
            files = {}
            for name in HOOK_NAMES:
                files[f".husky/{name}"] = "exit 0\n"
            files[".ruttla-selftest/git-index.json"] = json.dumps({"modes": {
                name: "100755" for name in files}})
            _materialise(root, files)
            result = check_git_hooks(Context(root, Config()))
            self.assertEqual((result.status, result.units_examined), (Status.PASS, len(HOOK_NAMES)))
            for name in HOOK_NAMES:
                with self.subTest(name=name):
                    self.git(root, "update-index", "--chmod=-x", f".husky/{name}")
                    result = check_git_hooks(Context(root, Config()))
                    self.assertEqual(len(result.findings), 1)
                    self.git(root, "update-index", "--chmod=+x", f".husky/{name}")

    def test_no_index_untracked_and_helper_files_are_not_passes(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(check_git_hooks(Context(root, Config())).status, Status.UNMEASURED)
            self.git(root, "init", "--quiet", "--template=")
            result = check_git_hooks(Context(root, Config()))
            self.assertEqual((result.status, result.units_examined), (Status.UNMEASURED, 0))
            _materialise(root, {".husky/pre-commit": "exit 0\n"})
            self.assertEqual(check_git_hooks(Context(root, Config())).status, Status.UNMEASURED)
        for path in (".husky/_/pre-commit", ".husky/pre-commit.sample", ".husky/README.md"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as root:
                _materialise(root, _probe("100644", path, ".husky/_"))
                self.assertEqual(check_git_hooks(Context(root, Config())).status, Status.UNMEASURED)

    def test_external_hook_directory_stays_unknown(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as external:
            _materialise(root, _probe("100755"))
            self.git(root, "config", "core.hooksPath", external)
            result = check_git_hooks(Context(root, Config()))
            self.assertEqual((result.status, result.units_examined), (Status.UNMEASURED, 1))
            self.git(root, "update-index", "--chmod=-x", ".husky/pre-commit")
            self.assertEqual(check_git_hooks(Context(root, Config())).status, Status.FAIL)

    def test_missing_git_is_unknown(self):
        with patch("ruttla.checks.universal.git_hooks.subprocess.run", side_effect=OSError):
            self.assertEqual(check_git_hooks(Context("/tmp", Config())).status, Status.UNMEASURED)

    def test_nonregular_and_conflicted_hook_modes_are_unknown(self):
        for mode in ("symlink", "conflict"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                _materialise(root, _probe("100755"))
                oid = self.git(root, "ls-files", "--stage").split()[1]
                if mode == "symlink":
                    self.git(root, "update-index", "--add", "--cacheinfo", "120000", oid, ".husky/pre-commit")
                else:
                    self.git(root, "update-index", "--force-remove", ".husky/pre-commit")
                    self.git(root, "update-index", "--index-info", input=f"100755 {oid} 1\t.husky/pre-commit\n100644 {oid} 2\t.husky/pre-commit\n")
                result = check_git_hooks(Context(root, Config()))
                self.assertEqual((result.status, result.units_examined), (Status.UNMEASURED, 0))

    def test_target_fsmonitor_is_disabled(self):
        with tempfile.TemporaryDirectory() as root:
            _materialise(root, _probe("100755"))
            self.git(root, "config", "core.fsmonitor", "touch should-not-exist")
            self.assertEqual(check_git_hooks(Context(root, Config())).status, Status.PASS)
            self.assertFalse(Path(root, "should-not-exist").exists())

    def test_fixture_materialisation_never_runs_hook(self):
        with tempfile.TemporaryDirectory() as root:
            files = _probe("100755")
            files[".husky/pre-commit"] = "#!/bin/sh\ntouch should-not-exist\nexit 1\n"
            _materialise(root, files)
            self.assertEqual(check_git_hooks(Context(root, Config())).status, Status.PASS)
            self.assertFalse(Path(root, "should-not-exist").exists())

    def test_fixture_rejects_path_escape_and_unexpected_mode(self):
        for declaration in ({"../outside": "100755"}, {"hook": "120000"}):
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as root:
                files = {"hook": "exit 0", ".ruttla-selftest/git-index.json": json.dumps({"modes": declaration})}
                self.assertFalse(_materialise(root, files))

    def test_registered_git_probes_work_with_normal_selftest_runner(self):
        check = REGISTRY["repo.git_hook_not_executable"]
        for case in check.self_tests:
            with self.subTest(case=case.name):
                self.assertIsNone(run_case(check, case))


class NetlifyCommands(unittest.TestCase):
    def scan(self, files):
        with make_tree(files) as root:
            return check_netlify_deploy(Context(root, Config()))

    def test_healthy_commands_precede_each_isolated_target_removal(self):
        for prefix in ("netlify", "npx netlify", "npx netlify-cli", "npx -y netlify-cli@23.1.2", "npx --yes netlify-cli@latest"):
            for path, template in (
                ("deploy.sh", "{command}\n"),
                ("Makefile", "ship:\n\t@{command}\n"),
                ("ops.mk", "ship:\n\t{command}\n"),
                ("package.json", None),
            ):
                def files(command):
                    return {path: template.format(command=command) if template else json.dumps({"scripts": {"ship": command}})}
                with self.subTest(prefix=prefix, path=path):
                    for suffix in (" --site sample", " --site=sample"):
                        healthy = self.scan(files(prefix + " deploy" + suffix))
                        self.assertEqual((healthy.status, healthy.units_examined), (Status.PASS, 1))
                    broken = self.scan(files(prefix + " deploy --dir dist"))
                    self.assertEqual((broken.status, broken.units_examined, len(broken.findings)), (Status.FAIL, 1, 1))
                    self.assertEqual(broken.findings[0].severity, Severity.WARNING)

    def test_inline_environment_precedes_removal(self):
        for command in ("NETLIFY_SITE_ID=sample netlify deploy", "env NETLIFY_SITE_ID=sample netlify deploy", "export NETLIFY_SITE_ID=sample; netlify deploy"):
            self.assertEqual(self.scan({"deploy.sh": command}).status, Status.PASS)
        for command in ("NETLIFY_SITE_ID= netlify deploy", "export NETLIFY_SITE_ID=sample\nnetlify deploy", 'echo NETLIFY_SITE_ID=sample; netlify deploy', "netlify deploy # NETLIFY_SITE_ID=sample"):
            self.assertEqual(self.scan({"deploy.sh": command}).status, Status.FAIL)

    def test_non_command_contexts_do_not_create_candidates(self):
        files = {
            "package.json": json.dumps({"description": "netlify deploy", "scripts": {"help": 'echo "netlify deploy"'}, "config": {"deploy": "netlify deploy"}}),
            "README.md": "netlify deploy\n",
            "helper.js": 'const text = "netlify deploy";',
            "deploy.sh": '# netlify deploy\necho "netlify deploy"\ncat <<EOF\nnetlify deploy\nEOF\n',
            "Makefile": "# netlify deploy\nship:\n\t@echo 'netlify deploy'\n",
        }
        result = self.scan(files)
        self.assertEqual((result.status, result.units_examined), (Status.UNMEASURED, 0))

    def test_misleading_options_and_other_commands_do_not_hide_deploy(self):
        for command in ("netlify deploy --site-name new", 'netlify deploy --message "--site sample"', "netlify deploy --site=", "netlify deploy --site", "echo --site sample; netlify deploy", "netlify deploy # --site sample"):
            with self.subTest(command=command):
                self.assertEqual(self.scan({"deploy.sh": command}).status, Status.FAIL)

    def test_line_boundaries_and_counting(self):
        for separator in ("\n", "\v", "\f", "\x85", "\u2028", "\u2029"):
            result = self.scan({"deploy.sh": "netlify deploy" + separator + "netlify deploy --site sample"})
            self.assertEqual((result.units_examined, len(result.findings)), (2, 1))
        result = self.scan({"deploy.sh": "netlify\ndeploy\n"})
        self.assertEqual(result.status, Status.UNMEASURED)
        result = self.scan({"deploy.sh": "netlify deploy; netlify deploy\n"})
        self.assertEqual((result.units_examined, len(result.findings)), (2, 2))
        self.assertEqual(self.scan({"deploy.sh": "netlify deploy \\\n --site sample\n"}).status, Status.PASS)

    def test_extensionless_shell_script_is_examined(self):
        self.assertEqual(self.scan({"ship": "#!/usr/bin/env bash\nnetlify deploy --site sample\n"}).status, Status.PASS)
        self.assertEqual(self.scan({"ship": "#!/usr/bin/env bash\nnetlify deploy\n"}).status, Status.FAIL)

    def test_quoted_or_commented_heredoc_marker_does_not_hide_next_command(self):
        for prefix in ("echo '<<EOF'", '# <<EOF', 'echo "<<EOF"'):
            with self.subTest(prefix=prefix):
                result = self.scan({"ship.sh": prefix + "\nnetlify deploy\nEOF\n"})
                self.assertEqual((result.status, result.units_examined), (Status.FAIL, 1))

    def test_package_location_handles_compact_nested_and_duplicate_keys(self):
        text = '{"config":{"scripts":{"fake":"netlify deploy"}},"scripts": {\n"ship": "netlify deploy", "help": "echo hi"}}'
        result = self.scan({"package.json": text})
        self.assertEqual((len(result.findings), result.findings[0].line), (1, 2))
        self.assertEqual(self.scan({"package.json": '{"scripts":{"ship":"netlify deploy"},"scripts":{"ship":"netlify deploy --site sample"}}'}).status, Status.PASS)

    def test_local_link_does_not_turn_warning_into_verified_target(self):
        result = self.scan({"deploy.sh": "netlify deploy\n", ".netlify/state.json": '{"siteId":"sample"}'})
        self.assertEqual((result.status, result.findings[0].severity), (Status.FAIL, Severity.WARNING))

    def test_invalid_input_does_not_become_a_pass(self):
        self.assertEqual(self.scan({"package.json": '{"scripts":'}).status, Status.UNMEASURED)
        self.assertEqual(self.scan({"deploy.sh": 'netlify deploy --site "unterminated'}).status, Status.UNMEASURED)
        self.assertEqual(self.scan({"package.json": '{', "deploy.sh": "netlify deploy"}).status, Status.FAIL)

    def test_warning_is_advisory_unless_strict(self):
        with make_tree({"package.json": '{"scripts":{"ship":"netlify deploy"}}'}) as root:
            normal = cli(root, "--check", "web.netlify_cli_deploy_without_site", "--format", "json")
            strict = cli(root, "--check", "web.netlify_cli_deploy_without_site", "--strict")
            self.assertEqual(normal.returncode, 0, normal.stdout + normal.stderr)
            self.assertEqual(strict.returncode, 1, strict.stdout + strict.stderr)


class CapacitorStartPath(unittest.TestCase):
    def test_named_scope_rulekit_budget_measures_all_three_inputs(self):
        require_engine(self)
        from _support import REPO
        proc = cli("rule", "test", str(REPO / "src/ruttla/rules/web/web.capacitor_app_start_path_spa_route.toml"), "--format", "json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_named_scope_counts_only_actual_configs_and_blocks_without_profile(self):
        require_engine(self)
        check = "web.capacitor_app_start_path_spa_route"
        shape = 'export default {server: {appStartPath: "/radar"}};'
        with make_tree({"src/router.ts": shape}) as root:
            proc = cli(root, "--check", check, "--format", "json")
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        with make_tree({"capacitor.config.ts": shape.replace("/radar", "/index.html")}) as root:
            self.assertEqual(cli(root, "--check", check).returncode, 0)
            Path(root, "capacitor.config.ts").write_text(shape)
            proc = cli(root, "--check", check, "--format", "json")
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)["results"][0]
            self.assertEqual((result["units_examined"], len(result["findings"])), (1, 1))
