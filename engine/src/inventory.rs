//! Dateiinventar mit derselben Semantik wie `ruttla.discovery.inventory`.
//!
//! Jede Datei wird entweder weitergereicht oder in der Coverage verbucht;
//! eine unlesbare Eingabe macht den ganzen Lauf ungültig. Symlinks dürfen die
//! Wurzel nicht verlassen, ein Link ohne Ziel ist eine Lücke, ein Link auf
//! eine schon erfasste Datei ein Alias.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::glob::Glob;
use crate::realpath::realpath;

pub const DEFAULT_EXCLUDE_DIRS: &[&str] = &[
    ".git", ".hg", ".svn", "node_modules", "DerivedData", ".build", "build",
    "dist", ".next", ".nuxt", "out", "venv", ".venv", "env", "__pycache__",
    ".godot", ".import", "Pods", "Carthage", ".gradle", "target", "bin", "obj",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", ".turbo",
    "vendor", ".terraform", ".cache", "Library", "Temp", "addons",
    ".qualitygate-work", ".temp", ".tmp", "tmp", ".svelte-kit", ".astro",
    ".parcel-cache", ".angular", "__snapshots__", "migrations_backup",
    ".vercel", ".netlify", ".supabase", "storybook-static", ".docusaurus",
    ".ruttla",
];

pub const AGENT_INSTRUCTION_FILES: &[&str] = &[
    "CLAUDE.md", "AGENTS.md", "GEMINI.md", "HANDOVER.md",
    "ROADMAP.md", "MASTER_ROADMAP.md", ".qualitygate.toml", ".ruttla.toml",
];

pub const DEFAULT_MAX_FILE_BYTES: u64 = 2_000_000;

#[derive(Debug, Clone)]
pub struct InventoryConfig {
    pub exclude_dirs: Vec<String>,
    pub exclude_globs: Vec<String>,
    pub max_file_bytes: u64,
}

