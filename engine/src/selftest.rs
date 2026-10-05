//! Fixtures einer Regel ausführen — dieselbe Semantik wie `ruttla --self-test`
//! (`selftest.run_case`): Dateien in ein leeres Verzeichnis, Regel laufen
//! lassen, Ausgang und optional einen Text in Meldung + Evidenz erwarten.

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};

use serde::Serialize;

use crate::detect::Manifest;
use crate::inventory::InventoryConfig;
use crate::rules::{RawFixture, Rule};
use crate::runner::{scan, View};

#[derive(Debug, Serialize)]
pub struct CaseOutcome {
    pub check_id: String,
    pub name: String,
    pub ok: bool,
    pub expected: String,
    pub got: String,
    pub detail: Option<String>,
}

static COUNTER: AtomicUsize = AtomicUsize::new(0);

/// Eigenes, neu angelegtes Verzeichnis im Temp-Ordner. `create_dir` (nicht
/// `_all`) schlägt fehl, wenn der Name schon existiert — ein fremd
/// vorbereitetes Verzeichnis oder ein Symlink unter demselben Namen wird nie
/// benutzt oder gelöscht, sondern übersprungen. Unix: nur für uns (0700).
fn workdir() -> std::io::Result<PathBuf> {
    let base = std::env::temp_dir();
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    for _ in 0..64 {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = base.join(format!("ruttla-engine-selftest-{}-{nanos:08x}-{n}", std::process::id()));
        let mut builder = std::fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        match builder.create(&dir) {
            Ok(()) => return Ok(dir),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e),
        }
    }
    Err(std::io::Error::new(std::io::ErrorKind::AlreadyExists, "kein freier Arbeitsordner"))
}

pub fn run_fixture(manifest: &Manifest, rule: &Rule, fx: &RawFixture) -> CaseOutcome {
    let mut outcome = CaseOutcome {
        check_id: rule.id.clone(),
        name: fx.name.clone(),
        ok: false,
        expected: fx.expect.clone(),
        got: "error".into(),
        detail: None,
    };
    let dir = match workdir() {
        Ok(d) => d,
        Err(e) => {
            outcome.detail = Some(format!("Arbeitsverzeichnis: {e}"));
            return outcome;
        }
    };
    let result = (|| -> Result<_, String> {
        for (rel, content) in &fx.files {
            let dest = dir.join(rel);
            if let Some(parent) = dest.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            std::fs::write(&dest, content).map_err(|e| e.to_string())?;
        }
        // Wie `ruttla --self-test`: die Probe sieht alle Dateien.
        let view = View::Unscoped;
        let dir_real = std::fs::canonicalize(&dir).map_err(|e| e.to_string())?;
        scan(manifest, &dir_real, &InventoryConfig::default(), std::slice::from_ref(rule), view, 1)
            .map_err(|e| e.message)
    })();
    let _ = std::fs::remove_dir_all(&dir);
    match result {
        Err(e) => outcome.detail = Some(e),
        Ok(mut results) => {
            let res = results.remove(0);
            outcome.got = res.status.clone();
            let mut ok = res.status == fx.expect;
            if ok {
                if let Some(needle) = &fx.expect_finding_contains {
                    let blob = res.findings.iter().map(|f| format!("{} {}", f.message, f.evidence)).collect::<Vec<_>>().join(" ");
                    ok = blob.contains(needle.as_str());
                    if !ok {
                        outcome.detail = Some(format!("kein Befund enthält {needle:?}"));
                    }
                }
                if let Some(n) = fx.expect_findings {
                    if ok && res.findings.len() != n {
                        ok = false;
                        outcome.detail = Some(format!("{} Befunde, erwartet {n}", res.findings.len()));
                    }
                }
            } else if let Some(r) = res.reason {
                outcome.detail = Some(format!("reason: {r}"));
            }
            outcome.ok = ok;
        }
    }
    outcome
}

pub fn run_selftests(manifest: &Manifest, rules: &[Rule]) -> Vec<CaseOutcome> {
    rules.iter().flat_map(|r| r.fixtures.iter().map(move |fx| run_fixture(manifest, r, fx))).collect()
}
