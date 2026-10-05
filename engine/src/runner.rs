//! Deklarativer Regel-Runner (P11-T005): jede Datei wird einmal gelesen und
//! vorverarbeitet, alle Regeln ihrer Endung laufen in einem Durchgang
//! (`RegexSet` als Vorfilter), Dateien parallel. Das Ergebnis hängt nicht von
//! der Thread-Zahl ab: die Befunde werden in Inventar-Reihenfolge gemischt.

use std::borrow::Cow;
use std::collections::HashMap;
use std::path::Path;

use regex::RegexSet;
use serde::Serialize;

use crate::detect::{claimed_files, find_roots, Manifest};
use crate::inventory::{inventory, InputError, InventoryConfig, SourceFile};
use crate::pytext::{is_line_break, snippet, splitlines, strip};
use crate::rules::{ExcludeOn, Piece, Rule};
use crate::strip::strip_comments;
use crate::text::{is_rule_definition, read_text};

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct Finding {
    pub check_id: String,
    pub severity: String,
    pub message: String,
    pub file: String,
    pub line: usize,
    pub evidence: String,
    pub fix: Option<String>,
    pub guideline: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct RuleResult {
    pub check_id: String,
    pub title: String,
    pub status: String,
    pub platform: String,
    pub reason: Option<String>,
    pub units_examined: usize,
    pub unit_label: String,
    pub findings: Vec<Finding>,
}

#[derive(Clone, Copy, PartialEq)]
pub enum View {
    /// Wie `run_checks`: Dateien einer fremden Projektwurzel sind unsichtbar.
    Scoped,
    /// Wie `--self-test`: alle Dateien.
    Unscoped,
}

/// Eine Datei, einmal gelesen; der Kommentar-freie Text wird bei Bedarf gebaut.
struct Prepared {
    text: String,
    stripped: Option<String>,
    rule_definition: bool,
}

fn render(pieces: &[Piece], caps: &regex::Captures) -> String {
    let mut out = String::new();
    for p in pieces {
        match p {
            Piece::Text(t) => out.push_str(t),
            Piece::Group { index, limit } => {
                // Python formatiert eine nicht beteiligte Gruppe als "None".
                let g = caps.get(*index).map(|m| m.as_str()).unwrap_or("None");
                match limit {
                    Some(n) => out.push_str(&snippet(g, *n)),
                    None => out.push_str(g),
                }
            }
        }
    }
    out
}

fn match_file(rule: &Rule, file: &SourceFile, prep: &Prepared) -> Vec<Finding> {
    let haystack = if rule.skip_comments { prep.stripped.as_deref().unwrap_or(&prep.text) } else { &prep.text };
    let lines = splitlines(&prep.text);
    let raw_line = |line_no: usize| lines.get(line_no - 1).map(|l| strip(l)).unwrap_or("");
    let mut out = Vec::new();
    if rule.per_line {
        // Wie `pattern.search(zeile)` je `splitlines`-Zeile: kein Treffer über
        // einen Trenner hinweg, höchstens einer je Zeile, gezählt an allen
        // Trennern (auch \f, \v, U+2028 …), nicht nur an \n.
        for (idx, line) in splitlines(haystack).into_iter().enumerate() {
            if let Some(caps) = rule.pattern.captures(line) {
                out.extend(finding(rule, file, &caps, idx + 1, raw_line(idx + 1)));
            }
        }
        return out;
    }
    let mut newlines = 0usize;
    let mut counted_to = 0usize;
    for caps in rule.pattern.captures_iter(haystack) {
        let m = caps.get(0).expect("group 0");
        newlines += haystack.as_bytes()[counted_to..m.start()].iter().filter(|&&b| b == b'\n').count();
        counted_to = m.start();
        let line_no = newlines + 1;
        out.extend(finding(rule, file, &caps, line_no, raw_line(line_no)));
    }
    out
}

/// Ein Treffer als Befund, oder None, wenn ein `exclude` ihn verwirft.
fn finding(rule: &Rule, file: &SourceFile, caps: &regex::Captures, line_no: usize, raw: &str) -> Option<Finding> {
    let excluded = rule.exclude.iter().any(|ex| match ex.on {
        ExcludeOn::Group(g) => caps.get(g).is_some_and(|c| ex.pattern.is_match(c.as_str())),
        ExcludeOn::Line => ex.pattern.is_match(raw),
        ExcludeOn::Path => ex.pattern.is_match(&file.rel),
    });
    if excluded {
        return None;
    }
    Some(Finding {
        check_id: rule.id.clone(),
        severity: rule.severity.clone(),
        message: render(&rule.message, caps),
        file: file.rel.clone(),
        line: line_no,
        evidence: snippet(raw, 120),
        fix: rule.fix.clone(),
        guideline: (!rule.guideline.is_empty()).then(|| rule.guideline.clone()),
    })
}

/// Vorfilter-Sicht für Zeilenregeln: jeder `splitlines`-Trenner wird `\n`,
/// damit `(?m)^`/`$` an denselben Stellen greifen wie im Lauf je Zeile. Der
/// Vorfilter darf zu viel melden (`\s` über einen Umbruch), nie zu wenig.
fn line_view(text: &str) -> Cow<'_, str> {
    if text.contains(|c: char| is_line_break(c) && c != '\n') {
        Cow::Owned(text.chars().map(|c| if is_line_break(c) { '\n' } else { c }).collect())
    } else {
        Cow::Borrowed(text)
    }
}

