# Explicit XCFramework CPU inspection

An XCFramework directory or its `SupportedArchitectures` array can claim CPUs
that are absent from the actual library. An architecture exclusion can produce
a successful link while leaving no installable app on the intended simulator.
Inspect the actual archive, then prove build, installation, start, interaction
and screenshots separately.

Run explicitly, on a local directory containing the exported libraries:

```sh
python3 scripts/check_xcframework_architectures.py /path/to/export Engine.xcframework
```

The checker uses Ruttla's ordinary inventory, profile exclusions and 2 MB default
file limit. Missing, excluded, oversized, unsupported or incomplete binaries
remain `UNMEASURED`. It neither executes target code nor calls external tools,
network services or an LLM. It is an explicit companion tool, **not a registered
default rule**; an ordinary `ruttla` scan does not run it or inherit its result.
The frozen text-only rule self-test interchange cannot carry Mach-O bytes;
binary controls currently live in `tests/test_xcframework_architectures.py`.

For an intentional isolated export inspection, select that export as the root
and explicitly allow its measured binary size:

```sh
python3 scripts/check_xcframework_architectures.py /path/to/export Engine.xcframework \
  --max-file-bytes 200000000
```

That explicit root/limit does not alter the project's normal scan settings.
Results contain the selected framework, effective limit, declared and measured
architectures per library. Exit codes: 0 complete match, 1 measured mismatch,
2 incomplete measurement, 3 invalid input/configuration or I/O failure. A
known mismatch remains exit 1 even if another slice is unmeasured. Each such
slice is still listed; exit 1 never claims full coverage.

Supported inputs: thin Mach-O, universal/fat Mach-O (32/64-bit slice tables),
BSD/GNU archives and frameworks with inventoried executables. Archive symbol
tables are skipped; object members are inspected. Fat tables are checked against
their actual bounded payloads. Unknown formats, malformed bounds, overlapping
slices and unsupported CPUs cannot become a pass. CPU coverage does not prove
platform identity, ABI compatibility, signatures, linking, installation or boot.

Validation: first an actual dual-CPU simulator archive with correct isolated
metadata passed; changing only its declared architecture array failed. The
observed single-CPU archive with dual-CPU metadata failed too. Tests additionally
cover missing/excluded/large inputs, unsupported/truncated archives, BSD names,
fat payload contradictions and escaping paths. No native startup heuristic was
added.

Primary references: [Apple XCFramework creation](https://developer.apple.com/documentation/xcode/creating-a-multi-platform-binary-framework-bundle),
[Mach-O headers](https://github.com/apple-oss-distributions/cctools/blob/main/include/mach-o/loader.h),
[fat headers](https://github.com/apple-oss-distributions/cctools/blob/main/include/mach-o/fat.h),
[archive headers](https://github.com/apple-oss-distributions/cctools/blob/main/include/ar.h).
