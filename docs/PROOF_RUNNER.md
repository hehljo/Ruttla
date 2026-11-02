<!-- ruttla:rule-docs -->
# Aggregate runner proof writers

`quality.contract_proof_without_runner_writer` is an additive Python advisory
(warning, not safe-by-default). A real aggregate audio step ran only the gate's
sabotage test. That test exited successfully without writing the declared audio
receipt. The separate audio test was the actual `write_receipt` producer.

The check relates explicit contract proof IDs to Python AST writer calls and
statically parsed shell command arguments. This state spans a manifest, runner,
optional argv configuration and producer files; a per-file pattern is inadequate.
It never imports or executes target code. Python AST and shlex are the standard
library interfaces used for parsing; see their references in the rule catalogue.

Supported scope:

- Direct Bash/sh commands and step wrappers whose body actually executes `"$@"`;
  literal local shell entrypoints, Python interpreters, env, timeout and xvfb-run.
- Python runners using imported subprocess APIs and literal argv lists/tuples.
- The template's `CONFIG=tools/gates.conf` data-only tab-separated argv interface.
- Imported `ruttla.contracts.write_receipt`, aliases, keyword proof_id arguments,
  literal constants and conditional literal ID alternatives. `named_proof` alone
  reads a contract and does **not** establish a writer.
- Each recognizable aggregate runner separately must reach the producers of all
  declared proofs. Partial runners cannot borrow coverage from one another.
  Nested contract scopes cannot supply writers to their parent projects.

No contracts, no proofs or no recognized aggregate runner means UNMEASURED,
not PASS. Unresolved launched scripts, dynamic IDs, conditionally launched
commands and unsupported shell forms remain UNMEASURED. Missing producer calls
in a fully recognized runner produce warnings. Unknown diagnostics survive
alongside any independently measured findings. Findings are project-wide so
changed-only scans retain cross-file violations.

False-positive boundary: deliberately partial aggregate runners, external
writers and custom orchestration may be intentional. Review the advisory;
use `--strict --check quality.contract_proof_without_runner_writer` when an
explicit complete-runner contract should block (defect exit 1, healthy 0,
absent/unsupported subject 2). Default warning findings do not block (exit 0);
that is **not** a PASS. Source reachability is no proof that a writer executes,
uses the correct platform arguments or creates a fresh complete receipt.
`quality.contract_runtime_evidence` remains responsible for receipt validation.

Runner edits may invalidate every receipt whose source patterns select that
runner. Run the complete project workflow after such edits. The scanner itself
never starts that workflow, and cannot establish device or human acceptance.

## Reproduce the verification block

`scripts/verify_proof_runner.py` builds the engine offline, runs the rule and
runner controls, compares a real project with its historical runner in a source
copy, inventories other local manifests, then executes the repository gates.
It records each process exit, separate logs and a summary under the local QA
output directory. It never starts the referenced project's aggregate workflow.

```bash
python3 scripts/verify_proof_runner.py \
  --reference /path/to/project --historical-ref REF \
  --template /path/to/template/run_all_gates.sh \
  --temp-root /path/to/allowed/scratch
```

The scratch parent must lie outside this checkout: rule-kit controls explicitly
exercise external packages. A synthetic invalid local gitdir inside the fresh
scratch folder blocks ancestor discovery, even if that allowed scratch parent
itself belongs to another repository. Child fixture repositories remain isolated.
This avoids accidentally measuring the enclosing checkout in non-Git controls.
The engine self-test requires `--rules src/ruttla/rules`; omitting it is a CLI
input error (exit 3), not a failed rule. Prerequisite or real-reference mismatches
stop the workflow before the expensive whole-suite run. `--final-only` repeats
only catalogue, full/changed source scans and diff checks after documentation
updates; it is not a substitute for the full block after code changes.

After a narrow parser correction, `--targeted-only` runs the rule/template tests,
real current/historical controls, foreign scans and source gates without
repeating the whole unit/engine/self-test suites. Keep the earlier full-suite
result separate and name the final targeted scope explicitly. Multiline shell
line boundaries use horizontal whitespace rather than newline-consuming `\s*`.