/// Ergebnis je Datei und Regelindex: None = Datei nicht im Prüfbereich der Regel.
type FileOutcome = Vec<Option<Vec<Finding>>>;

fn in_view(rule: &Rule, view: View, file: &SourceFile, owners: &HashMap<String, String>) -> bool {
    if !rule.extensions.contains(&file.ext) {
        return false;
    }
    if view == View::Unscoped || rule.platform == "universal" {
        return true;
    }
    owners.get(&file.rel).map_or(true, |o| *o == rule.platform)
}

fn process_file(
    rules: &[Rule],
    sets: &[(RegexSet, Vec<usize>, bool, bool)],
    view: View,
    owners: &HashMap<String, String>,
    file: &SourceFile,
) -> Result<FileOutcome, InputError> {
    let mut outcome: FileOutcome = vec![None; rules.len()];
    let wanted: Vec<usize> = (0..rules.len()).filter(|&i| in_view(&rules[i], view, file, owners)).collect();
    if wanted.is_empty() {
        return Ok(outcome);
    }
    let text = read_text(&file.path).map_err(|e| InputError {
        kind: "unreadable_file".into(),
        path: file.rel.clone(),
        message: format!("Eingabedatei nicht lesbar: {}: {e}", file.rel),
    })?;
    let needs_strip = wanted.iter().any(|&i| rules[i].skip_comments);
    let prep = Prepared {
        stripped: needs_strip.then(|| strip_comments(&text, &file.ext)),
        rule_definition: is_rule_definition(&text),
        text,
    };
    // Ein Durchgang je Vorverarbeitung: das RegexSet sagt, welche Regeln
    // überhaupt treffen; nur für diese laufen die Einzelmuster.
    let mut hit = vec![false; rules.len()];
    for (set, members, stripped, per_line) in sets {
        if !members.iter().any(|i| wanted.contains(i)) {
            continue;
        }
        let hay = if *stripped { prep.stripped.as_deref().unwrap_or(&prep.text) } else { &prep.text };
        let hay = if *per_line { line_view(hay) } else { Cow::Borrowed(hay) };
        for k in set.matches(&hay).iter() {
            hit[members[k]] = true;
        }
    }
    for i in wanted {
        let rule = &rules[i];
        if prep.rule_definition && !rule.include_rule_files {
            continue;
        }
        if let Some(needle) = &rule.require_text {
            if !prep.text.contains(needle.as_str()) {
                continue;
            }
        }
        outcome[i] = Some(if hit[i] { match_file(rule, file, &prep) } else { Vec::new() });
    }
    Ok(outcome)
}

pub fn run_rules(
    rules: &[Rule],
    files: &[SourceFile],
    owners: &HashMap<String, String>,
    view: View,
    threads: usize,
) -> Result<Vec<RuleResult>, InputError> {
    let mut sets = Vec::new();
    for (stripped, per_line) in [(true, false), (false, false), (true, true), (false, true)] {
        let members: Vec<usize> = (0..rules.len())
            .filter(|&i| rules[i].skip_comments == stripped && rules[i].per_line == per_line)
            .collect();
        if !members.is_empty() {
            let prefix = if per_line { "(?m)" } else { "" };
            let set = RegexSet::new(members.iter().map(|&i| format!("{prefix}{}", rules[i].pattern.as_str())))
                .expect("patterns compiled before");
            sets.push((set, members, stripped, per_line));
        }
    }
    let threads = threads.max(1).min(files.len().max(1));
    let chunk = files.len().div_ceil(threads).max(1);
    let per_file: Vec<Result<FileOutcome, InputError>> = std::thread::scope(|s| {
        let handles: Vec<_> = files
            .chunks(chunk)
            .map(|part| {
                let sets = &sets;
                s.spawn(move || part.iter().map(|f| process_file(rules, sets, view, owners, f)).collect::<Vec<_>>())
            })
            .collect();
        handles.into_iter().flat_map(|h| h.join().expect("worker thread")).collect()
    });
    let mut units = vec![0usize; rules.len()];
    let mut findings: Vec<Vec<Finding>> = vec![Vec::new(); rules.len()];
    for outcome in per_file {
        for (i, o) in outcome?.into_iter().enumerate() {
            if let Some(f) = o {
                units[i] += 1;
                findings[i].extend(f);
            }
        }
    }
    Ok(rules
        .iter()
        .enumerate()
        .map(|(i, rule)| {
            let (status, reason) = if units[i] == 0 {
                ("unmeasured", Some(rule.no_files_reason.clone()))
            } else if findings[i].is_empty() {
                ("pass", None)
            } else {
                ("fail", None)
            };
            RuleResult {
                check_id: rule.id.clone(),
                title: rule.title.clone(),
                status: status.into(),
                platform: rule.platform.clone(),
                reason,
                units_examined: units[i],
                unit_label: rule.unit_label.clone(),
                findings: std::mem::take(&mut findings[i]),
            }
        })
        .collect())
}

/// Komplettlauf auf einem Verzeichnis: Inventar, Ansprüche, Regeln.
pub fn scan(
    manifest: &Manifest,
    root: &Path,
    cfg: &InventoryConfig,
    rules: &[Rule],
    view: View,
    threads: usize,
) -> Result<Vec<RuleResult>, InputError> {
    let (files, _) = inventory(root, cfg)?;
    let owners = if view == View::Scoped {
        claimed_files(manifest, &files, &find_roots(manifest, &files))
    } else {
        HashMap::new()
    };
    run_rules(rules, &files, &owners, view, threads)
}
