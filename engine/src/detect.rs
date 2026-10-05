//! Plattform-Erkennung aus `platforms.toml` — dieselbe Datei, dieselbe
//! Validierung und dieselbe Logik wie `ruttla.platforms` (P11-T003).

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::Path;

use regex::Regex;
use serde::Serialize;

use crate::glob::Glob;
use crate::inventory::{InputError, InventoryConfig, SourceFile, DEFAULT_EXCLUDE_DIRS};
use crate::text::{is_rule_definition, read_text};

pub const MANIFEST_VERSION: i64 = 1;
/// Das Manifest des Python-Pakets, beim Bau eingebettet; `--manifest` ersetzt es.
pub const EMBEDDED_MANIFEST: &str = include_str!("../../src/ruttla/platforms.toml");

const PLATFORM_KEYS: &[&str] = &["pack", "always", "extensions", "file_names", "file_suffixes",
    "dir_suffixes", "content", "requires", "root_markers", "claims"];
const CONTENT_KEYS: &[&str] = &["extensions", "pattern", "examples", "counter_examples"];

#[derive(Debug)]
pub struct ContentSignal {
    pub extensions: Vec<String>,
    pub pattern: Regex,
}

#[derive(Debug)]
pub struct PlatformSpec {
    pub name: String,
    pub pack: bool,
    pub always: bool,
    pub extensions: HashSet<String>,
    pub file_names: HashSet<String>,
    pub file_suffixes: Vec<String>,
    pub dir_suffixes: Vec<String>,
    pub content: Vec<ContentSignal>,
    pub requires: Vec<String>,
    /// Je Marker die Segmente, einmal übersetzt (fnmatchcase).
    pub root_markers: Vec<Vec<Glob>>,
    pub claims: HashSet<String>,
}