impl Default for InventoryConfig {
    fn default() -> Self {
        InventoryConfig { exclude_dirs: Vec::new(), exclude_globs: Vec::new(), max_file_bytes: DEFAULT_MAX_FILE_BYTES }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SourceFile {
    #[serde(skip)]
    pub path: PathBuf,
    pub rel: String,
    pub ext: String,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SkippedFile {
    pub file: String,
    pub reason: String,
    pub bytes: u64,
}

/// Feldnamen exakt wie `Coverage.to_dict()` in Python.
#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct Coverage {
    pub files_scanned: usize,
    pub files_skipped: Vec<SkippedFile>,
    pub files_skipped_total: usize,
    pub files_excluded_agent_instructions: usize,
    pub files_excluded_by_config: usize,
    pub files_skipped_symlink_alias: usize,
    pub files_skipped_broken_symlink: Vec<String>,
    pub max_file_bytes: u64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct InputError {
    /// unreadable_dir · unreadable_file · outside_root
    pub kind: String,
    pub path: String,
    pub message: String,
}

/// `os.path.splitext(name)[1].lower()`
pub fn ext_of(name: &str) -> String {
    let Some(dot) = name.rfind('.') else { return String::new() };
    if name[..dot].chars().all(|c| c == '.') {
        return String::new();
    }
    name[dot..].to_lowercase()
}

fn inside(root_real: &Path, resolved: &Path) -> bool {
    resolved.starts_with(root_real)
}

struct Walker<'a> {
    cfg: &'a InventoryConfig,
    globs: Vec<Glob>,
    exclude_dirs: HashSet<&'a str>,
    root_real: PathBuf,
    found: Vec<SourceFile>,
    coverage: Coverage,
    aliases: Vec<(PathBuf, String, String, PathBuf)>,
}

impl<'a> Walker<'a> {
    fn admit(&mut self, full: &Path, rel: &str, name: &str) -> Result<(), InputError> {
        let not_checkable = |e: std::io::Error| InputError {
            kind: "unreadable_file".into(),
            path: rel.to_string(),
            message: format!("Eingabedatei nicht prüfbar: {rel}: {e}"),
        };
        let size = fs::metadata(full).map_err(not_checkable)?.len();
        if size > self.cfg.max_file_bytes {
            self.coverage.files_skipped.push(SkippedFile {
                file: rel.to_string(),
                reason: "max_file_bytes".into(),
                bytes: size,
            });
            return Ok(());
        }
        fs::File::open(full).map_err(not_checkable)?;
        self.found.push(SourceFile { path: full.to_path_buf(), rel: rel.to_string(), ext: ext_of(name) });
        Ok(())
    }

    /// Ein Verzeichnis wie `os.walk(followlinks=False)`: erst die Dateien,
    /// dann die Unterverzeichnisse, beides sortiert.
    fn walk(&mut self, dir: &Path, rel_dir: &str) -> Result<(), InputError> {
        let entries = fs::read_dir(dir).map_err(|e| InputError {
            kind: "unreadable_dir".into(),
            path: rel_dir.to_string(),
            message: format!("Eingabeverzeichnis nicht lesbar: {}: {e}", dir.display()),
        })?;
        let mut dirs: Vec<(String, bool)> = Vec::new();
        let mut files: Vec<String> = Vec::new();
        for entry in entries {
            let entry = entry.map_err(|e| InputError {
                kind: "unreadable_dir".into(),
                path: rel_dir.to_string(),
                message: format!("Eingabeverzeichnis nicht lesbar: {}: {e}", dir.display()),
            })?;
            let name = entry.file_name().to_string_lossy().into_owned();
            // DirEntry.is_dir() in Python folgt Links; Fehler zählen als "keine Datei".
            let is_link = entry.file_type().map(|t| t.is_symlink()).unwrap_or(false);
            let is_dir = fs::metadata(entry.path()).map(|m| m.is_dir()).unwrap_or(false);
            if is_dir {
                dirs.push((name, is_link));
            } else {
                files.push(name);
            }
        }
        files.sort();
        dirs.sort();
        for name in files {
            let full = dir.join(&name);
            let rel = if rel_dir.is_empty() { name.clone() } else { format!("{rel_dir}/{name}") };
            if AGENT_INSTRUCTION_FILES.contains(&name.as_str()) {
                self.coverage.files_excluded_agent_instructions += 1;
                continue;
            }
            if self.globs.iter().any(|g| g.is_match(&rel)) {
                self.coverage.files_excluded_by_config += 1;
                continue;
            }
            let resolved = realpath(&full);
            if !inside(&self.root_real, &resolved) {
                return Err(InputError {
                    kind: "outside_root".into(),
                    path: rel.clone(),
                    message: format!("Eingabepfad verlässt die Prüfwurzel: {rel}"),
                });
            }
            let is_link = fs::symlink_metadata(&full).map(|m| m.file_type().is_symlink()).unwrap_or(false);
            if is_link && fs::metadata(&full).is_err() {
                self.coverage.files_skipped_broken_symlink.push(rel);
                continue;
            }
            if is_link {
                self.aliases.push((full, rel, name, resolved));
                continue;
            }
            self.admit(&full, &rel, &name)?;
        }
        for (name, is_link) in dirs {
            if self.exclude_dirs.contains(name.as_str())
                || name.ends_with(".xcassets")
                || is_link
                || is_capacitor_copy(dir, &name)
            {
                continue;
            }
            let rel = if rel_dir.is_empty() { name.clone() } else { format!("{rel_dir}/{name}") };
            self.walk(&dir.join(&name), &rel)?;
        }
        Ok(())
    }
}

/// Die Kopie, die `cap copy` in ein natives Projekt schreibt — erkannt an
/// capacitor.config.json daneben und cordova_plugins.js darin. Gleiche
/// Regel in src/ruttla/discovery.py (is_capacitor_copy).
fn is_capacitor_copy(parent: &Path, name: &str) -> bool {
    name == "public"
        && parent.join("capacitor.config.json").is_file()
        && parent.join(name).join("cordova_plugins.js").is_file()
}

pub fn inventory(root: &Path, cfg: &InventoryConfig) -> Result<(Vec<SourceFile>, Coverage), InputError> {
    let root = if root.is_absolute() {
        root.to_path_buf()
    } else {
        std::env::current_dir().map(|c| c.join(root)).unwrap_or_else(|_| root.to_path_buf())
    };
    let mut w = Walker {
        cfg,
        globs: cfg.exclude_globs.iter().map(|g| Glob::new(g)).collect(),
        exclude_dirs: DEFAULT_EXCLUDE_DIRS.iter().copied().chain(cfg.exclude_dirs.iter().map(String::as_str)).collect(),
        root_real: realpath(&root),
        found: Vec::new(),
        coverage: Coverage { max_file_bytes: cfg.max_file_bytes, ..Coverage::default() },
        aliases: Vec::new(),
    };
    w.walk(&root, "")?;
    let mut scanned: HashSet<PathBuf> = w.found.iter().map(|sf| realpath(&sf.path)).collect();
    for (full, rel, name, resolved) in std::mem::take(&mut w.aliases) {
        if scanned.contains(&resolved) {
            w.coverage.files_skipped_symlink_alias += 1;
            continue;
        }
        w.admit(&full, &rel, &name)?;
        scanned.insert(resolved);
    }
    w.coverage.files_scanned = w.found.len();
    w.coverage.files_skipped_total = w.coverage.files_skipped.len();
    Ok((w.found, w.coverage))
}

#[cfg(test)]
mod tests {
    use super::ext_of;

    #[test]
    fn ext_matches_python_splitext() {
        assert_eq!(ext_of("a.Swift"), ".swift");
        assert_eq!(ext_of(".bashrc"), "");
        assert_eq!(ext_of("..x"), "");
        assert_eq!(ext_of(".a.b"), ".b");
        assert_eq!(ext_of("a.tar.gz"), ".gz");
        assert_eq!(ext_of("file."), ".");
        assert_eq!(ext_of("Makefile"), "");
    }
}
