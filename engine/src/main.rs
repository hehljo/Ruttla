//! `ruttla-engine` — Rust-Engine für deklarative Regeln (ADR-0011).
//!
//! Exit: 0 = Ergebnis auf stdout · 2 = Eingabe nicht prüfbar (JSON mit
//! `error`, wie GateInputError) · 3 = Fehlbedienung.

use std::path::PathBuf;
use std::process::ExitCode;

use ruttla_engine::detect::{detect, parse_manifest, Manifest, EMBEDDED_MANIFEST};
use ruttla_engine::inventory::{inventory, InventoryConfig};
use serde_json::json;

const USAGE: &str = "usage: ruttla-engine --version
       ruttla-engine inventory ROOT [OPTIONEN]
       ruttla-engine detect ROOT [--manifest DATEI] [OPTIONEN]
       ruttla-engine check-manifest [DATEI]
OPTIONEN: [--exclude-dir D]... [--exclude-glob G]... [--max-file-bytes N]";

fn usage_error(msg: &str) -> ExitCode {
    eprintln!("ruttla-engine: {msg}\n{USAGE}");
    ExitCode::from(3)
}

struct Invocation {
    root: PathBuf,
    cfg: InventoryConfig,
    manifest: Option<PathBuf>,
}

/// Gemeinsame Optionen von Inventar und Erkennung.
fn parse_inventory_args(args: &[String]) -> Result<Invocation, String> {
    let mut cfg = InventoryConfig::default();
    let mut root: Option<PathBuf> = None;
    let mut manifest: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        let mut value = |flag: &str| it.next().cloned().ok_or(format!("{flag} braucht einen Wert"));
        match a.as_str() {
            "--manifest" => manifest = Some(PathBuf::from(value("--manifest")?)),
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
    Ok(Invocation { root: root.ok_or("ROOT fehlt")?, cfg, manifest })
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
        Some("detect") => {
            let inv = match parse_inventory_args(&args[1..]) {
                Ok(v) => v,
                Err(e) => return usage_error(&e),
            };
            let manifest = match load_manifest(inv.manifest.as_ref()) {
                Ok(m) => m,
                Err(e) => return manifest_error(&e),
            };
            let result = inventory(&inv.root, &inv.cfg)
                .and_then(|(files, _)| detect(&manifest, &inv.root, &inv.cfg, &files));
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
            if inv.manifest.is_some() {
                return usage_error("--manifest gilt nur für detect");
            }
            match inventory(&inv.root, &inv.cfg) {
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
