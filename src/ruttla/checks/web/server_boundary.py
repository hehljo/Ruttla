"""Explicit server-only boundary for HTML module entrypoints; no IP guessing."""
from __future__ import annotations

import posixpath
import re

from ruttla.core import Context, CheckResult, Finding, Severity, Status, SelfTestCase, register, result_for, strip_comments, unmeasured

ENTRY = '<script type="module" src="/src/main.ts"></script>'
EXTENSIONS = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.mts')


@register(
    'web.server_only_reaches_browser', 'Server-only-Modul im Browser-Importpfad',
    platform='web', severity=Severity.ERROR,
    guideline='GUIDELINES.md § Server-only boundary',
    references=['https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules',
                'https://docs.netlify.com/build/edge-functions/api/'],
    rationale='Browsermodule werden an Nutzer ausgeliefert. Explizit mit // @server-only markierte Module und *.server.ts/js-Dateien dürfen von HTML-Moduleinstiegen nicht über Laufzeitimports erreichbar sein. Relative Imports, Re-Exports und literale dynamische Imports werden verfolgt; Typimporte sind ausgenommen. Aliases, Framework-Einstiege und berechnete Imports bleiben ungemessen. Keine automatische Klassifikation von Geschäftslogik und kein vollständiger Copycat-Schutz.',
    self_tests=[
        SelfTestCase(name='gesund: Servercode getrennt', files={'index.html': ENTRY, 'src/main.ts': 'export const ok = true;', 'server/core.ts': '// @server-only\nexport const secret = 1;'}, expect=Status.PASS),
        SelfTestCase(name='gesund: Typimport', files={'index.html': ENTRY, 'src/main.ts': 'import type { Core } from "../server/core";', 'server/core.ts': '// @server-only\nexport interface Core {}'}, expect=Status.PASS),
        SelfTestCase(name='defekt: direkter privater Import', files={'index.html': ENTRY, 'src/main.ts': 'import { core } from "../server/core";', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.FAIL),
        SelfTestCase(name='defekt: transitive Barrel-Exports', files={'index.html': ENTRY, 'src/main.ts': 'import { core } from "./bridge";', 'src/bridge.ts': 'export { core } from "../server/core";', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.FAIL),
        SelfTestCase(name='defekt: dynamischer Literalimport', files={'index.html': ENTRY, 'src/main.ts': 'const core = import("../server/core");', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.FAIL),
        SelfTestCase(name='defekt: server-Suffix', files={'index.html': ENTRY, 'src/main.ts': 'import "./core.server";', 'src/core.server.ts': 'export const core = 1;'}, expect=Status.FAIL),
        SelfTestCase(name='gesund: kommentierter Import', files={'index.html': ENTRY, 'src/main.ts': '// import "../server/core";', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.PASS),
        SelfTestCase(name='gesund: reiner Typ-Reexport', files={'index.html': ENTRY, 'src/main.ts': 'export type { Core } from "../server/core";', 'server/core.ts': '// @server-only\nexport interface Core {}'}, expect=Status.PASS),
        SelfTestCase(name='Alias bleibt ungemessen', files={'index.html': ENTRY, 'src/main.ts': 'import { core } from "@/core";', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.UNMEASURED),
        SelfTestCase(name='berechneter Import bleibt ungemessen', files={'index.html': ENTRY, 'src/main.ts': 'const core = import(path);', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.UNMEASURED),
        SelfTestCase(name='kein HTML-Einstieg bleibt ungemessen', files={'src/main.ts': 'import "../server/core";', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.UNMEASURED),
        SelfTestCase(name='nicht deklarierte Grenze bleibt ungemessen', files={'index.html': ENTRY, 'src/main.ts': 'export const ok = true;'}, expect=Status.UNMEASURED),
        SelfTestCase(name='gesund: Importtext in String', files={'index.html': ENTRY, 'src/main.ts': 'const help = `import "../server/core";`;', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.PASS),
        SelfTestCase(name='defekt: Worker-URL', files={'index.html': ENTRY, 'src/main.ts': 'const worker = new Worker(new URL("../server/core.ts", import.meta.url));', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.FAIL),
        SelfTestCase(name='defekt: Sideeffect vor weiterem Import', files={'index.html': ENTRY, 'src/main.ts': 'import "../server/core";\nimport { ok } from "./public";', 'src/public.ts': 'export const ok = 1;', 'server/core.ts': '// @server-only\nexport const core = 1;'}, expect=Status.FAIL),
    ],
)
def check_server_only_reaches_browser(ctx: Context) -> CheckResult:
    check_id, title = 'web.server_only_reaches_browser', 'Server-only-Modul im Browser-Importpfad'
    files = {sf.rel: sf for sf in ctx.files(*EXTENSIONS)}
    private = {path for path, sf in files.items() if re.search(r'^\s*//\s*@server-only\s*$', sf.text, re.M) or re.search(r'\.server\.(?:[cm]?[jt]sx?)$', path)}
    if not private:
        return unmeasured(check_id, title, 'Keine expliziten server-only-Module deklariert.', 'web')

    def resolve(base: str, specifier: str) -> str | None:
        path = posixpath.normpath(posixpath.join(posixpath.dirname(base), specifier)) if not specifier.startswith('/') else specifier.lstrip('/')
        for candidate in [path, *[path + ext for ext in EXTENSIONS], *[path + '/index' + ext for ext in EXTENSIONS]]:
            if candidate in files:
                return candidate
        return None

    entries = []
    unknown = False
    for html in ctx.files('.html'):
        code = strip_comments(html.text, html.ext)
        for script in re.finditer(r'<script\b[^>]*>', code, re.I):
            if not re.search(r'\btype\s*=\s*[\'"]module[\'"]', script.group(), re.I):
                continue
            src = re.search(r'\bsrc\s*=\s*([\'"])(.*?)\1', script.group())
            if src:
                entry = resolve(html.rel, src.group(2))
                if entry:
                    entries.append(entry)
                else:
                    unknown = True
            else:
                unknown = True
    if not entries:
        return unmeasured(check_id, title, 'Kein auflösbarer HTML-Moduleinstieg. Frameworks/Inline-Module separat prüfen.', 'web')
    findings, seen, queue = [], set(), list(entries)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        sf = files[path]
        if path in private:
            findings.append(Finding(check_id=check_id, severity=Severity.ERROR, file=path, line=1,
                message='Expliziter server-only-Code ist über den HTML-Browserimport erreichbar.',
                fix='Laufzeitimport entfernen; private Verarbeitung hinter eine geprüfte HTTP-Schnittstelle verlagern. Nur öffentliche Verträge teilen.'))
            continue
        code = strip_comments(sf.text, sf.ext)
        specs = []
        literals = [match.span() for match in re.finditer(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", code)]
        def inside_literal(offset: int) -> bool:
            return any(start <= offset < end for start, end in literals)
        for match in re.finditer(r'\b(?:import|export)\s+(?!\()(?:(?P<quote>[\'"])(?P<side>[^\'"\n]+)(?P=quote)|(?P<clause>[\w$\s{},*]+?)\s+from\s+(?P<fromquote>[\'"])(?P<from>[^\'"\n]+)(?P=fromquote))', code):
            if inside_literal(match.start()):
                continue
            clause = (match.group('clause') or '').strip()
            if clause.startswith('type ') or (clause.startswith('{') and all(part.strip().startswith('type ') for part in clause.strip('{} ').split(',') if part.strip())):
                continue
            specs.append(match.group('side') or match.group('from'))
        for match in re.finditer(r'\bimport\s*\(\s*(?:([\'"])([^\'"]+)\1\s*\)|([^)]*)\))', code):
            if inside_literal(match.start()):
                continue
            if match.group(1):
                specs.append(match.group(2))
            else:
                unknown = True
        for match in re.finditer(r'\bnew\s+URL\(\s*([\'"])([^\'"]+)\1\s*,\s*import\.meta\.url\s*\)', code):
            if not inside_literal(match.start()):
                specs.append(match.group(2))
        if re.search(r'\bimport\.meta\.glob\s*\(', code):
            unknown = True
        for spec in specs:
            if spec.startswith('.') or spec.startswith('/'):
                target = resolve(path, spec)
                if target:
                    queue.append(target)
                elif not re.search(r'\.(?:css|svg|png|jpg|woff2)(?:\?|$)', spec):
                    unknown = True
            elif spec.startswith('@/') or spec.startswith('~/'):
                unknown = True
    if unknown and not findings:
        return unmeasured(check_id, title, 'Importgraph nur teilweise auflösbar; Aliases/berechnete Imports/Worker separat prüfen.', 'web')
    return result_for(check_id, title, findings, len(seen), 'erreichbare Browsermodule (keine Bundler-Vollprüfung)', 'web')
