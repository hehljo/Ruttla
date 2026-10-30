"""docs/AGENT_SETUP.md: jeder genannte Befehl und Schalter existiert in der echten CLI.

Der Prompt wird in fremde Projekte kopiert. Ein umbenannter Schalter fiele dort
erst auf, wenn ein Agent ihn aufruft — hier wird er rot, bevor der Prompt veraltet.
Geprüft über `--help` des jeweiligen (Unter-)Befehls, nicht über eine Liste.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
import re
import shlex
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from ruttla import cli  # noqa: E402

DOC = REPO / "docs" / "AGENT_SETUP.md"
# Unterbefehl → hat selbst Unterbefehle (hub search, stats enable, rule test).
GROUPS = {"update": False, "hub": True, "stats": True, "rule": True, "badge": True}
# `ruttla` als Befehl: nicht Teil eines Pfads/Namens (.ruttla/, ruttla-rule/0, /Ruttla/).
COMMAND = re.compile(r"(?<![\w/.-])ruttla(?=[ \t])([^\n`;|)&]*)")


def commands(text: str) -> list[list[str]]:
    found = []
    for match in COMMAND.finditer(text):
        tokens = []
        for token in shlex.split(match.group(1), posix=True):
            if token.startswith("#"):
                break  # Kommentar in einem Codeblock
            tokens.append(token)
        found.append(tokens)
    return found


def _help(path: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main([*path, "--help"])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return code, out.getvalue()


def problems(tokens: list[str]) -> list[str]:
    """Leere Liste = Befehl und alle Schalter gibt es so in der CLI."""
    path: list[str] = []
    if tokens and tokens[0] in GROUPS:
        path.append(tokens[0])
        if GROUPS[tokens[0]] and len(tokens) > 1 and not tokens[1].startswith("-"):
            path.append(tokens[1])
    code, text = _help(path)
    if code != 0:
        return [f"`ruttla {' '.join(path)}` gibt es nicht (--help Exit {code})"]
    errors = []
    for i, token in enumerate(tokens):
        if not token.startswith("--"):
            continue
        option = token.split("=", 1)[0]
        if not re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", text):
            errors.append(f"{option} fehlt in `ruttla {' '.join(path)} --help`")
            continue
        choices = re.search(rf"{re.escape(option)} \{{([^}}]*)\}}", text)
        value = token.split("=", 1)[1] if "=" in token else (
            tokens[i + 1] if i + 1 < len(tokens) else None)
        if choices and value is not None and value not in choices.group(1).split(","):
            errors.append(f"{option} {value}: erlaubt sind nur {{{choices.group(1)}}}")
    return errors


class AgentSetupDocTests(unittest.TestCase):
    def setUp(self) -> None:
        self.found = commands(DOC.read_text(encoding="utf-8"))

    def test_every_command_and_option_exists(self) -> None:
        # Null gefundene Befehle wären trivial grün — der Prompt nennt mindestens die Kernabläufe.
        self.assertGreaterEqual(len(self.found), 15, self.found)
        failures = {" ".join(t): p for t in self.found if (p := problems(t))}
        self.assertEqual(failures, {})

    def test_core_workflow_is_named(self) -> None:
        joined = {" ".join(t) for t in self.found}
        for needed in (". --format agent", "--self-test --engine required",
                       "rule test .ruttla/packages/NAME", "hub submit NAME --yes",
                       "stats enable", ". --changed-only --format agent"):
            self.assertIn(needed, joined)

    def test_consent_rules_stay_in_the_prompt(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        prompt = text.split("## Prompt", 1)[1].split("## Project snippet", 1)[0]
        block = prompt.split("Never without the user's explicit consent", 1)
        self.assertEqual(len(block), 2, "Zustimmungsabschnitt fehlt im Prompt")
        for command in ("ruttla hub submit NAME --yes", "ruttla stats enable"):
            self.assertIn(command, block[1])

    def test_checker_rejects_stale_commands(self) -> None:
        """Gegenprobe: der Prüfer muss veraltete Befehle wirklich ablehnen."""
        for stale in ([".", "--formatt", "agent"], [".", "--format", "yaml"],
                      ["hub", "publish", "NAME"], ["stats", "turn-on"],
                      ["rule", "test", "x", "--strict"], ["update", "--channel", "beta"]):
            with self.subTest(stale=stale):
                self.assertTrue(problems(stale), stale)
        self.assertEqual(problems([".", "--format", "agent"]), [])


if __name__ == "__main__":
    unittest.main()
