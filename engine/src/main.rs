//! `ruttla-engine` — Rust-Engine für deklarative Regeln (ADR-0011).
//!
//! Exit: 0 = Ergebnis auf stdout · 2 = Eingabe nicht prüfbar (JSON mit
//! `error`, wie GateInputError) · 3 = Fehlbedienung.

use std::path::PathBuf;
use std::process::ExitCode;

use ruttla_engine::detect::{detect, parse_manifest, Manifest, EMBEDDED_MANIFEST};
use ruttla_engine::inventory::{inventory, InventoryConfig};
use ruttla_engine::rules::{load_rules, Rule};
use ruttla_engine::runner::{scan, View};
use ruttla_engine::selftest::run_selftests;
use serde_json::json;

const USAGE: &str = "usage: ruttla-engine --version
       ruttla-engine inventory ROOT [OPTIONEN]
       ruttla-engine detect ROOT [--manifest DATEI] [OPTIONEN]
       ruttla-engine check-manifest [DATEI]
       ruttla-engine check-rules --rules DIR... [--manifest DATEI]
       ruttla-engine scan ROOT --rules DIR... [--rule ID]... [--view scoped|unscoped] [--threads N] [--manifest DATEI] [OPTIONEN]
       ruttla-engine selftest --rules DIR... [--rule ID]... [--manifest DATEI]
OPTIONEN: [--exclude-dir D]... [--exclude-glob G]... [--max-file-bytes N]";

fn usage_error(msg: &str) -> ExitCode {
    eprintln!("ruttla-engine: {msg}\n{USAGE}");
    ExitCode::from(3)
}

struct Invocation {
    root: Option<PathBuf>,
    cfg: InventoryConfig,
    manifest: Option<PathBuf>,
    rules: Vec<PathBuf>,
    only: Vec<String>,
    view: View,
    threads: usize,
}

/// Gemeinsame Optionen von Inventar und Erkennung.
fn parse_inventory_args(args: &[String]) -> Result<Invocation, String> {
    let mut cfg = InventoryConfig::default();
    let mut root: Option<PathBuf> = None;
    let mut manifest: Option<PathBuf> = None;
    let mut rules: Vec<PathBuf> = Vec::new();
    let mut only = Vec::new();
    let mut view = View::Scoped;
    let mut threads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
    let mut it = args.iter();
    while let Some(a) = it.next() {
        let mut value = |flag: &str| it.next().cloned().ok_or(format!("{flag} braucht einen Wert"));
        match a.as_str() {
            "--manifest" => manifest = Some(PathBuf::from(value("--manifest")?)),
            "--rules" => rules.push(PathBuf::from(value("--rules")?)),
            "--rule" => only.push(value("--rule")?),
            "--view" => {
                view = match value("--view")?.as_str() {
                    "scoped" => View::Scoped,
                    "unscoped" => View::Unscoped,
                    v => return Err(format!("--view {v}: scoped oder unscoped")),
                }
            }
            "--threads" => {
                threads = value("--threads")?.parse().ok().filter(|&n| n > 0)
                    .ok_or("--threads muss eine positive Ganzzahl sein")?
            }
            "--exclude-dir" => cfg.exclude_dirs.push(value("--exclude-dir")?),
            "--exclude-glob" => cfg.exclude_globs.push(value("--exclude-glob")?),
            "--max-file-bytes" => {
                cfg.max_file_bytes = value("--max-file-bytes")?
                    .parse()
                    .map_err(|_| "--max-file-bytes muss eine positive Ganzzahl sein".to_string())?
            }
            s if s.starts_with("--") => return Err(format!("unbekannte Option {s}")),
            s if root.is_none() => root = Some(PathBuf::from(s)),
            s => return Err(format!("überzähliges Argument {s}")),
        }
    }
    Ok(Invocation { root, cfg, manifest, rules, only, view, threads })
}

fn load_manifest(path: Option<&PathBuf>) -> Result<Manifest, String> {
    let text = match path {
        Some(p) => std::fs::read_to_string(p).map_err(|e| format!("{}: {e}", p.display()))?,
        None => EMBEDDED_MANIFEST.to_string(),
    };
    parse_manifest(&text)
}

/// Ein ungültiges Manifest ist eine kaputte Installation, keine Eingabe.
fn manifest_error(msg: &str) -> ExitCode {
    println!("{}", json!({"error": {"kind": "manifest", "path": "", "message": msg}}));
    ExitCode::from(3)
}

fn need_root(inv: &Invocation) -> Result<PathBuf, ExitCode> {
    inv.root.clone().ok_or_else(|| usage_error("ROOT fehlt"))
}

