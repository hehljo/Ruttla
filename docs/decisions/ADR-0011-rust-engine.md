# ADR-0011 — Rust Engine for New Rules, Staged Port of Existing Checks

## Status
Accepted (2026-10-04, maintainer decision). Amends ADR-0002 for the engine;
the Python package stays stdlib-only during the migration.

## Context
- Ruttla reads foreign repositories. Python's `re` backtracks: on 2026-10-04 a
  core regex (`(?:^|\n)\s*…`) made a scan of 10 files with 40 KB of blank
  space run past 900 s (fixed: 1.7 s). 17 such patterns existed. A community
  rule hub would multiply foreign patterns on foreign files.
- Cost grows with checks × files × preprocessing: every check re-walks the
  inventory and re-strips comments. Measured baseline: flutter (14 539 files,
  102 checks) 32.7 s check time; linear extrapolation ×100 ≈ 55 min.
- Python threads cannot run checks in parallel (GIL); checks are independent
  and read-only, so parallelism is a property the engine should provide.

## Decision
1. New rules — official and community — are **declarative data** (format from
   P10-T008) executed by a **Rust engine** (`engine/`, crate `ruttla-engine`).
2. The engine matches with the `regex` crate only (linear time by
   construction). Patterns needing lookaround or backreferences are rejected
   at load; logic that needs them is written as engine code, never via a
   backtracking regex library.
3. Each file is read and preprocessed once; all rules of its platforms run in
   one pass (`RegexSet`), files in parallel.
4. Existing Python checks are ported in batches. A port is accepted only when
   it passes the **exported Python self-tests** unchanged and yields identical
   findings on the reference corpus (differential gate). Then the Python
   check is removed — never two live implementations of one rule.
5. Until the Rust CLI is primary, the Python CLI calls the engine as an
   optional subprocess and merges results. A missing engine makes engine
   rules *not measured*, never silently green.
6. Distribution: binary wheels via maturin (`bindings = "bin"`), so
   `pip install ruttla` stays the one-command install.

## Alternatives
- Stay in Python, add caching and a process pool: fixes speed, not ReDoS.
- Python + RE2 binding: linear regex, but a native runtime dependency without
  the parallelism and single-binary benefits.
- `fancy-regex` in Rust: supports lookaround, but backtracks again.
- Big-bang rewrite: no oracle while porting; rejected.

## Why
Safety first: a linear-time matcher makes the measured failure class
impossible for every future rule, including untrusted ones. Ported checks
keep their evidence because the Python self-tests become the oracle.

## Consequences
- Rust toolchain becomes a development dependency; CI gains a Rust job.
- About 40 regex lines in 20 check modules use lookaround and must be
  re-expressed when ported.
- The engine reads `src/ruttla/platforms.toml` — one detection source for
  both implementations.

## Validation
- Self-test parity per ported check (both directions, from the export).
- Differential corpus gate: Python vs Rust finding fingerprints identical;
  three outcomes (identical / diverged / not measured).
- Load-time rejection test for lookaround/backreference patterns.
- Whitespace-bomb fixture stays under a measured time bound.
