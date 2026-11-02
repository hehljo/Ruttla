"""Cross-file proof writer/runner coverage; target code is never executed."""
from __future__ import annotations

import ast
import json
import re
import shlex
from pathlib import Path

from ruttla.contracts import CONTRACT_FILE
from ruttla.core import CheckResult, Context, Finding, SelfTestCase, Severity, Status, register, result_for, unmeasured
from .contracts import _project_contracts

ID = "quality.contract_proof_without_runner_writer"
TITLE = "Sammellauf erreicht die Nachweiserzeuger"
GUIDE = "GUIDELINES.md § Documentation — Sammellauf und Nachweiserzeuger"


def _strings(node: ast.AST, values: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return values.get(node.id, set())
    if isinstance(node, ast.IfExp):
        return _strings(node.body, values) | _strings(node.orelse, values)
    return set()


def _writers(text: str) -> set[str] | None:
    """Only imported receipt APIs, literal IDs and local constant alternatives.

    named_proof only reads the specification; it is not a receipt writer.
    Unknown Python syntax/IDs never establish a measured writer.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    aliases = set()
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "ruttla.contracts":
            aliases.update(a.asname or a.name for a in node.names if a.name == "write_receipt")
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "ruttla.contracts")
    imported = aliases | {name.split(".")[0] for name in modules}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in imported:
            return None
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in imported:
            return None
        if isinstance(node, ast.arg) and node.arg in imported:
            return None
    found = set()
    unknown = False

    def scope(nodes, inherited):
        nonlocal unknown
        values = dict(inherited)
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope(node.body, values)
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = _strings(node.value, values) if node.value else set()
            if isinstance(node, ast.Call):
                api = isinstance(node.func, ast.Name) and node.func.id in aliases
                if isinstance(node.func, ast.Attribute):
                    api = node.func.attr == "write_receipt" and ast.unparse(node.func.value) in modules
                if api:
                    argument = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "proof_id"), None)
                    ids = _strings(argument, values) if argument is not None else set()
                    found.update(ids)
                    unknown |= not ids
            scope(list(ast.iter_child_nodes(node)), values)
    scope(tree.body, {})
    return found if not unknown else None


def _commands(text: str) -> tuple[list[list[str]], bool]:
    """Bounded shell argv parsing, not a shell evaluator.

    Function definitions, echo strings, comments and heredocs are not commands.
    The common step wrapper is recognized by actual execution of "$@".
    """
    wrappers, arrays, lines = set(), {}, []
    body = None
    control = 0
    unknown = False
    for line in text.replace("\\\n", " ").splitlines():
        match = re.match(r"\s*(?:function\s+)?([\w]+)\s*\(\)\s*\{", line)
        if match:
            body = [match[1], line[match.end():]]
            if "}" in body[1]:
                if re.search(r'(?:^|[;\n])\s*"\$@"(?:\s|[;}]|$)', body[1]):
                    wrappers.add(body[0])
                body = None
            continue
        if body:
            # Braces in ${...} are balanced; function-closing braces stand alone.
            if line.strip() == "}":
                if re.search(r'(?:^|[;\n])\s*"\$@"(?:\s|[;}]|$)', body[1]):
                    wrappers.add(body[0])
                body = None
            else:
                body[1] += "\n" + line
            continue
        stripped = line.strip()
        if re.match(r"(?:if|for|while|case)\b", stripped):
            control += 1
        if re.match(r"(?:fi|done|esac)\b", stripped):
            control = max(0, control - 1)
            continue
        if control:
            unknown |= bool(re.search(r"(?:python[0-9.]*|bash|ruttla|step)\s", stripped))
            continue
        if "<<" in line:
            # Do not infer coverage from heredoc payloads.
            return [], True
        match = re.match(r"\s*(\w+)=\((.*)\)\s*$", line)
        if match:
            try:
                arrays["${" + match[1] + "[@]}"] = shlex.split(match[2], comments=True)
            except ValueError:
                unknown = True
            continue
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|<>")
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            unknown = True
            continue
        # Control-flow and assignments are outside the recognized direct form.
        if not tokens or tokens[0] in {"if", "elif", "for", "while", "case"}:
            continue
        chunks, chunk = [], []
        for token in tokens:
            if token in {";", "&&", "||", "|", "&"}:
                if chunk:
                    chunks.append(chunk)
                chunk = []
            else:
                chunk.append(token)
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            if chunk[0] in wrappers:
                chunk = chunk[2:]  # wrapper name and step label
            expanded = []
            for token in chunk:
                expanded.extend(arrays.get(token, [token]))
            if expanded:
                if not re.match(r"[A-Za-z_]\w*=", expanded[0]):
                    unknown |= any(c in expanded[0] for c in "$`")
                lines.append(expanded)
    return lines, unknown


def _invocation(argv: list[str]) -> tuple[str | None, bool]:
    """Return a directly launched local script, or a real Ruttla invocation."""
    args = list(argv)
    while args:
        exe = Path(args[0]).name
        if exe == "env":
            args = args[1:]
            while args and re.match(r"\w+=", args[0]):
                args.pop(0)
        elif exe == "xvfb-run":
            args = args[1:]
            while args and args[0].startswith("-"):
                opt = args.pop(0)
                if opt in {"-s", "--server-args", "-n", "--server-num"} and args:
                    args.pop(0)
        elif exe == "timeout":
            args = args[2:]
        else:
            break
    if not args:
        return None, False
    exe = Path(args[0]).name
    if exe == "ruttla":
        return None, True
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", exe):
        if args[1:3] == ["-m", "ruttla"]:
            return None, True
        args = args[1:]
        while args and args[0] in {"-u", "-B", "-I"}:
            args.pop(0)
    elif exe in {"bash", "sh"}:
        args = args[1:]
    if args and args[0].endswith((".py", ".sh")) and not any(c in args[0] for c in "$`\\"):
        return args[0].removeprefix("./"), False
    return None, False


def _python_commands(text: str) -> tuple[list[list[str]], bool]:
    """Recognize imported subprocess APIs with literal argv, without eval."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return [], True
    modules, aliases = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "subprocess")
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            aliases.update(a.asname or a.name for a in node.names if a.name in {"run", "call", "check_call", "check_output", "Popen"})
    commands, unknown = [], False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        api = isinstance(node.func, ast.Name) and node.func.id in aliases
        if isinstance(node.func, ast.Attribute):
            api = (isinstance(node.func.value, ast.Name) and node.func.value.id in modules
                   and node.func.attr in {"run", "call", "check_call", "check_output", "Popen"})
        if not api:
            continue
        argv = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "args"), None)
        if not isinstance(argv, (ast.List, ast.Tuple)):
            unknown = True
            continue
        command = []
        for item in argv.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                command.append(item.value)
            elif isinstance(item, ast.Attribute) and ast.unparse(item) == "sys.executable":
                command.append("python3")
            else:
                unknown = True
                break
        else:
            if command:
                commands.append(command)
    return commands, unknown


