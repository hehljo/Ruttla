# Deployment safety checks

These offline checks record three observed failures from 22–23 October 2026.
They do not run hooks, package scripts, shell commands or a deployment.

## web.capacitor_app_start_path_spa_route

Error, blocking without a profile. A literal `server.appStartPath: "/radar"`
made Capacitor iOS abort before the SPA router: its startup file must exist in
the bundle. Remove the override and choose the first screen in the router, or
supply an actual bundled HTML file. `/index.html` and `landing.html` are healthy
controls. Existence of the named HTML file and native launch are separate tests.

The TOML rule is limited to `capacitor.config.ts`, `.js`, `.mjs` and `.json`,
including generated files in subdirectories. The additive `scope.file_names`
filter uses literal basenames AND the existing extension filter. Without a
matching config there is no measured pass. It has 12 fixtures, with both
exclusions independently challenged by the conformance kit; its three stress
inputs retain an allowed basename in separate directories.

The match covers a direct string literal in a flat server object. Dynamic
values, nested object syntax and full JS/TS evaluation are outside this check.
A file without an extension can be intentional: use a project-specific
exception when that bundle layout is verified. This conventional-path policy
was explicitly requested as a blocker; it is not a bundle filesystem proof.

Sources: [Capacitor configuration](https://capacitorjs.com/docs/config),
[iOS startup implementation](https://github.com/ionic-team/capacitor/blob/main/ios/Capacitor/Capacitor/CAPBridgeViewController.swift).

## repo.git_hook_not_executable

Error, blocking without a profile. Standard hook names directly in `.husky/`
and the configured `core.hooksPath` are checked in the real Git index. Mode
`100644` is a finding; `100755` is healthy. `.husky/_/` is excluded, even if it
is the configured hook directory. Candidates are counted, not arbitrary files.
No indexed hooks means unmeasured. Untracked files do not prove index modes.
Conflicted/nonregular entries and external hook directories remain unmeasured
unless a definite broken entry is also present. No external directory is read.

Use `git update-index --chmod=+x PATH` together with the appropriate working-tree
permission, then inspect the staged mode. Changing only the working-tree mode
cannot repair a tracked 644 index entry. The Python implementation is required
because a file's indexed mode is metadata, not a text pattern. Git fsmonitor
execution is disabled for queries; hooks and scanned code are never invoked.

The `.husky/` policy also flags scripts intentionally invoked through `sh` by a
wrapper, which may work without their own executable bit. This explicit index
policy therefore does not prove actual Git/Husky invocation. Configuration,
`--no-verify`, OS permissions and wrapper behavior need separate runtime checks.

Sources: [Git hooks](https://git-scm.com/docs/githooks),
[index entries](https://git-scm.com/docs/git-ls-files).

## web.netlify_cli_deploy_without_site

Warning, advisory unless strict/profile policy makes it blocking. Direct
`netlify deploy`, `npx netlify deploy` and
`npx [-y|--yes] netlify-cli[@version] deploy` are inspected in shell scripts,
Makefiles/`.mk` and **only the scripts object** of `package.json`. The absence
of `--site VALUE`, `--site=VALUE`, or a nonempty inline `NETLIFY_SITE_ID`
assignment produces a finding. Comments, quoted examples, descriptions and
other JSON data are not commands. Continuations are one logical command;
separate command segments cannot borrow each other's `--site` option.

A linked `.netlify/state.json` or inherited environment may already select the
right project. This is why the rule warns rather than claiming that every
unqualified deploy creates a site. It never contacts Netlify. Values of site
options/environment are not printed in evidence.

The TOML format **does support** negative conditions through `match.exclude`.
Python is used here because selecting a JSON scripts object, tokenizing command
arguments and recognizing extensionless scripts/Makefiles are structural work,
not one text pattern. The parser is bounded: aliases, dynamic commands, complex
heredocs, generated scripts and general shell control/data flow are not a
complete shell execution analysis. Environment from another line is explicitly
outside the same-command-line policy.

Sources: [deploy command](https://cli.netlify.com/commands/deploy/),
[linking a site](https://docs.netlify.com/cli/get-started/#link-and-unlink-sites).

## Git metadata in self-test fixtures

The trusted installed self-test harness recognizes the text fixture
`.ruttla-selftest/git-index.json` with `modes` (path to `100644`/`100755`) and an
optional relative `hooks_path`. It materializes files, initializes an empty
Git repository without templates, hashes fixture contents without filters and
sets index entries. It never executes fixture scripts or Git hooks. Paths and
modes are validated. This is harness data, never an input contract for ordinary
scans. Exported `ruttla-selftests/1` field sets stay unchanged and round trips
exercise the same setup. This declaration is interpreted only by the trusted
Python fixture harness, not by a generic file-only engine fixture runner.
