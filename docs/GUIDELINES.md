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

The concatenation check reads complete quoted literals before testing the
following operator. Long data URLs must finish within the regression budget;
a real text concatenation after such a literal must still be detected. This
is a bounded syntax check, not proof that every runtime string is localized.

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

Distinguish pipelines in a command's arguments from pipelines filtering the
command itself. In `out=$(gate $(list | grep pattern)); status=$?`, the status
belongs to `gate`. In `out=$(gate | head); status=$?`, it belongs to `head`.
The offline check covers these direct substitutions, including wrapped
lines; it does not prove full shell control flow, dynamic commands, or heredocs.

Integration evidence also has separate levels: a configured MCP server is
not necessarily a tool available in the current session. A successful
initialization is not proof of access to the intended account or resource.
Verify actual session tools and a scoped read operation; direct official API
access can provide the latter independently. Offline scans cannot measure
authentication, permissions, resource ownership, or email delivery.

<a id="interaction-before-final-artwork"></a>
### App workflow — core interaction before final asset polish

Start with the product benefit, its primary action and the central navigation
path. Use a short interactive prototype only to resolve a concrete interaction
question. Once that question is answered, continue in small vertical slices in
the actual app, using real data and error states and respecting its safety and
identity contracts. Avoid a prolonged standalone artwork or mockup phase.

Consider design from the beginning: use shared theme tokens, localization and
accessibility and establish a coherent visual direction. Refine final artwork,
logo, typography and animation against working app screens. Early assets can
still be justified when they are needed to test a specific interaction.

A prototype with sample data demonstrates only the interaction it exercises.
It does not prove integration, native focus or input behavior, device
performance or safety. Record app tests separately from prototype tests and
identify which target-platform checks remain unmeasured. For a TV interface,
include remote navigation, focus and return, reading distance and reduced
motion. Decorative motion must not delay input or add an artificial launch
wait; preserve timing that belongs to a verified domain or playback contract.

This is a workflow guideline, not a static source-code rule. An offline scan
cannot reliably establish project chronology, visual quality or device
usability; absence of a finding must not become an automatic PASS. Use a
repeatable platform checklist with the tested revision, scenario, expected
result and observed result instead.

References: <https://developer.apple.com/tutorials/develop-in-swift/build-an-interactive-prototype>,
<https://developer.apple.com/design/human-interface-guidelines/designing-for-tvos/>,
<https://developer.apple.com/design/human-interface-guidelines/launching/>,
<https://developer.apple.com/design/human-interface-guidelines/motion/>.

<a id="sample-payload-contract-scope"></a>
### Sample payloads prove only their contract branch

Inspect the actual files and parsed product/type nodes in a test archive.
An XML sample for one product can demonstrate the shared order structure
without demonstrating a different product's payload. Record which fields and
branches are evidenced; preserve the useful common structure instead of
calling the entire example missing. A valid document is not proof that the
provider accepts the target product, its file references or its production
trigger. Reconcile the target product specification with the interface
description and obtain explicit confirmation where they differ. Keep local
format validation, a provider's non-production import test and an authorised
production order as separate results. This is integration guidance; there is
no generic offline PASS for an unknown provider contract.

<a id="anchor-on-identifiers-not-display-text"></a>
### Anchor on identifiers, not display text

Logic that finds its position through visible wording (`indexOf("Save")`)
breaks with the next copy edit or translation. Anchor on IDs, keys or
structure.

<a id="one-list-not-two"></a>
### One list, not two

The same list of values maintained in two places drifts. The second list is
almost never the last one; derive it from the first.

<a id="existence-is-not-effect"></a>
### Existence is not effect

A setting the user edits, that is loaded into the editor, shown and saved back,
only touches its own editor. It has an effect once a consumer outside the editor
reads it and computes with it. Saved and displayed is not the same as used.

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

<a id="internal-notes-stay-local"></a>
### Internal notes stay local

Session handovers and the private master roadmap describe work in progress,
local paths and open problems. They belong in the working copy, not in what a
push publishes: keep them in `.gitignore`. Once pushed, they remain in the
history even after deletion.

---

## Platform guideline families

<a id="apple-platform-documentation"></a>
### Apple platform documentation