def _runner_paths(files: dict[str, str]) -> list[tuple[str, set[str], bool]]:
    parsed = {name: (_commands(text) if name.endswith(".sh") else _python_commands(text))
              for name, text in files.items() if name.endswith((".sh", ".py"))}
    runners = []
    for name, (commands, unknown) in parsed.items():
        commands = list(commands)
        # Template's data-only tab-separated argv interface; no shell eval.
        text = files[name]
        if (name.endswith(".sh")
                and re.search(r'^CONFIG=tools/gates\.conf[ \t]*$', text, re.M)
                and re.search(r'^done < "\$CONFIG"[ \t]*$', text, re.M)
                and re.search(r'^[ \t]*step "\$\{fields\[@\]\}"[ \t]*$', text, re.M)):
            unknown = False
            config = files.get("tools/gates.conf")
            if config is None:
                unknown = True
            else:
                for line in config.splitlines():
                    if line.strip() and not line.lstrip().startswith("#"):
                        fields = line.split("\t")
                        if len(fields) < 2 or not all(fields):
                            unknown = True
                        else:
                            commands.append(fields[1:])
        launches = [_invocation(c) for c in commands]
        if not any(ruttla for _, ruttla in launches) or not any(path for path, _ in launches):
            continue
        reached, pending = set(), [path for path, _ in launches if path]
        while pending:
            path = pending.pop()
            if path in reached:
                continue
            if path not in files:
                unknown = True
                continue
            reached.add(path)
            # A test may launch dynamic engine/browser processes unrelated to
            # receipt orchestration. Descend into shell entrypoints and actual
            # Python aggregate runners, not every subprocess inside a test.
            if path in parsed and (path.endswith(".sh") or any(_invocation(c)[1] for c in parsed[path][0])):
                nested, incomplete = parsed[path]
                unknown |= incomplete
                pending.extend(p for p, _ in map(_invocation, nested) if p)
        runners.append((name, reached, unknown))
    return runners


