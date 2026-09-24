# Public guideline rationale

Ruttla's rules were distilled from the maintainer's private engineering
guidelines (e.g. `CLAUDE.md § Grundsatz C`, `CODE_QUALITY_GUIDELINES_WEB.md § 5b`).
Those documents are not public. Each rule still carries its original
`guideline` string for traceability, and this page explains every guideline
family in public terms. `ruttla --explain <check_id>` and
[`RULES.md`](RULES.md) link each rule to its section here.

This page deliberately does **not** list rule IDs per section — that would be
a second, hand-maintained list. The mapping lives in code
(`ruttla.catalog.GUIDELINE_FAMILIES`) and is rendered into `RULES.md`.

---

## Cross-cutting principles

<a id="principle-a-single-source-of-truth"></a>
### Principle A — single source of truth

A value that is derived from another (a brand name in UI text, an asset file
named after the brand, a constant "that must be changed together with X")
is computed from one source, never copied by hand. A comment that says
*"keep in sync with …"* is the warning that the coupling is missing.

<a id="principle-b-lab-flags-are-compile-time-constants"></a>
### Principle B — lab flags are compile-time constants

Experimental ("lab") code is switched by a statically evaluable constant so
bundlers and compilers can remove it from release builds. A flag read through
a function call survives into the shipped artefact.

<a id="principle-c-visible-text-lives-in-a-catalog"></a>
### Principle C — visible text lives in a catalog

Every user-visible string lives in a text catalog, even in a single-language
product. Strings are never concatenated (word order differs between
languages; use placeholders). A half-maintained catalog is worse than none:
orphan keys and untranslated entries look like a source of truth and are not.

<a id="principle-d-hardware-behind-an-interface"></a>
### Principle D — hardware behind an interface

Hardware access (GPIO, I²C, serial, cameras) is isolated in its own module so
the logic can be tested without the device. The test: can the property be
checked without the real environment?

<a id="principle-e-protocols-evolve-safely"></a>
### Principle E — published formats evolve safely

An enum in a serialised or published format needs an "unknown" fallback, so
an old client can ignore a new value instead of crashing. Shared runtime
terms are named after what they mean at runtime, not after the UI that first
showed them — a second client does not have that UI.

<a id="gates-must-not-lie"></a>
### Gates must not lie

A quality gate reports the real status or none at all:

- the exit status of a pipeline is that of its **last** command —
  `gate | tail` always reports `tail`'s success;
- "zero tests found" is red, not green;
- a gate that reads from a git-ignored artefact checks whatever happened to
  be built last, not the current source.

<a id="anchor-on-identifiers-not-display-text"></a>
### Anchor on identifiers, not display text

Logic that finds its position through visible wording (`indexOf("Save")`)
breaks with the next copy edit or translation. Anchor on IDs, keys or
structure.

<a id="one-list-not-two"></a>
### One list, not two

The same list of values maintained in two places drifts. The second list is
almost never the last one; derive it from the first.

<a id="wait-for-state-not-time"></a>
### Wait for state, not time

A fixed sleep measures chance. Wait for the state you need (signal, frame,
event) — otherwise the result depends on machine speed.

<a id="frequency-times-cardinality"></a>
### Frequency × cardinality

Work on a hot path is never "one line": it runs per frame × per entity.
Allocation, I/O and logging in `_process`-style callbacks multiply.

<a id="no-assistant-traces-in-code"></a>
### No assistant traces in code

Source code and commit history carry no AI-assistant signatures or
conversational leftovers. Using an assistant is fine; leaving its trace in
the product is not.

<a id="secrets-never-in-source"></a>
### Secrets never in source

Credentials are recognised by their **form** (prefixes, structure, entropy),
not by variable names, and never live in source or in client bundles.
Placeholders and examples are not secrets.

<a id="documentation-that-can-be-executed"></a>
### Documentation that can be executed

Shell snippets in docs are copied verbatim. An unquoted `<HOST_IP>`
placeholder becomes an I/O redirection in a POSIX shell. Markdown with
trailing whitespace fails `git diff --check`.

---

## Platform guideline families

<a id="apple-platform-documentation"></a>
### Apple platform documentation

Rules whose guideline starts with `Apple:` cite Apple's developer
documentation for the named Info.plist key, entitlement, scheme or file
format (String Catalogs, asset catalogs, App Sandbox,
`LSApplicationCategoryType`, distribution). Several of these requirements
only surface in App Store Connect after upload — the local build stays green.

<a id="apple-build-and-debugging-guidelines"></a>
### Apple build and debugging guidelines