Rules whose guideline starts with `Apple:` cite Apple's developer
documentation for the named Info.plist key, entitlement, scheme or file
format (String Catalogs, asset catalogs, App Sandbox,
`LSApplicationCategoryType`, distribution). Several of these requirements
only surface in App Store Connect after upload — the local build stays green.
SwiftUI focus should land on a visible interactive element; a transparent
1-pixel focus target is an advisory usability finding, not a compile error.
The local scheme test check reads `TestAction` and XCTest target references;
Xcode Cloud workflow actions and destinations are configured separately and
cannot be inferred from the scheme XML.
References: [SwiftUI Focus](https://developer.apple.com/documentation/swiftui/focus),
[Xcode test plans and schemes](https://developer.apple.com/documentation/xcode/organizing-tests-to-improve-feedback),
[Xcode Cloud workflow actions](https://developer.apple.com/documentation/xcode/configuring-your-xcode-cloud-workflow-s-actions).

<a id="app-store-review-metadata"></a>
### App Store review metadata

Rules whose guideline starts with `App Review Guidelines` read the store
texts at their source — fastlane `metadata/<locale>/*.txt` or JSON profiles
whose locale blocks carry a `subtitle`/`reviewNotes` — before anything is
submitted. Apple product names (Mac, iPhone, iCloud, …) in the app name,
subtitle or keywords are rejected under guideline 5.2.5/2.3.7; in the
description a referential use is tolerated, so that is a warning. Review
notes that decline a demo account, or describe a sign-in with credentials
without one, are a warning: App Review only accepts this when the reviewer
can provide the counterpart (e.g. any SMB server), not for proprietary
backends. Whether Apple can reach the backend is not measurable from text.
References: [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/),
[Guidelines for using Apple trademarks](https://www.apple.com/legal/intellectual-property/guidelinesfor3rdparties.html).

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
- **Draft recovery:** React state does not survive reloads or discarded tabs.
  Agree the scope before storing sensitive drafts; save edits, restore before
  editing, show storage failures, and provide explicit deletion and a backup.
  Test unsent input, background/freeze, reload, browser restart and concurrent
  tabs in a real browser. Do not rely on `unload` to save mobile data. The
  bounded `web.textarea_draft_memory_only` advisory covers direct React state
  and visible Web Storage paths; indirect hooks/IndexedDB need browser proof.
  References: [Page Lifecycle](https://developer.chrome.com/docs/web-platform/page-lifecycle-api),
  [IndexedDB](https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API).

<a id="game-development-guidelines-godot"></a>
### Game development guidelines (Godot)

Values that `_ready()` reads are set **before** `add_child()`; physics queries
before the physics server's first step measure nothing; per-frame warnings are
noise that hides real bugs; balance values live in data, not constants;
nodes communicate via signals or exported references instead of fragile
`get_node("../..")` paths; `any_peer` RPCs must verify the sender; the main
scene configured in `project.godot` must exist; the project root stays tidy;
declarations are typed; visible UI text goes through `tr()`.

Explicitly connected Area physics callbacks must defer collider changes using
`set_deferred()` or a deferred geometry helper. The bounded
`godot.collider_write_in_physics_signal` advisory checks typed onready collider
references and direct same-file calls. Scene connections, dynamic flags,
closures, awaits and cross-script reward chains require a real engine project
proof; absence of this source pattern proves no runtime safety.
See [Godot's CollisionShape2D contract](https://github.com/godotengine/godot/blob/master/doc/classes/CollisionShape2D.xml).

Simulation proofs must bind the complete case matrix, clean engine log and
report to current source hashes; generated balance resources must also appear
in the exported PCK. Healthy runs precede individually broken callback,
statistics and export probes. Bot win rates do not measure human enjoyment or
native device performance.

<a id="raspberry-pi-field-device-guidelines"></a>
### Raspberry Pi / field device guidelines

The field is hostile: hardware and network I/O needs timeouts; bare
`except:` turns a hardware failure into silence; configuration is validated
before the service starts; raw measurements are append-only (corrections are
stored as offsets next to them); long-running services declare a restart
policy; hardware access is isolated (Principle D).

<a id="wpf-desktop-guidelines"></a>
### WPF desktop guidelines

Many WPF mistakes only surface on the Windows build or when a view loads,
which is expensive when Linux is the development host and CI is the only
Windows build: `new Thickness(a, b)` does not compile (1 or 4 arguments);
`Style` must not be set as attribute and property element at once;
`Run.Text` binds TwoWay by default and crashes on read-only sources unless a
`Mode` is given; a literal `CommandParameter` always arrives as `string`, so
`RelayCommand<int>` throws; a custom ComboBox template needs
`PART_EditableTextBox` for editable ComboBoxes; UI scaling belongs in font
resources, not in a bound `LayoutTransform`; `async void` is for event
handlers only.

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

<a id="python-regex"></a>
### Python regex

Python's `re` backtracks. Under `re.MULTILINE` every line start is a match
start, and `\s` also matches newlines: `^\s*` at each line of a blank-line run
scans to the end of the run before it fails — quadratic time. A gate that reads
foreign repositories then hangs on one file full of blank lines. Measured on
this repository: 40 KB of blank lines cost 2.0 s per pattern, 80 KB 8.1 s;
`^[ \t]*` cost 0.00 s. After `^`, allow horizontal whitespace only. The check
judges literal patterns with a visible multiline flag (`re.M`, `re.MULTILINE`
or a leading `(?m)`); patterns built at runtime are not measured.
Reference: <https://docs.python.org/3/library/re.html#re.MULTILINE>.

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


<a id="server-only-boundary"></a>
### Server-only boundary

Keep proprietary prompts, ranking rules, provider orchestration and credentials
behind a server endpoint. Browser code can be downloaded and inspected;
minification and removing source maps are not a secrecy boundary. Declare
private JS/TS modules with a standalone `// @server-only` comment or a
`*.server.ts/js` filename. Public API shapes and rendering remain shareable.
The offline gate follows local imports, re-exports, literal dynamic imports
and `new URL(..., import.meta.url)` worker references from HTML module entries.
Pure type imports are excluded. Framework entrypoints, custom aliases and
computed imports require a real bundler gate; unmeasured is not success.

Reject private modules during the actual frontend build too. Serving only
built static assets prevents source directories from becoming public. Server
responses must expose only necessary results and must not log or cache
applicant bodies. Select Edge or regional Functions using their actual CPU,
SDK, timeout and data-processing constraints. An endpoint can still be
queried and its behaviour reproduced; this is not complete copycat protection.
References: <https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules>,
<https://docs.netlify.com/build/edge-functions/api/>,
<https://docs.netlify.com/build/edge-functions/limits/>.

<a id="browser-supabase-remote-dev"></a>
### Browser-Supabase im Remote-Dev-Modus

Wenn ein Vite-Frontend über einen externen Dev-Host erreichbar ist, wird
`VITE_SUPABASE_URL` vom Browser des Besuchers verwendet. `127.0.0.1` und
`localhost` zeigen dort auf dessen Gerät, nicht auf den VPS. Bei gemeinsam
genutzten lokalen Supabase-Ports kann das zu einem fremden Projekt oder zu
einem nicht erreichbaren Auth-Dienst führen. Eine explizite externe
`server.allowedHosts`-Liste zusammen mit einer Loopback-Supabase-URL ist
deshalb ein Konfigurationsfehler. Die Regel liest statische Dev-Env-Dateien
nach Vite-Priorität; Prozessvariablen, Proxys und die tatsächlich laufende
Supabase-Instanz bleiben Laufzeitprüfungen. OAuth-Redirects müssen für die
erreichbare Frontend-URL separat freigeschaltet und im Browser geprüft werden.
Referenzen: <https://vite.dev/guide/env-and-mode.html>,
<https://vite.dev/config/server-options.html#server-allowedhosts>,
<https://supabase.com/docs/guides/auth/redirect-urls>.

<a id="supabase-email-login-smtp"></a>
### Mail-Anmeldung ohne eigenen SMTP

Ohne eigenen SMTP verschickt Supabase Anmelde- und Bestätigungsmails über
den eingebauten Dienst: 2 Mails pro Stunde, und nur an Adressen aus dem
eigenen Supabase-Team; jede andere Adresse scheitert mit „Email address not
authorized". Supabase nennt ihn ausdrücklich „not meant for production use".
Ein Mail-Login-Formular für Fremde ist damit ein Versprechen ohne Zustellung.
Die Regel meldet `signInWithOtp({ email })` im Code, solange
`supabase/config.toml` keinen nichtleeren Host in einem aktiven `[auth.email.smtp]`
trägt. `enabled=true` allein ist kein Versandnachweis. TOML-Kommentare werden
geparst; ungültiges TOML oder falsche Feldtypen bleiben ungemessen. Ein nur im
Dashboard gesetzter SMTP ist offline nicht sichtbar — deshalb Warnung, nicht
harter Fehler. Vor einer Änderung Remote-SMTP lesend prüfen; ein fehlender lokaler
Abschnitt beweist keinen defekten Live-Login. Eigener Versand braucht eine eigene, per DNS bestätigte
Domain; eine geliehene Plattform-Subdomain (`*.netlify.app`) lässt sich bei
Mailanbietern nicht bestätigen. Supabase-Auth-Limits und Providerkontingent sind
getrennt: eigener SMTP hebt ein niedriges Auth-Limit nicht automatisch auf.
DNS/Scope, Auth-Limit, Zustellung, echter Login und Mailbranding separat live
prüfen; Secrets nicht in Konfiguration oder Testfixtures committen.
Referenz: <https://supabase.com/docs/guides/auth/auth-smtp>.


<a id="postgrest-conflict-codes"></a>
### PostgREST application conflict codes

Use a custom application error such as SQLSTATE `PT409` for an expected
optimistic revision mismatch. Do not report a business conflict as PostgreSQL
`40001` (serialization failure): PostgREST may retry a real transaction failure,
and affected PostgREST 14 versions can repeat custom `40001` raises indefinitely.
Check the actual deployed version and the HTTP result of a real stale revision
request. Preserve applied migration history; replace the function in a new
migration. A later function definition can supersede an old error code, so a
text hit in historical SQL alone is not an active defect.

References: <https://supabase.com/docs/guides/troubleshooting/high-cpu-and-infinite-transaction-retries-when-using-custom-error-codes-in-rpc-functions-77326b>,
<https://postgrest.org/en/v14/references/errors.html>.


<a id="chat-viewport-budget"></a>
### Chat workspace and viewport budget

For a conversation workspace, keep session navigation separate from the
scrolling transcript and anchor the composer to the bottom of its own panel.
Measure the empty composer and a real populated conversation at desktop,
narrow and low-height viewports. Count fully visible messages and compare the
usable transcript height before and after a layout change; a clean overflow
audit alone does not establish a useful conversation view. A jump-to-latest
control should not enlarge the composer while the user reads older messages.

With `field-sizing: content`, placeholder text can determine the empty
textarea's height, and `rows` is not a height guarantee. Keep placeholders
short, constrain growth and verify the actual rendered field in browsers with
and without native support. Presentation density should adjust text and gaps
without shrinking actionable touch targets or disabling browser zoom.

For a mobile navigation dialog, keep its close control reachable while its
content scrolls. Use native modal focus containment and verify Escape and
focus return. A scrollability checker must consider both the dialog root and
its descendants: a root with `overflow-y: auto` can be healthy even when no
child scrolls. Prove reachability by scrolling, not by CSS presence alone.
These are runtime and usability checks; no general static PASS is implied.

References: <https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/field-sizing>,
<https://www.w3.org/WAI/WCAG21/Understanding/reflow>,
<https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/>.

<a id="continuous-career-chat"></a>
### Continuous chat, durable derived views and model approval

Profile readiness is a domain result, not the end of a conversation. In a
chat-led product, keep the composer available alongside profile and job
results; do not couple its mount state to a completed questionnaire or a
profile-review step. Source-backed profile fields can be read-only results,
with corrections made through the conversation. Check the actual profile
and result states, not just the initial empty chat. An explicitly labelled
offline questionnaire does not establish reactive AI quality.

When the server commits verified facts before HTTP delivery, a disconnected
browser may miss response callbacks. Derive the displayed profile from the
persisted facts again on restore, and invalidate a search confirmation if
it refers to a different profile. Saving the transcript alone does not prove
that every derived view is current. Live-provider disconnect and correction
behaviour still requires a real permitted provider run; no static PASS is
implied by this guidance.

Enforce an explicit model ceiling in provider dispatch, not only in an
example environment file or documentation shortlist. A configured key and
processing flag do not approve an arbitrary model. A paid evaluation must
name its selected models: expanding a catalogue must not silently expand
the number or cost of requests. Validate the allow/deny policy locally with
known model identifiers before any paid call. Model approval is distinct
from a measured money limit, model quality and provider/account access.

A DOM-only click checker can miss a working file download. Observe the real
browser download event and verify its contents before classifying the
control as unwired. Likewise, wait for the actual application/editor before
layout or design measurement; a clean loading spinner is no app audit.

For flat locale catalogues, a template value containing a central brand does
not make the object keys dynamic. The parity scanner can read plain templates
and simple member substitutions without resolving or executing values.
Interpolation calls, nested templates, spreads and computed keys still remain
unmeasured. Validate a real intact catalogue before independently removing or
adding a key; compiling the application remains a separate gate.

For a private Node service, verify its working directory, actual startup command
and proxy target before restarting only that unit. An environment file read at
startup is not hot reloaded. Keep keys out of status output; report only their
presence, model selection and processing approval. Node-added environment
values need not appear in `/proc/PID/environ`, so their absence there is not proof
of failed loading. Verify the same start path and the running status endpoint.
HTTP 200 and an enabled AI flag prove configuration/readiness, not account/model
access, actual inference, charges, stored answers or consent. Keep the service
running at handover unless stopping it was explicitly requested.

References: <https://developers.openai.com/api/docs/guides/function-calling>,
<https://playwright.dev/docs/downloads>,
<https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Template_literals>,
<https://nodejs.org/api/cli.html#--env-filefile>,
<https://man7.org/linux/man-pages/man5/proc_pid_environ.5.html>.

### Anchored selection controls inside modal navigation

A native HTML select can open an operating-system menu centered on its
selected item and overlap its trigger. Styling the select does not reliably
control that menu's placement. When a product requires below-trigger placement,
use a verified selection widget with an explicit popup anchor. Native popovers
enter the top layer, including inside a modal dialog; reset their default
centering (`inset` and `margin`) before setting trigger-relative coordinates.
A body portal can instead be inert or hidden beneath the modal.

Measure the actual open list against the trigger in multiple browser engines
and low-height layouts. When bringing a trigger into view before opening,
queued container scroll events must not immediately dismiss the new popup.
Follow its anchor on scroll and limit list height to the remaining viewport.
Check Escape closes the list before the parent dialog, preview does not commit,
selection persists, outside dismissal works, and keyboard focus returns.
Preserve touch target sizes while reducing typography and padding. The job-search
Chromium/WebKit regression covers three real controls at four viewport sizes,
with no fabricated applicant content or provider responses. Physical devices
and assistive technology still require their own checks; an offline source
scan cannot prove placement or screen-reader interoperability.

References: <https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-select-only/>,
<https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Global_attributes/popover>.

### Chat readiness, saved vacancies and evidence-backed documents

Do not advance a fixed questionnaire regardless of an answer and then imply a
personal analysis. With an unavailable provider, allow unsent drafts and real
source browsing, but disable submission that would imitate a model reply. Test
blank and whitespace input, old-history restoration and visible readiness using
the actual browser. Greetings and nonspecific answers are not profile facts.
Explore concrete hobbies and projects without equating interest with a credential
or a wish to monetise it. Provider quality remains a real-data acceptance gate.

A saved vacancy needs a durable snapshot of actual publisher metadata. Keep its
identity separate from current query results. Mark it missing only after a
successful complete publisher feed; failure, truncation and an unknown source
mean unknown availability. Show the check time. URL/content deduplication must
preserve publisher IDs as aliases and must not merge solely on a shared title.

Document generation belongs behind authentication and existing RLS. Flush the
actual source state before inference, persist the verified result before HTTP
delivery and use compare-and-swap before applying it. Retry reuse must revalidate
stored outputs against the actual sources. A revision acknowledgement should
update only the revision through a functional state update; replacing an entire
stale snapshot can discard newly applied fields. Literal quote and quantity
checks do not prove semantic truth. Require personal review and distinguish a
technical PDF/DOCX rendering gate from an actual applicant/provider gate. Use an
array-buffer DOCX output in browsers, not a Node-buffer contract.

Builds served to active chat users must retain older hashed lazy chunks and
publish the new index only after its assets exist. Stage the complete build,
copy assets, then atomically replace the entry page. Checking only the new page
does not prove that an already open client can still fetch its dependencies.
Measured locally: the previously served entry JS/CSS remained HTTP200 across a
new staged build. Input preservation during arbitrary browser/OS eviction still
needs the separate durable-draft gates.

References: <https://github.com/lever/postings-api>,
<https://docs.greenhouse.io/job-board.html>,
<https://web.arbeitsagentur.de/bildung/bewerbung/anschreiben>,
<https://developers.openai.com/api/docs/guides/structured-outputs>.

When validating a source-bound transcript, reject whitespace-only messages
without trimming or rewriting earlier assistant/source text. A transform can
change a preserved literal quote or make a server equality/CAS check reject its
own saved message. Canonicalise only the newly submitted editor input; validate
existing history without mutation. This is code-path guidance, not a measured
live-provider result.

A successful service restart is not HTTP readiness. A real private proxy returned
502 immediately after restart, then 200 from the unchanged status endpoint once
the application was listening. Wait for a successful read-only readiness probe
before running API/browser gates; do not classify that initial transport failure
as a provider, feed or application-contract failure.

<a id="linux-host-preflight"></a>
## Linux host preflight

For a new VPS, inspect the actual OS, virtualization, disk, memory, package
state and network device permissions. A distribution version is not proof of
a private kernel or Docker support. An existing `/dev/net/tun` is not proof
that a VPN can create its interface. Test the VPN and a real container.

The reproduced tzdata defect is narrow: `/etc/localtime` pointed to
`/usr/share/zoneinfo/Host` while `/etc/timezone` said `Etc/UTC`. Debconf derived
`Host` and failed with code 10 on the absent `tzdata/Zones/Host` template.
Capture link and registered template names explicitly using
`scripts/collect_host_snapshot.py`; `linux.tzdata_host_timezone` reads that
versioned JSON offline. Unavailable fields, unsupported schemas and partial
snapshots remain unmeasured. A registered custom Host template is allowed.
Other timezone aliases, remote freshness and complete package health are
outside this rule's measurement. Never infer provider restrictions from a
generic dpkg exit code.

The reusable [1blu/OpenVZ setup procedure](operations/1blu-vps.md) includes
missing curl, locale fallback, targeted tzdata diagnosis, a reversible link
repair, Tailnet/OpenSSH bootstrap and verification of public firewall closure.
Keep normal OpenSSH over a Tailnet separate from the optional Tailscale SSH
server. Verify the host fingerprint using the user's console before trusting
a keyscan; private client keys require restrictive file permissions. Protect
remote access changes with a timed rollback and cancel it only after a fresh
connection and external probes succeed. Docker-published ports need their own
verification because they can bypass ufw. Snapshot and static gates do not
prove provider permissions, recovery-console access, backup restoration or
the application's production readiness.

References: <https://manpages.debian.org/testing/debconf-doc/debconf-devel.7.en.html>,
<https://tailscale.com/docs/reference/ssh-over-tailscale>,
<https://docs.docker.com/engine/install/ubuntu/>.

### Declared Godot button minima and runtime touch targets

The mobile button check inspects explicit positive scene minima below 80
logical units in a 1080-wide portrait project. This is a bounded static risk
indicator, not a measurement of the resulting hit region. Container growth,
font metrics, stretch and density remain runtime inputs. Do not recommend
96–120 logical units as a universal platform minimum. Measure iOS regions
in points (44×44), Android regions in dp (48×48), and browser regions separately
in CSS pixels. Assign scene files to their nearest project; neighboring and
nested desktop projects must not inherit another project's mobile setting.
Use source-bound runtime receipts and isolated width/height mutations for
actual scaled targets, layout reachability and input routing.

References: [Apple Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons),
[Android touch targets](https://support.google.com/accessibility/android/answer/7101858),
[Godot resolutions](https://docs.godotengine.org/en/stable/tutorials/rendering/multiple_resolutions.html).

Explicit `MIN/MAX_TOUCH_SIZE/WIDTH/HEIGHT` constants express UI geometry, not
gameplay balance. Excluding them from balance advisories does not prove their
actual runtime hit regions. Health and touch damage constants remain covered.