def _fixture(defect=False):
    proof = {"id": "audio_assets", "receipt": ".audio.json", "sources": ["tools/test_audio.py"], "required_cases": ["audio"]}
    script = "tools/test_audio_gate.py" if defect else "tools/test_audio.py"
    return {CONTRACT_FILE: json.dumps({"version": 1, "proofs": [proof]}),
            "tools/test_audio.py": 'from ruttla.contracts import write_receipt\nwrite_receipt(root, "audio_assets", before, cases, 1, 0)\n',
            "tools/test_audio_gate.py": 'print("healthy sabotage check")\n',
            "tools/run_all_gates.sh": f'python3 {script}\nruttla --changed-only --format agent\n'}


@register(
    ID, TITLE, severity=Severity.WARNING, guideline=GUIDE,
    tags=("proof", "runner", "source-only"),
    rationale="A real aggregate runner called only an audio-gate sabotage test, leaving the audio receipt stale. Python is required for cross-file contract, shell argv and Python AST state. Advisory: dynamic orchestration and external writers may be intentional; this is static reachability, not execution proof.",
    references=("https://docs.python.org/3/library/ast.html", "https://docs.python.org/3/library/shlex.html"),
    self_tests=[
        SelfTestCase("gesund: echter Schreiber gestartet", _fixture(), Status.PASS),
        SelfTestCase("defekt: nur Gate-Sabotage gestartet", _fixture(True), Status.FAIL),
        SelfTestCase("ohne Contracts bleibt ungemessen", {"game.py": "pass\n"}, Status.UNMEASURED),
        SelfTestCase("ohne Sammellauf bleibt ungemessen", {k: v for k, v in _fixture().items() if not k.endswith(".sh")}, Status.UNMEASURED),
    ],
)
def check_proof_runner(ctx: Context) -> CheckResult:
    """Check every recognized runner separately; never combine partial runners.

    Only source inventory files within the nearest contract scope are read.
    Shell/TS/PowerShell orchestration outside the documented subset is unknown.
    A reader (named_proof), similar filename, comment or string is no writer.
    """
    projects = list(_project_contracts(ctx))
    scopes = [root for root, _, _, _ in projects]
    findings, unknown, units = [], [], 0
    for root, label, contracts, error in projects:
        proofs = (contracts or {}).get("proofs", [])
        if error:
            unknown.append(label + ": ungültiger Vertrag (siehe Vertragsprüfung)")
            continue
        if not proofs:
            continue
        files = {}
        for sf in ctx.all_files():
            path = Path(sf.path)
            if (path.is_relative_to(root) and sf.ext in {".sh", ".py", ".conf"}
                    and not any(other != root and other.is_relative_to(root) and path.is_relative_to(other) for other in scopes)):
                files[path.relative_to(root).as_posix()] = sf.text
        runners = _runner_paths(files)
        if not runners:
            unknown.append(label + ": kein statisch erkennbarer Sammellauf")
            continue
        writers = {name: _writers(text) for name, text in files.items() if name.endswith(".py")}
        for runner, reached, incomplete in runners:
            for proof in proofs:
                if any(proof["id"] in (writers.get(path) or set()) for path in reached):
                    units += 1
                    continue
                if incomplete or any(writers.get(path) is None for path in reached if path.endswith(".py")):
                    unknown.append(label + " / " + runner + " / " + proof["id"] + ": dynamischer Aufruf/Schreiber")
                    continue
                units += 1
                producers = sorted(name for name, ids in writers.items() if proof["id"] in (ids or set()))
                findings.append(Finding(ID, Severity.WARNING,
                    "Sammellauf startet keinen belegten Nachweiserzeuger: " + proof["id"],
                    evidence=label + " / " + runner + "; Erzeuger: " + (", ".join(producers) or "nicht statisch gefunden"),
                    fix="Den tatsächlichen write_receipt-Erzeuger als eigenen Schritt starten; Gate-Sabotage separat ausführen. Danach vollständigen Sammellauf starten.", guideline=GUIDE))
    if findings:
        result = result_for(ID, TITLE, findings, units, "Runner-Nachweise")
        if unknown:
            result.reason = "; ".join(unknown)
        return result
    if unknown:
        return CheckResult(ID, Status.UNMEASURED, TITLE, reason="; ".join(unknown), units_examined=units, unit_label="Runner-Nachweise")
    if not units:
        return unmeasured(ID, TITLE, "Keine expliziten Nachweise mit erkennbarem Sammellauf.")
    return result_for(ID, TITLE, [], units, "Runner-Nachweise")
