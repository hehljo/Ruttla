//! Dateitext genau so, wie Python ihn liest: `open(path, "r",
//! encoding="utf-8", errors="replace")` — also mit Universal Newlines.
//! Ohne die Umsetzung von `\r\n`/`\r` stimmen weder `^` im Mehrzeilenmodus
//! noch die Zeilennummern mit der Python-Seite überein.

use std::path::Path;
use std::sync::OnceLock;

use regex::Regex;

pub const RULE_DOCS_MARKER: &str = "<!-- ruttla:rule-docs -->";

pub fn read_text(path: &Path) -> std::io::Result<String> {
    let bytes = std::fs::read(path)?;
    Ok(universal_newlines(&String::from_utf8_lossy(&bytes)))
}

pub fn universal_newlines(text: &str) -> String {
    if !text.contains('\r') {
        return text.to_string();
    }
    text.replace("\r\n", "\n").replace('\r', "\n")
}

/// `discovery._SELF_DESCRIBING`: Dateien, die Prüfregeln oder Testfälle
/// definieren, verletzen die Regeln nicht — sie beschreiben sie.
pub fn is_rule_definition(text: &str) -> bool {
    static RE: OnceLock<Regex> = OnceLock::new();
    let re = RE.get_or_init(|| {
        Regex::new(&format!(
            r#"(?:\A|\n)[ \t]*(?:@register\s*\(|SelfTestCase\s*\(|def\s+test_\w+|class\s+Test\w+|describe\s*\(|it\s*\(\s*["'])|{}"#,
            regex::escape(RULE_DOCS_MARKER)
        ))
        .expect("self-describing pattern is valid")
    });
    re.is_match(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newlines_follow_python_text_mode() {
        assert_eq!(universal_newlines("a\r\nb\rc\n"), "a\nb\nc\n");
    }

    #[test]
    fn rule_definitions_are_recognised_by_property() {
        assert!(is_rule_definition("x\n  def test_foo():"));
        assert!(is_rule_definition("SelfTestCase(name=1)"));
        assert!(is_rule_definition("<!-- ruttla:rule-docs -->"));
        assert!(!is_rule_definition("x = 'def test_foo'"));
    }
}
