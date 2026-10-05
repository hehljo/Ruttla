//! Deklaratives Regelformat v0 (`ruttla-rule/0`, P10-T008).
//!
//! Eine Regel ist Daten: Metadaten, Dateiauswahl, ein Muster, Ausschlüsse,
//! Meldung und Pflicht-Fixtures (mindestens ein roter und ein grüner Fall).
//! Kein ausführbarer Code. Beim Laden abgelehnt wird alles, was später still
//! falsch messen würde: Lookaround/Rückverweise (die `regex`-Crate kennt sie
//! nicht), Platzhalter auf nicht vorhandene Gruppen, fehlende Fixtures und
//! `fix`-Texte, die eine API nennen, ohne Quelle.

use std::collections::{BTreeMap, HashSet};
use std::path::{Path, PathBuf};

use regex::Regex;
use serde::Deserialize;

pub const RULE_FORMAT: &str = "ruttla-rule/0";
pub const SEVERITIES: &[&str] = &["error", "warning", "info"];
pub const EXPECTS: &[&str] = &["pass", "fail", "unmeasured", "error"];
/// = `registry.LIFECYCLES`
pub const LIFECYCLES: &[&str] = &["experimental", "stable", "deprecated"];

// Katalog-Metadaten (rationale, tags, …) liest die Python-Seite; hier werden
// sie nur auf gültige Werte geprüft.
#[allow(dead_code)]
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawRule {
    format: String,
    id: String,
    title: String,
    platform: String,
    severity: String,
    #[serde(default)]
    guideline: String,
    #[serde(default)]
    rationale: String,
    #[serde(default)]
    references: Vec<String>,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    safe_by_default: bool,
    #[serde(default)]
    introduced_in: Option<String>,
    #[serde(default)]
    lifecycle: Option<String>,
    scope: RawScope,
    #[serde(rename = "match")]
    match_: RawMatch,
    #[serde(default)]
    fixtures: Vec<RawFixture>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawScope {
    extensions: Vec<String>,
    unit_label: String,
    #[serde(default)]
    no_files_reason: Option<String>,
    #[serde(default = "yes")]
    skip_comments: bool,
    #[serde(default)]
    include_rule_files: bool,
    #[serde(default)]
    require_text: Option<String>,
}

fn yes() -> bool {
    true
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawMatch {
    pattern: String,
    #[serde(default)]
    exclude: Vec<RawExclude>,
    message: String,
    #[serde(default)]
    fix: Option<String>,
    /// Leitlinie im Befund, falls sie von der Katalog-`guideline` abweicht.
    #[serde(default)]
    guideline: Option<String>,
    /// `true`: das Muster läuft je `splitlines`-Zeile, höchstens ein Treffer
    /// je Zeile — Port eines Python-Checks mit `pattern.search(zeile)`.
    /// `false`: über die ganze Datei, alle Treffer (`iter_matches`).
    #[serde(default)]
    per_line: bool,
}

/// Ausschluss: ein Treffer wird verworfen, wenn `pattern` auf das Ziel passt.
/// `on = "match"` (Vorgabe; mit `group` auf eine Gruppe), `"line"` (die
/// Rohzeile, getrimmt) oder `"path"` (relativer Pfad — die Datei zählt
/// trotzdem als geprüft).
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawExclude {
    #[serde(default = "on_match")]
    on: String,
    #[serde(default)]
    group: usize,
    pattern: String,
}

fn on_match() -> String {
    "match".to_string()
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ExcludeOn {
    Group(usize),
    Line,
    Path,
}

#[derive(Debug)]
pub struct Exclude {
    pub on: ExcludeOn,
    pub pattern: Regex,
}

#[derive(Debug, Deserialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct RawFixture {
    pub name: String,
    pub expect: String,
    #[serde(default)]
    pub expect_finding_contains: Option<String>,
    /// Genaue Befundzahl; misst z. B. "zwei Treffer in einer Zeile → einer".
    #[serde(default)]
    pub expect_findings: Option<usize>,
    pub files: BTreeMap<String, String>,
}


/// Teil einer Meldung: Text oder Gruppe mit optionaler Kürzung (`{2:40}`).
#[derive(Debug, Clone, PartialEq)]
pub enum Piece {
    Text(String),
    Group { index: usize, limit: Option<usize> },
}

#[derive(Debug)]
pub struct Rule {
    pub id: String,
    pub title: String,
    pub platform: String,
    pub severity: String,
    pub guideline: String,
    pub extensions: Vec<String>,
    pub unit_label: String,
    pub no_files_reason: String,
    pub skip_comments: bool,
    pub per_line: bool,
    pub include_rule_files: bool,
    pub require_text: Option<String>,
    pub pattern: Regex,
    pub exclude: Vec<Exclude>,
    pub message: Vec<Piece>,
    pub fix: Option<String>,
    pub fixtures: Vec<RawFixture>,
    pub source: PathBuf,
}

/// Ein `fix`-Text nennt eine API, sobald ein Bezeichner (auch `Typ.member`)
/// ohne Leerzeichen vor einer Klammer steht (`Path.Combine(`) oder Code in
/// Backticks steht. Prosa wie "warten (Signal, …)" ist kein Aufruf.
fn names_api(fix: &str) -> bool {
    let call = Regex::new(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\(").expect("valid");
    fix.contains('`') || call.is_match(fix)
}

pub fn parse_message(text: &str, groups: usize) -> Result<Vec<Piece>, String> {
    let mut out = Vec::new();
    let mut lit = String::new();
    let chars: Vec<char> = text.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if (c == '{' || c == '}') && chars.get(i + 1) == Some(&c) {
            lit.push(c);
            i += 2;
            continue;
        }
        if c == '}' {
            return Err("einzelnes '}' in message (als '}}' schreiben)".into());
        }
        if c != '{' {
            lit.push(c);
            i += 1;
            continue;
        }
        let close = (i..chars.len()).find(|&k| chars[k] == '}').ok_or("'{' ohne '}' in message")?;
        let inner: String = chars[i + 1..close].iter().collect();
        let (idx, limit) = match inner.split_once(':') {
            Some((a, b)) => (a, Some(b.parse::<usize>().map_err(|_| format!("Kürzung {{{inner}}} ist keine Zahl"))?)),
            None => (inner.as_str(), None),
        };
        let index: usize = idx.parse().map_err(|_| format!("Platzhalter {{{inner}}}: nur Gruppennummern erlaubt"))?;
        if index > groups {
            return Err(format!("Platzhalter {{{inner}}}: das Muster hat nur {groups} Gruppe(n)"));
        }
        if !lit.is_empty() {
            out.push(Piece::Text(std::mem::take(&mut lit)));
        }
        out.push(Piece::Group { index, limit });
        i = close + 1;
    }
    if !lit.is_empty() {
        out.push(Piece::Text(lit));
    }
    Ok(out)
}

fn compile(what: &str, pattern: &str) -> Result<Regex, String> {
    Regex::new(pattern).map_err(|e| {
        format!("{what} ist kein linearzeitiges Muster (regex-Crate; Lookaround und Rückverweise \
                 sind nicht erlaubt): {e}")
    })
}

pub fn parse_rule(text: &str, source: &Path, known_platforms: &HashSet<String>) -> Result<Rule, String> {
    let raw: RawRule = toml::from_str(text).map_err(|e| format!("kein gültiges Regelformat: {e}"))?;
    if raw.format != RULE_FORMAT {
        return Err(format!("format muss {RULE_FORMAT:?} sein, ist {:?}", raw.format));
    }
    let id_ok = Regex::new(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$").expect("valid").is_match(&raw.id);
    if !id_ok {
        return Err(format!("id {:?} hat nicht die Form namespace.name", raw.id));
    }
    if let Some(stem) = source.file_stem().and_then(|s| s.to_str()) {
        if stem != raw.id {
            return Err(format!("Dateiname {stem:?} muss der id {:?} entsprechen", raw.id));
        }
    }
    if !known_platforms.contains(&raw.platform) {
        return Err(format!("platform {:?} steht nicht in platforms.toml", raw.platform));
    }
    if let Some(l) = &raw.lifecycle {
        if !LIFECYCLES.contains(&l.as_str()) {
            return Err(format!("lifecycle muss eine von {LIFECYCLES:?} sein"));
        }
    }
    if raw.references.iter().any(|r| !(r.starts_with("https://") || r.starts_with("http://"))) {
        return Err("references: nur http(s)-URLs".into());
    }
    if !SEVERITIES.contains(&raw.severity.as_str()) {
        return Err(format!("severity muss eine von {SEVERITIES:?} sein"));
    }
    if raw.scope.extensions.is_empty() || raw.scope.extensions.iter().any(|e| !e.starts_with('.') || e.to_lowercase() != *e) {
        return Err("scope.extensions: nicht leer, jede Endung kleingeschrieben mit Punkt".into());
    }
    if raw.title.trim().is_empty() || raw.scope.unit_label.trim().is_empty() || raw.match_.message.trim().is_empty() {
        return Err("title, scope.unit_label und match.message dürfen nicht leer sein".into());
    }
    let pattern = compile("match.pattern", &raw.match_.pattern)?;
    if pattern.is_match("") {
        return Err("match.pattern passt auf den leeren Text — jede Datei wäre ein Befund".into());
    }
    // Der Vorfilter läuft mit `(?m)` über die ganze Datei; `\A`/`\z` hießen
    // dort Dateigrenze, im Einzellauf Zeilengrenze — er würde Treffer verlieren.
    if raw.match_.per_line && (raw.match_.pattern.contains("\\A") || raw.match_.pattern.contains("\\z")) {
        return Err("match.pattern: mit per_line = true Zeilengrenzen als ^ und $ schreiben, nicht \\A/\\z".into());
    }
    let groups = pattern.captures_len() - 1;
    let message = parse_message(&raw.match_.message, groups)?;
    let mut exclude = Vec::new();
    for ex in &raw.match_.exclude {
        let on = match (ex.on.as_str(), ex.group) {
            ("match", g) if g <= groups => ExcludeOn::Group(g),
            ("match", g) => return Err(format!("match.exclude: group {g}, das Muster hat nur {groups}")),
            ("line", 0) => ExcludeOn::Line,
            ("path", 0) => ExcludeOn::Path,
            (other, _) => return Err(format!("match.exclude: on = {other:?} (match|line|path; group nur bei match)")),
        };
        exclude.push(Exclude { on, pattern: compile("match.exclude.pattern", &ex.pattern)? });
    }
    if let Some(fix) = &raw.match_.fix {
        if names_api(fix) && raw.references.is_empty() {
            return Err("match.fix nennt eine API, aber references ist leer — \
                        ein Fix-Vorschlag ohne Quelle kann eine erfundene API empfehlen".into());
        }
    }
    let mut directions = HashSet::new();
    for fx in &raw.fixtures {
        if !EXPECTS.contains(&fx.expect.as_str()) {
            return Err(format!("fixture {:?}: expect muss eine von {EXPECTS:?} sein", fx.name));
        }
        if fx.files.keys().any(|k| k.starts_with('/') || k.split('/').any(|s| s == ".." || s.is_empty())) {
            return Err(format!("fixture {:?}: Dateipfad verlässt das Fixture", fx.name));
        }
        match (fx.expect_findings, fx.expect.as_str()) {
            (Some(0), "fail") | (Some(1..), "pass" | "unmeasured" | "error") => {
                return Err(format!("fixture {:?}: expect_findings widerspricht expect", fx.name));
            }
            _ => {}
        }
        directions.insert(fx.expect.as_str());
    }
    if !(directions.contains("fail") && directions.contains("pass")) {
        return Err("fixtures brauchen mindestens einen Fall expect=\"fail\" und einen expect=\"pass\" — \
                    ein Gate, das nie rot war, prüft nichts".into());
    }
    let unit_label = raw.scope.unit_label.clone();
    Ok(Rule {
        no_files_reason: raw.scope.no_files_reason.clone()
            .unwrap_or_else(|| format!("Null {unit_label} geprüft — es gab nichts zu messen.")),
        id: raw.id,
        title: raw.title,
        platform: raw.platform,
        severity: raw.severity,
        guideline: raw.match_.guideline.clone().unwrap_or(raw.guideline),
        extensions: raw.scope.extensions,
        unit_label,
        skip_comments: raw.scope.skip_comments,
        per_line: raw.match_.per_line,
        include_rule_files: raw.scope.include_rule_files,
        require_text: raw.scope.require_text,
        pattern,
        exclude,
        message,
        fix: raw.match_.fix,
        fixtures: raw.fixtures,
        source: source.to_path_buf(),
    })
}

/// Alle `*.toml` unter `dir` (rekursiv, sortiert); Fehler je Datei gesammelt,
/// damit ein kaputter Regelsatz alle Befunde auf einmal nennt.
pub fn load_rules(dir: &Path, known_platforms: &HashSet<String>) -> Result<Vec<Rule>, Vec<String>> {
    fn collect(dir: &Path, out: &mut Vec<PathBuf>) -> std::io::Result<()> {
        let mut entries: Vec<_> = std::fs::read_dir(dir)?.collect::<Result<_, _>>()?;
        entries.sort_by_key(|e| e.file_name());
        for e in entries {
            let p = e.path();
            if p.is_dir() {
                collect(&p, out)?;
            } else if p.extension().is_some_and(|x| x == "toml") {
                out.push(p);
            }
        }
        Ok(())
    }
    let mut files = Vec::new();
    if let Err(e) = collect(dir, &mut files) {
        return Err(vec![format!("{}: {e}", dir.display())]);
    }
    let mut rules = Vec::new();
    let mut errors = Vec::new();
    let mut seen = HashSet::new();
    for f in files {
        let text = match std::fs::read_to_string(&f) {
            Ok(t) => t,
            Err(e) => {
                errors.push(format!("{}: {e}", f.display()));
                continue;
            }
        };
        match parse_rule(&text, &f, known_platforms) {
            Ok(r) => {
                if !seen.insert(r.id.clone()) {
                    errors.push(format!("{}: doppelte id {}", f.display(), r.id));
                }
                rules.push(r);
            }
            Err(e) => errors.push(format!("{}: {e}", f.display())),
        }
    }
    if errors.is_empty() {
        Ok(rules)
    } else {
        Err(errors)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn platforms() -> HashSet<String> {
        ["universal", "godot"].iter().map(|s| s.to_string()).collect()
    }

    pub const GOOD: &str = r#"
format = "ruttla-rule/0"
id = "godot.example_rule"
title = "Beispiel"
platform = "godot"
severity = "warning"
[scope]
extensions = [".gd"]
unit_label = "GDScript-Dateien"
[match]
pattern = 'wait\((\d+)\)'
message = "Wartet {1}s."
fix = "Auf einen Zustand warten."
[[fixtures]]
name = "rot"
expect = "fail"
files = { "a.gd" = "wait(3)\n" }
[[fixtures]]
name = "grün"
expect = "pass"
files = { "a.gd" = "ok\n" }
"#;

    fn parse(text: &str) -> Result<Rule, String> {
        parse_rule(text, Path::new("godot.example_rule.toml"), &platforms())
    }

    #[test]
    fn good_rule_loads() {
        let r = parse(GOOD).expect("loads");
        assert_eq!(r.message, vec![Piece::Text("Wartet ".into()), Piece::Group { index: 1, limit: None }, Piece::Text("s.".into())]);
    }

    #[test]
    fn lookaround_is_rejected() {
        let err = parse(&GOOD.replace(r"wait\((\d+)\)", r"(?<!x)wait\((\d+)\)")).unwrap_err();
        assert!(err.contains("linearzeitig"), "{err}");
    }

    #[test]
    fn backreference_is_rejected() {
        let err = parse(&GOOD.replace(r"wait\((\d+)\)", r"(a)\1wait\((\d+)\)")).unwrap_err();
        assert!(err.contains("linearzeitig"), "{err}");
    }

    #[test]
    fn missing_direction_is_rejected() {
        let only_red = GOOD.split("[[fixtures]]\nname = \"grün\"").next().unwrap();
        assert!(parse(only_red).unwrap_err().contains("nie rot"));
        let no_fixtures = GOOD.split("[[fixtures]]").next().unwrap();
        assert!(parse(no_fixtures).is_err());
    }

    #[test]
    fn placeholder_beyond_groups_is_rejected() {
        assert!(parse(&GOOD.replace("Wartet {1}s.", "Wartet {2}s.")).unwrap_err().contains("Gruppe"));
    }

    #[test]
    fn prose_parenthesis_is_not_an_api() {
        assert!(!names_api("Auf den Zustand warten (Signal, Bedingung)."));
        assert!(!names_api("In die Endpunktliste (config.ts) legen."));
        assert!(names_api("get_node(\"x\") vermeiden"));
        assert!(names_api("`Font.custom` nutzen"));
    }

    #[test]
    fn api_in_fix_needs_reference() {
        let api = GOOD.replace("Auf einen Zustand warten.", "Path.Combine(a, b) benutzen.");
        assert!(parse(&api).unwrap_err().contains("references"));
        let sourced = api.replace("severity = \"warning\"", "severity = \"warning\"\nreferences = [\"https://learn.microsoft.com/dotnet/api/system.io.path.combine\"]");
        assert!(parse(&sourced).is_ok());
    }

    #[test]
    fn unknown_keys_and_platforms_are_rejected() {
        assert!(parse(&GOOD.replace("severity = \"warning\"", "severity = \"warning\"\ncolour = 1")).is_err());
        assert!(parse(&GOOD.replace("platform = \"godot\"", "platform = \"cobol\"")).is_err());
        assert!(parse_rule(GOOD, Path::new("other.toml"), &platforms()).is_err());
    }

    #[test]
    fn per_line_rejects_text_anchors() {
        let per_line = GOOD.replace("[match]\n", "[match]\nper_line = true\n");
        assert!(parse(&per_line).expect("loads").per_line);
        let err = parse(&per_line.replace(r"wait\((\d+)\)", r"\Await\((\d+)\)")).unwrap_err();
        assert!(err.contains("per_line"), "{err}");
    }

    #[test]
    fn expect_findings_must_agree_with_expect() {
        assert!(parse(&GOOD.replace("expect = \"fail\"", "expect = \"fail\"\nexpect_findings = 1")).is_ok());
        assert!(parse(&GOOD.replace("expect = \"fail\"", "expect = \"fail\"\nexpect_findings = 0")).is_err());
        assert!(parse(&GOOD.replace("expect = \"pass\"", "expect = \"pass\"\nexpect_findings = 2")).is_err());
    }
}