/// Regeln laden und auf `--rule` einschränken; Fehler gesammelt, Exit 3.
fn load_selected(inv: &Invocation, manifest: &Manifest) -> Result<Vec<Rule>, ExitCode> {
    if inv.rules.is_empty() {
        return Err(usage_error("--rules DIR fehlt"));
    }
    let known = manifest.platforms.iter().map(|p| p.name.clone()).collect();
    // Mehrere Verzeichnisse (offiziell + Hub-Pakete): dieselbe id in zwei
    // Verzeichnissen ist ein Abbruch, nie ein stilles Überschreiben.
    let mut rules: Vec<Rule> = Vec::new();
    let mut origin: std::collections::HashMap<String, &PathBuf> = std::collections::HashMap::new();
    for dir in &inv.rules {
        let loaded = match load_rules(dir, &known) {
            Ok(r) => r,
            Err(errors) => {
                println!("{}", json!({"error": {"kind": "rules", "path": dir.display().to_string(), "message": errors.join("\n")}}));
                return Err(ExitCode::from(3));
            }
        };
        for r in loaded {
            if let Some(first) = origin.insert(r.id.clone(), dir) {
                let msg = format!("id {} kommt in {} und {} vor", r.id, first.display(), dir.display());
                println!("{}", json!({"error": {"kind": "rules", "path": dir.display().to_string(), "message": msg}}));
                return Err(ExitCode::from(3));
            }
            rules.push(r);
        }
    }
    if inv.only.is_empty() {
        return Ok(rules);
    }
    let unknown: Vec<&String> = inv.only.iter().filter(|id| !rules.iter().any(|r| &r.id == *id)).collect();
    if !unknown.is_empty() {
        return Err(usage_error(&format!("unbekannte Regel: {unknown:?}")));
    }
    // Reihenfolge wie angefragt — der Aufrufer mischt in seine eigene Ordnung.
    let mut by_id: std::collections::HashMap<String, Rule> = rules.into_iter().map(|r| (r.id.clone(), r)).collect();
    Ok(inv.only.iter().filter_map(|id| by_id.remove(id)).collect())
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--version") if args.len() == 1 => {
            println!("ruttla-engine {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        Some("check-manifest") if args.len() <= 2 => {
            match load_manifest(args.get(1).map(PathBuf::from).as_ref()) {
                Ok(m) => {
                    println!("{}", json!({"platforms": m.platforms.iter().map(|p| &p.name).collect::<Vec<_>>()}));
                    ExitCode::SUCCESS
                }
                Err(e) => manifest_error(&e),
            }
        }
        Some(cmd @ ("check-rules" | "scan" | "selftest")) => {
            let inv = match parse_inventory_args(&args[1..]) {
                Ok(v) => v,
                Err(e) => return usage_error(&e),
            };
            let manifest = match load_manifest(inv.manifest.as_ref()) {
                Ok(m) => m,
                Err(e) => return manifest_error(&e),
            };
            let rules = match load_selected(&inv, &manifest) {
                Ok(r) => r,
                Err(code) => return code,
            };
            match cmd {
                "check-rules" => {
                    println!("{}", json!({"rules": rules.iter().map(|r| &r.id).collect::<Vec<_>>()}));
                    ExitCode::SUCCESS
                }
                "selftest" => {
                    let cases = run_selftests(&manifest, &rules);
                    let passed = cases.iter().filter(|c| c.ok).count();
                    println!("{}", json!({"cases": cases, "passed": passed, "total": cases.len()}));
                    if cases.is_empty() || passed != cases.len() { ExitCode::from(1) } else { ExitCode::SUCCESS }
                }
                _ => {
                    let root = match need_root(&inv) {
                        Ok(r) => r,
                        Err(code) => return code,
                    };
                    match scan(&manifest, &root, &inv.cfg, &rules, inv.view, inv.threads) {
                        Ok(results) => {
                            println!("{}", json!({"results": results}));
                            ExitCode::SUCCESS
                        }
                        Err(err) => {
                            println!("{}", json!({"error": err}));
                            ExitCode::from(2)
                        }
                    }
                }
            }
        }
        Some("detect") => {
            let inv = match parse_inventory_args(&args[1..]) {
                Ok(v) => v,
                Err(e) => return usage_error(&e),
            };
            let manifest = match load_manifest(inv.manifest.as_ref()) {
                Ok(m) => m,
                Err(e) => return manifest_error(&e),
            };
            let root = match need_root(&inv) {
                Ok(r) => r,
                Err(code) => return code,
            };
            let result = inventory(&root, &inv.cfg)
                .and_then(|(files, _)| detect(&manifest, &root, &inv.cfg, &files));
            match result {
                Ok(d) => {
                    println!("{}", json!({"platforms": d.platforms, "roots": d.roots}));
                    ExitCode::SUCCESS
                }
                Err(err) => {
                    println!("{}", json!({"error": err}));
                    ExitCode::from(2)
                }
            }
        }
        Some("inventory") => {
            let inv = match parse_inventory_args(&args[1..]) {
                Ok(v) => v,
                Err(e) => return usage_error(&e),
            };
            if inv.manifest.is_some() || !inv.rules.is_empty() {
                return usage_error("--manifest/--rules gelten nicht für inventory");
            }
            let root = match need_root(&inv) {
                Ok(r) => r,
                Err(code) => return code,
            };
            match inventory(&root, &inv.cfg) {
                Ok((files, coverage)) => {
                    println!("{}", json!({"files": files, "coverage": coverage}));
                    ExitCode::SUCCESS
                }
                Err(err) => {
                    println!("{}", json!({"error": err}));
                    ExitCode::from(2)
                }
            }
        }
        _ => usage_error("unbekannter Aufruf"),
    }
}
