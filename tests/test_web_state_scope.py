"""Healthy UI booleans precede isolated nullable-state counterprobes."""
from __future__ import annotations

import unittest

from _support import cli_json, make_tree
from ruttla.core import Config, Context, Status
from ruttla.checks.web.rules import check_null_state


def inspect(source):
    with make_tree({"src/State.tsx": source}) as root:
        return check_null_state(Context(root, Config()))


class WebStateScopeTests(unittest.TestCase):
    def test_healthy_controls_before_each_isolated_defect(self):
        for name in ("isOpen", "isImportOpen", "isSaving", "isSubmitting", "isChecked"):
            with self.subTest(healthy=name):
                result = inspect(f"const [{name}, setValue] = useState(false);")
                self.assertEqual(result.status, Status.UNMEASURED)
                self.assertFalse(result.findings)
        for union in ("boolean | null", "null | boolean"):
            healthy = f"const [answer, setAnswer] = useState<{union}>(null);"
            self.assertEqual(inspect(healthy).status, Status.PASS)
            for value in ("false", "true"):
                with self.subTest(defect=(union, value)):
                    result = inspect(healthy.replace("(null)", f"({value})"))
                    self.assertEqual(result.status, Status.FAIL)
                    self.assertEqual(len(result.findings), 1)
                    self.assertEqual(result.findings[0].line, 1)

    def test_multiline_and_neighboring_declarations_do_not_cross_bind(self):
        result = inspect("const [isSaving, setSaving] = useState(false);\n"
                         "const [answer, setAnswer] = React.useState<\nboolean | null\n>(false);\n"
                         "const [other, setOther] = useState<boolean | null>(null);")
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].line, 2)
        self.assertIn("'answer'", result.findings[0].message)

    def test_comments_strings_aliases_and_dynamic_initializers_remain_unknown(self):
        sources = [
            "// const [answer, setAnswer] = useState<boolean | null>(false);",
            'const example = "const [answer, setAnswer] = useState<boolean | null>(false);";',
            "const example = `const [answer, setAnswer] = useState<boolean | null>(false);`;",
            "const [answer, setAnswer] = useState<Result>(false);",
            "const [answer, setAnswer] = useState<boolean | null>(() => false);",
            "const [answer, setAnswer] = useState<boolean | null>(false || cached);",
            "const [answer, setAnswer] = useState<boolean | null | string>(false);",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(inspect(source).status, Status.UNMEASURED)

    def test_cli_keeps_info_advisory_and_unknown_exit_contract(self):
        with make_tree({"src/State.tsx": "const [isOpen, setOpen] = useState(false);"}) as root:
            code, report = cli_json(root, "--check", "web.loading_without_null_state")
            self.assertEqual(code, 2)
            self.assertEqual(report["results"][0]["status"], "unmeasured")
        with make_tree({"src/State.tsx": "const [answer, setAnswer] = useState<boolean | null>(false);"}) as root:
            code, report = cli_json(root, "--check", "web.loading_without_null_state")
            self.assertEqual(code, 0)
            self.assertFalse(report["results"][0]["findings"][0]["blocking"])
            code, _ = cli_json(root, "--check", "web.loading_without_null_state", "--strict")
            self.assertEqual(code, 1)