Practical traps from real Xcode/Swift projects: bundle identifiers that
diverge between Info.plist and build settings, `Bundle.module` without an SPM
resource target, force-unwraps and `print` in production code, APIs used
above the deployment target without `#available`, SwiftUI container and
navigation traps, Swift concurrency (`@MainActor` on observable state, UI
updates off the main actor), SwiftData `#Predicate` captures, and fix hints
that must only name APIs that actually exist.

<a id="web-guidelines"></a>
### Web guidelines

- **Endpoints** come from one registry, not literals scattered in code.
- **Layout:** `1fr` means "at least as wide as the content"; equal columns
  need `minmax(0, 1fr)`. Mobile viewports need `dvh`, not `vh`. Touch targets
  should be at least 44×44 px (WCAG 2.5.5, Apple HIG).
- **Accessibility:** every control needs an accessible name. In Germany the
  Barrierefreiheitsstärkungsgesetz (BFSG) applies to many consumer services
  since 28 June 2025.
- **Secrets:** variables with public prefixes (`VITE_`, `NEXT_PUBLIC_`,
  `REACT_APP_`) end up in the shipped bundle.
- **Errors and state:** a fetch without an error branch swallows 403s; an
  empty JavaScript/TypeScript `catch` discards the exception without reporting
  or recovery; a boolean loading flag cannot express "not checked yet"; React
  StrictMode double-mounts expose resources without cleanup; undefined CSS
  custom properties fail silently. Empty catches can be intentional for
  best-effort operations, so Ruttla reports them as advisory findings.
- **Legal:** German sites need an imprint (§ 5 DDG) and a privacy policy
  (GDPR Art. 13) before deployment.

<a id="game-development-guidelines-godot"></a>
### Game development guidelines (Godot)

Values that `_ready()` reads are set **before** `add_child()`; physics queries
before the physics server's first step measure nothing; per-frame warnings are
noise that hides real bugs; balance values live in data, not constants;
nodes communicate via signals or exported references instead of fragile
`get_node("../..")` paths; `any_peer` RPCs must verify the sender; the main
scene configured in `project.godot` must exist; the project root stays tidy;
declarations are typed; visible UI text goes through `tr()`.

<a id="raspberry-pi-field-device-guidelines"></a>
### Raspberry Pi / field device guidelines

The field is hostile: hardware and network I/O needs timeouts; bare
`except:` turns a hardware failure into silence; configuration is validated
before the service starts; raw measurements are append-only (corrections are
stored as offsets next to them); long-running services declare a restart
policy; hardware access is isolated (Principle D).

<a id="unreal-engine-guidelines"></a>
### Unreal Engine guidelines

`FObjectFinder` fails silently unless there is an else branch; modular skeletal
meshes need a leader pose component or they stay in T-pose; a gameplay
method without callers outside tests is not a capability; `UPROPERTY(Config)`
without a reader is a dead balance value; `OnComponentHit` never fires without
`SetNotifyRigidBodyCollision(true)`; writes to replicated state require
`HasAuthority()`.

<a id="media-pipelines"></a>
### Media pipelines

Offline audio/video pipelines: FFmpeg's `alimiter` re-normalises to 0 dB
unless auto-level is disabled; generated TTS audio needs a hard duration
sanity check before it reaches the mix; stream order and language metadata
are verified after muxing; PowerShell `Start-Process -ArgumentList` joins
arguments into one string, so free text with spaces needs explicit quoting.
References: <https://ffmpeg.org/ffmpeg-filters.html#alimiter>,
<https://learn.microsoft.com/powershell/module/microsoft.powershell.management/start-process>.

<a id="python-authentication"></a>
### Python authentication

`hmac.compare_digest` and `secrets.compare_digest` only accept ASCII when
passed `str` values. A Unicode password, including `ß`, raises `TypeError`.
Compare UTF-8 bytes on both sides; do not accidentally replace the constant-time
comparison with regular string equality. The check deliberately flags only
password-like inputs and explicit non-ASCII literals: unrelated ASCII-only
HMAC hex digests are legitimate. The heuristic is advisory because variable
names alone cannot prove the accepted character set.
Reference: <https://docs.python.org/3/library/hmac.html#hmac.compare_digest>.

<a id="long-running-python-services"></a>
### Long-running Python services

APScheduler drops jobs that are more than `misfire_grace_time` late (default
1 s); `httpx` logs full request URLs at INFO, which include Telegram bot
tokens; Yahoo's chart API can return the latest daily bar with `close=None`;
retry loops must not repeat non-idempotent requests (POST/PUT) after a
timeout; exchange-rate lookups must not fall back silently to a hard-coded
number. References:
<https://apscheduler.readthedocs.io/en/3.x/userguide.html#missed-job-executions-and-coalescing>,
<https://www.python-httpx.org/logging/>.
