//! Python-Textsemantik, die Befunde sichtbar beeinflusst: `str.splitlines`,
//! `str.strip`, `str.split()` und `registry.snippet`. Eine Abweichung hier
//! ändert Zeilen-Evidenz und Meldungen — das Differenz-Gate würde sie melden.

/// `str.isspace` in CPython: Unicode-White_Space plus die Trenner \x1c–\x1f.
pub fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Zeilentrenner von `str.splitlines`.
pub fn is_line_break(c: char) -> bool {
    matches!(c, '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}')
}

/// `str.splitlines()` (ohne keepends).
pub fn splitlines(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut iter = text.char_indices().peekable();
    while let Some((i, c)) = iter.next() {
        if !is_line_break(c) {
            continue;
        }
        out.push(&text[start..i]);
        let mut end = i + c.len_utf8();
        if c == '\r' {
            if let Some(&(j, '\n')) = iter.peek() {
                iter.next();
                end = j + 1;
            }
        }
        start = end;
    }
    if start < text.len() {
        out.push(&text[start..]);
    }
    out
}

pub fn strip(s: &str) -> &str {
    s.trim_matches(is_py_space)
}

/// `registry.snippet`: Leerraum zusammenfassen, bei `limit` Zeichen kürzen.
pub fn snippet(text: &str, limit: usize) -> String {
    let one = text.split(is_py_space).filter(|w| !w.is_empty()).collect::<Vec<_>>().join(" ");
    if one.chars().count() <= limit {
        return one;
    }
    let mut cut: String = one.chars().take(limit.saturating_sub(1)).collect();
    cut.push('…');
    cut
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_matches_python() {
        assert_eq!(splitlines("a\nb\r\nc\rd\x0ce\u{2028}f"), vec!["a", "b", "c", "d", "e", "f"]);
        assert_eq!(splitlines("a\n"), vec!["a"]);
        assert_eq!(splitlines("a\n\nb"), vec!["a", "", "b"]);
        assert!(splitlines("").is_empty());
    }

    #[test]
    fn snippet_collapses_and_cuts() {
        assert_eq!(snippet("  a \t b\n c ", 120), "a b c");
        assert_eq!(snippet("abcdef", 4), "abc…");
        assert_eq!(snippet("äöüß", 4), "äöüß");
        assert_eq!(strip("\u{1f} x \u{a0}"), "x");
    }
}
