//! `fnmatch.fnmatch` mit derselben Semantik wie CPython (3.11–3.14).
//!
//! Python übersetzt ein Glob in einen regulären Ausdruck (`fnmatch._translate`);
//! dieselbe Übersetzung steht hier, nur mit Ziel `regex`-Crate. `*` passt auch
//! über `/`, ein Backslash ist außerhalb von `[...]` ein gewöhnliches Zeichen.

use regex::Regex;

/// Ein übersetztes Muster. `None` heißt: kann nie passen (leere Menge `[]`).
#[derive(Debug)]
pub struct Glob {
    re: Option<Regex>,
}

impl Glob {
    pub fn new(pattern: &str) -> Glob {
        let pattern = normcase(pattern);
        Glob { re: translate(&pattern).map(|src| Regex::new(&src).expect("fnmatch translation is valid")) }
    }

    pub fn is_match(&self, name: &str) -> bool {
        match &self.re {
            Some(re) => re.is_match(&normcase(name)),
            None => false,
        }
    }
}

/// `os.path.normcase`: auf Windows klein und `/` → `\`, sonst unverändert.
fn normcase(s: &str) -> String {
    if cfg!(windows) {
        s.to_lowercase().replace('/', "\\")
    } else {
        s.to_string()
    }
}

fn lit(c: char) -> String {
    format!("\\x{{{:X}}}", c as u32)
}

/// Inhalt einer Python-Zeichenklasse (nach `_translate`) in Rust-Syntax.
/// Rückgabe `None` = leere Menge.
fn class(stuff: &[char]) -> Option<String> {
    // Python: '' → (?!) ; '!' → '.' ; führendes '!' → Negation.
    if stuff.is_empty() {
        return None;
    }
    if stuff == ['!'] {
        return Some("(?s:.)".to_string());
    }
    let (negate, body) = if stuff[0] == '!' { (true, &stuff[1..]) } else { (false, stuff) };
    // body: Zeichen mit '\' als Escape; unescaptes '-' zwischen zwei Elementen = Bereich.
    let mut atoms: Vec<(char, bool)> = Vec::new(); // (Zeichen, war_escaped)
    let mut i = 0;
    while i < body.len() {
        if body[i] == '\\' && i + 1 < body.len() {
            atoms.push((body[i + 1], true));
            i += 2;
        } else {
            atoms.push((body[i], false));
            i += 1;
        }
    }
    let mut out = String::new();
    let mut k = 0;
    while k < atoms.len() {
        let (c, _) = atoms[k];
        if k + 2 < atoms.len() && atoms[k + 1] == ('-', false) {
            let (d, _) = atoms[k + 2];
            out.push_str(&format!("{}-{}", lit(c), lit(d)));
            k += 3;
        } else {
            out.push_str(&lit(c));
            k += 1;
        }
    }
    Some(format!("[{}{}]", if negate { "^" } else { "" }, out))
}

/// Port von `fnmatch._translate` + Verankerung; `None` = passt nie.
pub fn translate(pat: &str) -> Option<String> {
    let p: Vec<char> = pat.chars().collect();
    let n = p.len();
    let mut res = String::from("(?s)^");
    let mut i = 0;
    while i < n {
        let c = p[i];
        i += 1;
        if c == '*' {
            // Aufeinanderfolgende Sterne zusammenfassen.
            while i < n && p[i] == '*' {
                i += 1;
            }
            res.push_str(".*");
        } else if c == '?' {
            res.push('.');
        } else if c == '[' {
            let mut j = i;
            if j < n && p[j] == '!' {
                j += 1;
            }
            if j < n && p[j] == ']' {
                j += 1;
            }
            while j < n && p[j] != ']' {
                j += 1;
            }
            if j >= n {
                res.push_str(&lit('['));
                continue;
            }
            let stuff: Vec<char> = if !p[i..j].contains(&'-') {
                escape_backslashes(&p[i..j])
            } else {
                let mut chunks: Vec<Vec<char>> = Vec::new();
                let mut start = i;
                let mut k = if p[i] == '!' { i + 2 } else { i + 1 };
                loop {
                    let found = (k..j).find(|&x| p[x] == '-');
                    match found {
                        None => break,
                        Some(pos) => {
                            chunks.push(p[start..pos].to_vec());
                            start = pos + 1;
                            k = pos + 3;
                        }
                    }
                }
                let chunk = p[start..j].to_vec();
                if !chunk.is_empty() {
                    chunks.push(chunk);
                } else {
                    chunks.last_mut().expect("at least one chunk").push('-');
                }
                // Leere Bereiche entfernen (in Python ein ungültiger RE).
                let mut k = chunks.len() - 1;
                while k > 0 {
                    let prev_last = *chunks[k - 1].last().expect("chunk");
                    let first = chunks[k][0];
                    if prev_last > first {
                        let tail: Vec<char> = chunks[k][1..].to_vec();
                        chunks[k - 1].pop();
                        chunks[k - 1].extend(tail);
                        chunks.remove(k);
                    }
                    k -= 1;
                }
                let mut joined = Vec::new();
                for (idx, s) in chunks.iter().enumerate() {
                    if idx > 0 {
                        joined.push('-');
                    }
                    for &ch in s {
                        match ch {
                            '\\' => joined.extend(['\\', '\\']),
                            '-' => joined.extend(['\\', '-']),
                            _ => joined.push(ch),
                        }
                    }
                }
                joined
            };
            i = j + 1;
            // Python escapt hier noch & ~ | und ein führendes ^ oder [; in
            // `class` wird ohnehin jedes Zeichen als \x{..} ausgegeben, und
            // negiert wird nur durch `!`.
            match class(&stuff) {
                Some(cls) => res.push_str(&cls),
                None => return None,
            }
        } else {
            res.push_str(&lit(c));
        }
    }
    res.push('$');
    Some(res)
}

fn escape_backslashes(s: &[char]) -> Vec<char> {
    let mut out = Vec::new();
    for &c in s {
        if c == '\\' {
            out.extend(['\\', '\\']);
        } else {
            out.push(c);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::Glob;

    #[test]
    fn star_crosses_slashes_like_python() {
        assert!(Glob::new("*.md").is_match("docs/a.md"));
        assert!(Glob::new("docs/*").is_match("docs/x/y.txt"));
        assert!(!Glob::new("docs/*").is_match("src/docs/x"));
    }

    #[test]
    fn brackets_and_negation() {
        assert!(Glob::new("[ab].txt").is_match("a.txt"));
        assert!(!Glob::new("[!ab].txt").is_match("a.txt"));
        assert!(Glob::new("[!ab].txt").is_match("c.txt"));
        assert!(Glob::new("x[").is_match("x["));
        assert!(Glob::new("[a-c]").is_match("b"));
        assert!(!Glob::new("[c-a]").is_match("b"));
    }
}
