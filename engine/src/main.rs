//! `ruttla-engine` — Rust-Engine für deklarative Regeln (ADR-0011).
//!
//! Exit: 0 = Ergebnis auf stdout · 2 = Eingabe nicht prüfbar (JSON mit
//! `error`, wie GateInputError) · 3 = Fehlbedienung.

use std::path::PathBuf;
use std::process::ExitCode;

use ruttla_engine::inventory::{inventory, InventoryConfig};
use serde_json::json;

const USAGE: &str = "usage: ruttla-engine --version
       ruttla-engine inventory ROOT [--exclude-dir D]... [--exclude-glob G]... [--max-file-bytes N]";

fn usage_error(msg: &str) -> ExitCode {
    eprintln!("ruttla-engine: {msg}\n{USAGE}");
    ExitCode::from(3)
}

/// Gemeinsame Optionen des Inventars; liefert (Wurzel, Konfiguration).
fn parse_inventory_args(args: &[String]) -> Result<(PathBuf, InventoryConfig), String> {
    let mut cfg = InventoryConfig::default();
    let mut root: Option<PathBuf> = None;
    let mut it = args.iter();
    while let Some(a) = it.next() {
        let mut value = |flag: &str| it.next().cloned().ok_or(format!("{flag} braucht einen Wert"));
        match a.as_str() {
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
    Ok((root.ok_or("ROOT fehlt")?, cfg))
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("--version") if args.len() == 1 => {
            println!("ruttla-engine {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        Some("inventory") => {
            let (root, cfg) = match parse_inventory_args(&args[1..]) {
                Ok(v) => v,
                Err(e) => return usage_error(&e),
            };
            match inventory(&root, &cfg) {
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
