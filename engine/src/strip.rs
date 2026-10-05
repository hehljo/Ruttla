//! Port von `discovery.strip_comments`: Kommentarinhalt wird durch
//! Leerzeichen ersetzt, Zeilenumbrüche bleiben — Zeilennummern stimmen also.
//! Gearbeitet wird wie in Python auf Zeichen, nicht auf Bytes.

fn line_marker(ext: &str) -> Option<&'static str> {
    Some(match ext {
        ".swift" | ".ts" | ".tsx" | ".js" | ".jsx" | ".mjs" | ".cjs" | ".cs" | ".c" | ".h" | ".cpp"
        | ".hpp" | ".java" | ".kt" | ".go" | ".rs" => "//",
        ".gd" | ".py" | ".ps1" | ".sh" | ".rb" | ".yaml" | ".yml" | ".toml" => "#",
        _ => return None,
    })
}

fn block_markers(ext: &str) -> &'static [(&'static str, &'static str)] {
    match ext {
        ".swift" | ".ts" | ".tsx" | ".js" | ".jsx" | ".mjs" | ".cs" | ".cpp" | ".java" | ".kt"
        | ".go" | ".rs" | ".css" | ".scss" => &[("/*", "*/")],
        ".html" | ".xml" | ".xaml" => &[("<!--", "-->")],
        ".vue" | ".svelte" => &[("<!--", "-->"), ("/*", "*/")],
        ".ps1" => &[("<#", "#>")],
        _ => &[],
    }
}

fn starts_with(text: &[char], i: usize, pat: &str) -> bool {
    let mut k = i;
    for p in pat.chars() {
        if k >= text.len() || text[k] != p {
            return false;
        }
        k += 1;
    }
    true
}

fn find(text: &[char], pat: &str, from: usize) -> Option<usize> {
    (from..text.len()).find(|&k| starts_with(text, k, pat))
}

pub fn strip_comments(text: &str, ext: &str) -> String {
    let line = line_marker(ext);
    let blocks = block_markers(ext);
    if line.is_none() && blocks.is_empty() {
        return text.to_string();
    }
    let src: Vec<char> = text.chars().collect();
    let mut out = src.clone();
    let n = src.len();
    let strings_allowed = !matches!(ext, ".html" | ".xml" | ".xaml");
    let mut in_string: Option<char> = None;
    let mut i = 0;
    'outer: while i < n {
        let ch = src[i];
        if let Some(q) = in_string {
            if ch == '\\' {
                i += 2;
                continue;
            }
            if ch == q {
                i += 1;
                in_string = None;
                continue;
            }
            i += 1;
            continue;
        }
        if matches!(ch, '"' | '\'' | '`') && strings_allowed {
            in_string = Some(ch);
            i += 1;
            continue;
        }
        for (start, end) in blocks {
            if starts_with(&src, i, start) {
                let from = i + start.chars().count();
                let stop = find(&src, end, from).map(|s| s + end.chars().count()).unwrap_or(n);
                for item in out.iter_mut().take(stop).skip(i) {
                    if *item != '\n' {
                        *item = ' ';
                    }
                }
                i = stop;
                continue 'outer;
            }
        }
        if let Some(marker) = line {
            if starts_with(&src, i, marker) {
                let stop = (i..n).find(|&k| src[k] == '\n').unwrap_or(n);
                for item in out.iter_mut().take(stop).skip(i) {
                    *item = ' ';
                }
                i = stop;
                continue;
            }
        }
        i += 1;
    }
    out.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::strip_comments;

    #[test]
    fn keeps_lines_and_strings() {
        let src = "let u = \"http://x\" // c\n/* a\nb */ x";
        assert_eq!(strip_comments(src, ".swift"), "let u = \"http://x\"     \n    \n     x");
    }

    #[test]
    fn unknown_extension_is_untouched() {
        assert_eq!(strip_comments("# x", ".md"), "# x");
    }

    #[test]
    fn hash_comments_and_escapes() {
        assert_eq!(strip_comments("a = 'x\\'#' # c", ".py"), "a = 'x\\'#'    ");
    }
}