/// Plattformen in Manifest-Reihenfolge (wie Pythons dict).
#[derive(Debug)]
pub struct Manifest {
    pub platforms: Vec<PlatformSpec>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct ProjectRoot {
    pub path: String,
    pub platform: String,
    pub marker: String,
}

impl ProjectRoot {
    pub fn contains(&self, rel: &str) -> bool {
        self.path == "." || rel.starts_with(&format!("{}/", self.path))
    }
}

type MResult<T> = Result<T, String>;

fn strings(where_: &str, value: Option<&toml::Value>) -> MResult<Vec<String>> {
    let err = || format!("{where_} muss eine Liste nicht-leerer Strings sein.");
    let arr = value.and_then(|v| v.as_array()).ok_or_else(err)?;
    arr.iter()
        .map(|v| v.as_str().filter(|s| !s.is_empty()).map(str::to_string).ok_or_else(err))
        .collect()
}

fn strings_or_empty(where_: &str, value: Option<&toml::Value>) -> MResult<Vec<String>> {
    match value {
        None => Ok(Vec::new()),
        some => strings(where_, some),
    }
}

/// Pythons `bool(x)` für TOML-Werte.
fn truthy(v: &toml::Value) -> bool {
    match v {
        toml::Value::Boolean(b) => *b,
        toml::Value::Integer(i) => *i != 0,
        toml::Value::Float(f) => *f != 0.0,
        toml::Value::String(s) => !s.is_empty(),
        toml::Value::Array(a) => !a.is_empty(),
        toml::Value::Table(t) => !t.is_empty(),
        toml::Value::Datetime(_) => true,
    }
}

fn unknown_keys(table: &toml::value::Table, allowed: &[&str]) -> Vec<String> {
    let mut out: Vec<String> = table.keys().filter(|k| !allowed.contains(&k.as_str())).cloned().collect();
    out.sort();
    out
}

fn content(name: &str, i: usize, raw: &toml::Value) -> MResult<ContentSignal> {
    let where_ = format!("platforms.{name}.content[{i}]");
    let t = raw.as_table().ok_or(format!("{where_} muss eine Tabelle sein."))?;
    let unknown = unknown_keys(t, CONTENT_KEYS);
    if !unknown.is_empty() {
        return Err(format!("{where_}: unbekannte Schlüssel {unknown:?}"));
    }
    let text = t.get("pattern").and_then(|v| v.as_str()).filter(|s| !s.is_empty())
        .ok_or(format!("{where_}.pattern fehlt."))?;
    // Nur die `regex`-Crate (linear): Lookaround und Rückverweise scheitern
    // hier beim Laden statt später an fremden Dateien (ADR-0011).
    let pattern = Regex::new(&format!("(?m){text}")).map_err(|e| format!("{where_}.pattern ungültig: {e}"))?;
    let examples = strings(&format!("{where_}.examples"), t.get("examples"))?;
    let counter = strings(&format!("{where_}.counter_examples"), t.get("counter_examples"))?;
    for ex in &examples {
        if !pattern.is_match(ex) {
            return Err(format!("{where_}: Beispiel trifft nicht: {ex:?}"));
        }
    }
    for ex in &counter {
        if pattern.is_match(ex) {
            return Err(format!("{where_}: Gegenbeispiel trifft: {ex:?}"));
        }
    }
    let exts = strings(&format!("{where_}.extensions"), t.get("extensions"))?;
    Ok(ContentSignal { extensions: exts.iter().map(|e| e.to_lowercase()).collect(), pattern })
}

fn marker(name: &str, text: &str) -> MResult<Vec<Glob>> {
    let segs: Vec<&str> = text.split('/').collect();
    if segs.iter().any(|s| s.is_empty() || *s == "." || *s == "..") {
        return Err(format!("platforms.{name}.root_markers: ungültiger Pfad {text:?}"));
    }
    Ok(segs.into_iter().map(Glob::new_case).collect())
}

pub fn parse_manifest(text: &str) -> MResult<Manifest> {
    let doc: toml::Table = text.parse().map_err(|e| format!("platforms.toml ist kein gültiges TOML: {e}"))?;
    // Python vergleicht mit `!=`: 1, 1.0 und true sind dort gleich.
    let version_ok = match doc.get("manifest_version") {
        Some(toml::Value::Integer(i)) => *i == MANIFEST_VERSION,
        Some(toml::Value::Float(f)) => *f == MANIFEST_VERSION as f64,
        Some(toml::Value::Boolean(b)) => *b == (MANIFEST_VERSION == 1),
        _ => false,
    };
    if !version_ok {
        return Err(format!("manifest_version muss {MANIFEST_VERSION} sein."));
    }
    let unknown = unknown_keys(&doc, &["manifest_version", "platforms"]);
    if !unknown.is_empty() {
        return Err(format!("Unbekannte Schlüssel: {unknown:?}"));
    }
    let platforms = doc.get("platforms").and_then(|v| v.as_table()).filter(|t| !t.is_empty())
        .ok_or("Null Plattformen im Manifest — die Erkennung prüft nichts.")?;
    let mut specs: Vec<PlatformSpec> = Vec::new();
    for (name, raw) in platforms {
        let t = raw.as_table().ok_or(format!("platforms.{name} muss eine Tabelle sein."))?;
        let unknown = unknown_keys(t, PLATFORM_KEYS);
        if !unknown.is_empty() {
            return Err(format!("platforms.{name}: unbekannte Schlüssel {unknown:?}"));
        }
        let pack = t.get("pack").and_then(|v| v.as_bool())
            .ok_or(format!("platforms.{name}.pack muss true oder false sein."))?;
        let always = t.get("always").map(truthy).unwrap_or(false);
        let content_raw = match t.get("content") {
            None => Vec::new(),
            Some(toml::Value::Array(a)) => a.clone(),
            Some(_) => return Err(format!("platforms.{name}.content muss eine Liste sein.")),
        };
        let lower = |v: Vec<String>| v.into_iter().map(|s| s.to_lowercase()).collect::<HashSet<_>>();
        let spec = PlatformSpec {
            name: name.clone(),
            pack,
            always,
            extensions: lower(strings_or_empty(&format!("platforms.{name}.extensions"), t.get("extensions"))?),
            file_names: lower(strings_or_empty(&format!("platforms.{name}.file_names"), t.get("file_names"))?),
            file_suffixes: strings_or_empty(&format!("platforms.{name}.file_suffixes"), t.get("file_suffixes"))?,
            dir_suffixes: strings_or_empty(&format!("platforms.{name}.dir_suffixes"), t.get("dir_suffixes"))?,
            content: content_raw.iter().enumerate().map(|(i, c)| content(name, i, c)).collect::<MResult<_>>()?,
            requires: strings_or_empty(&format!("platforms.{name}.requires"), t.get("requires"))?,
            root_markers: strings_or_empty(&format!("platforms.{name}.root_markers"), t.get("root_markers"))?
                .iter().map(|m| marker(name, m)).collect::<MResult<_>>()?,
            claims: lower(strings_or_empty(&format!("platforms.{name}.claims"), t.get("claims"))?),
        };
        if !spec.claims.is_empty() && spec.root_markers.is_empty() {
            return Err(format!("platforms.{name}.claims braucht root_markers — \
                                ohne Wurzel gälte der Anspruch fürs ganze Repo."));
        }
        let has_signal = !(spec.extensions.is_empty() && spec.file_names.is_empty()
            && spec.file_suffixes.is_empty() && spec.dir_suffixes.is_empty()
            && spec.content.is_empty() && spec.root_markers.is_empty());
        if !spec.always && !has_signal {
            return Err(format!("platforms.{name}: kein einziges Erkennungssignal."));
        }
        specs.push(spec);
    }
    let names: HashSet<&str> = specs.iter().map(|s| s.name.as_str()).collect();
    for spec in &specs {
        for dep in &spec.requires {
            if !names.contains(dep.as_str()) {
                return Err(format!("platforms.{}.requires: unbekannt {dep:?}", spec.name));
            }
        }
    }
    Ok(Manifest { platforms: specs })
}

impl Manifest {
    pub fn get(&self, name: &str) -> &PlatformSpec {
        self.platforms.iter().find(|s| s.name == name).expect("platform from this manifest")
    }
}

fn match_marker(segments: &[Glob], rel: &str) -> Option<String> {
    let parts: Vec<&str> = rel.split('/').collect();
    let k = segments.len();
    if parts.len() < k {
        return None;
    }
    let tail = &parts[parts.len() - k..];
    if tail.iter().zip(segments).all(|(p, s)| s.is_match(p)) {
        let head = parts[..parts.len() - k].join("/");
        return Some(if head.is_empty() { ".".to_string() } else { head });
    }
    None
}

pub fn find_roots(manifest: &Manifest, files: &[SourceFile]) -> Vec<ProjectRoot> {
    let mut roots: BTreeMap<(String, String), ProjectRoot> = BTreeMap::new();
    for spec in &manifest.platforms {
        for f in files {
            for segs in &spec.root_markers {
                if let Some(path) = match_marker(segs, &f.rel) {
                    roots.entry((path.clone(), spec.name.clone()))
                        .or_insert(ProjectRoot { path, platform: spec.name.clone(), marker: f.rel.clone() });
                }
            }
        }
    }
    roots.into_values().collect()
}

pub fn claimed_files(manifest: &Manifest, files: &[SourceFile], roots: &[ProjectRoot]) -> HashMap<String, String> {
    let mut owners = HashMap::new();
    let mut claiming: Vec<&ProjectRoot> = roots.iter().filter(|r| !manifest.get(&r.platform).claims.is_empty()).collect();
    claiming.sort_by_key(|r| if r.path == "." { 0 } else { r.path.matches('/').count() + 1 });
    for root in claiming {
        let claims = &manifest.get(&root.platform).claims;
        for f in files {
            if claims.contains(&f.ext) && root.contains(&f.rel) {
                owners.insert(f.rel.clone(), root.platform.clone());
            }
        }
    }
    owners
}

/// `Context.dirs_with_suffix`: eigener Verzeichnislauf ohne .xcassets-Ausnahme,
/// mit Profil-Globs auf `rel` und `rel/`.
fn dirs_with_suffix(root: &Path, cfg: &InventoryConfig, suffix: &str) -> Result<bool, InputError> {
    let globs: Vec<Glob> = cfg.exclude_globs.iter().map(|g| Glob::new(g)).collect();
    let excluded: HashSet<&str> = DEFAULT_EXCLUDE_DIRS.iter().copied().chain(cfg.exclude_dirs.iter().map(String::as_str)).collect();
    fn walk(dir: &Path, rel_dir: &str, suffix: &str, globs: &[Glob], excluded: &HashSet<&str>) -> Result<bool, InputError> {
        let rd = fs::read_dir(dir).map_err(|e| InputError {
            kind: "unreadable_dir".into(),
            path: rel_dir.to_string(),
            message: format!("Eingabeverzeichnis nicht lesbar: {}: {e}", dir.display()),
        })?;
        let mut dirs: Vec<(String, bool)> = Vec::new();
        for entry in rd.flatten() {
            if fs::metadata(entry.path()).map(|m| m.is_dir()).unwrap_or(false) {
                let is_link = entry.file_type().map(|t| t.is_symlink()).unwrap_or(false);
                dirs.push((entry.file_name().to_string_lossy().into_owned(), is_link));
            }
        }
        dirs.sort();
        let mut kept = Vec::new();
        for (name, is_link) in dirs {
            let rel = if rel_dir.is_empty() { name.clone() } else { format!("{rel_dir}/{name}") };
            if excluded.contains(name.as_str())
                || globs.iter().any(|g| g.is_match(&rel) || g.is_match(&format!("{rel}/")))
            {
                continue;
            }
            if name.ends_with(suffix) {
                return Ok(true);
            }
            kept.push((name, rel, is_link));
        }
        for (name, rel, is_link) in kept {
            if !is_link && walk(&dir.join(&name), &rel, suffix, globs, excluded)? {
                return Ok(true);
            }
        }
        Ok(false)
    }
    walk(root, "", suffix, &globs, &excluded)
}

pub struct Detection {
    pub platforms: Vec<String>,
    pub roots: Vec<ProjectRoot>,
}

pub fn detect(manifest: &Manifest, root: &Path, cfg: &InventoryConfig, files: &[SourceFile]) -> Result<Detection, InputError> {
    let roots = find_roots(manifest, files);
    let owners = claimed_files(manifest, files, &roots);
    let mut texts: HashMap<String, Option<String>> = HashMap::new();
    let mut found: Vec<String> = Vec::new();
    let mut pending: Vec<&PlatformSpec> = manifest.platforms.iter().collect();
    loop {
        let mut progressed = false;
        let mut i = 0;
        while i < pending.len() {
            let spec = pending[i];
            if spec.requires.iter().any(|d| !found.contains(d)) {
                i += 1;
                continue;
            }
            pending.remove(i);
            progressed = true;
            if present(spec, root, cfg, files, &owners, &mut texts)? {
                found.push(spec.name.clone());
            }
        }
        if !progressed {
            break;
        }
    }
    found.sort();
    Ok(Detection { platforms: found, roots })
}

fn present(
    spec: &PlatformSpec,
    root: &Path,
    cfg: &InventoryConfig,
    files: &[SourceFile],
    owners: &HashMap<String, String>,
    texts: &mut HashMap<String, Option<String>>,
) -> Result<bool, InputError> {
    if spec.always {
        return Ok(true);
    }
    // Sicht der Plattform: Dateien, die einer fremden Wurzel gehören, fehlen.
    let scoped: Vec<&SourceFile> = if spec.name == "universal" {
        files.iter().collect()
    } else {
        files.iter().filter(|f| owners.get(&f.rel).map_or(true, |o| *o == spec.name)).collect()
    };
    for f in &scoped {
        if spec.extensions.contains(&f.ext) {
            return Ok(true);
        }
        let base = f.rel.rsplit('/').next().unwrap_or(&f.rel).to_lowercase();
        if !spec.file_names.is_empty() && spec.file_names.contains(&base) {
            return Ok(true);
        }
        if spec.file_suffixes.iter().any(|s| f.rel.ends_with(s.as_str())) {
            return Ok(true);
        }
        if spec.root_markers.iter().any(|m| match_marker(m, &f.rel).is_some()) {
            return Ok(true);
        }
    }
    for suffix in &spec.dir_suffixes {
        if dirs_with_suffix(root, cfg, suffix)? {
            return Ok(true);
        }
    }
    for signal in &spec.content {
        for f in &scoped {
            if !signal.extensions.contains(&f.ext) {
                continue;
            }
            let text = texts.entry(f.rel.clone()).or_insert_with(|| read_text(&f.path).ok());
            let Some(text) = text.as_deref() else {
                return Err(InputError {
                    kind: "unreadable_file".into(),
                    path: f.rel.clone(),
                    message: format!("Eingabedatei nicht lesbar: {}", f.rel),
                });
            };
            if !is_rule_definition(text) && signal.pattern.is_match(text) {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_manifest_loads() {
        let m = parse_manifest(EMBEDDED_MANIFEST).expect("manifest valid");
        assert!(m.platforms.iter().any(|p| p.name == "universal" && p.always));
    }

    #[test]
    fn lookaround_is_rejected_at_load() {
        let bad = EMBEDDED_MANIFEST.replace(r"\b(?:UCLASS", r"(?<!MY_)\b(?:UCLASS");
        assert_ne!(bad, EMBEDDED_MANIFEST);
        let err = parse_manifest(&bad).unwrap_err();
        assert!(err.contains("pattern ungültig"), "{err}");
    }

    #[test]
    fn marker_matching_is_segmentwise_and_case_sensitive() {
        let segs = marker("unity", "ProjectSettings/ProjectVersion.txt").unwrap();
        assert_eq!(match_marker(&segs, "game/ProjectSettings/ProjectVersion.txt"), Some("game".into()));
        assert_eq!(match_marker(&segs, "ProjectSettings/ProjectVersion.txt"), Some(".".into()));
        assert_eq!(match_marker(&segs, "projectsettings/ProjectVersion.txt"), None);
        let star = marker("unreal", "*.uproject").unwrap();
        assert_eq!(match_marker(&star, "a/b/X.uproject"), Some("a/b".into()));
    }
}
