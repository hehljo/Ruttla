//! `os.path.realpath(strict=False)` wie CPython auf POSIX.
//!
//! `std::fs::canonicalize` scheitert an Links ohne Ziel; Python löst dagegen
//! so weit auf wie möglich und hängt den Rest unverändert an. Genau davon
//! hängt ab, ob ein kaputter Link nach außen ein Abbruch ist (P10-T001).

#[cfg(unix)]
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[cfg(unix)]
pub fn realpath(path: &Path) -> PathBuf {
    use std::ffi::OsStr;
    use std::os::unix::ffi::OsStrExt;

    fn join(a: &[u8], b: &[u8]) -> Vec<u8> {
        if b.first() == Some(&b'/') {
            return b.to_vec();
        }
        if a.is_empty() || a.ends_with(b"/") {
            [a, b].concat()
        } else {
            [a, b"/", b].concat()
        }
    }

    fn split(p: &[u8]) -> (Vec<u8>, Vec<u8>) {
        let i = p.iter().rposition(|&c| c == b'/').map(|x| x + 1).unwrap_or(0);
        let (head, tail) = (&p[..i], &p[i..]);
        let mut h = head.to_vec();
        if !h.is_empty() && h.iter().any(|&c| c != b'/') {
            while h.ends_with(b"/") {
                h.pop();
            }
        }
        (h, tail.to_vec())
    }

    fn walk(
        mut path: Vec<u8>,
        rest: &[u8],
        seen: &mut HashMap<Vec<u8>, Option<Vec<u8>>>,
    ) -> (Vec<u8>, bool) {
        let mut rest: Vec<u8> = rest.to_vec();
        if rest.first() == Some(&b'/') {
            rest.remove(0);
            path = b"/".to_vec();
        }
        while !rest.is_empty() {
            let (name, tail) = match rest.iter().position(|&c| c == b'/') {
                Some(i) => (rest[..i].to_vec(), rest[i + 1..].to_vec()),
                None => (rest.clone(), Vec::new()),
            };
            rest = tail;
            if name.is_empty() || name == b"." {
                continue;
            }
            if name == b".." {
                if !path.is_empty() {
                    let (h, t) = split(&path);
                    path = h;
                    if t == b".." {
                        path = join(&join(&path, b".."), b"..");
                    }
                } else {
                    path = b"..".to_vec();
                }
                continue;
            }
            let newpath = join(&path, &name);
            let is_link = std::fs::symlink_metadata(OsStr::from_bytes(&newpath))
                .map(|m| m.file_type().is_symlink())
                .unwrap_or(false);
            if !is_link {
                path = newpath;
                continue;
            }
            if let Some(cached) = seen.get(&newpath) {
                match cached {
                    Some(resolved) => {
                        path = resolved.clone();
                        continue;
                    }
                    // Schleife: aufgelöster Teil + Rest unverändert.
                    None => return (join(&newpath, &rest), false),
                }
            }
            seen.insert(newpath.clone(), None);
            let target = match std::fs::read_link(OsStr::from_bytes(&newpath)) {
                Ok(t) => t.as_os_str().as_bytes().to_vec(),
                Err(_) => {
                    path = newpath;
                    continue;
                }
            };
            let (resolved, ok) = walk(path, &target, seen);
            if !ok {
                return (join(&resolved, &rest), false);
            }
            seen.insert(newpath, Some(resolved.clone()));
            path = resolved;
        }
        (path, true)
    }

    let raw = path.as_os_str().as_bytes();
    let (out, _) = walk(Vec::new(), raw, &mut HashMap::new());
    PathBuf::from(OsStr::from_bytes(&out))
}

#[cfg(not(unix))]
pub fn realpath(path: &Path) -> PathBuf {
    // Windows wie die Python-Seite (discovery.inventory): ntpath.realpath
    // folgt einem Link ohne Ziel selbst (`_readlink_deep`, Zyklus endet am
    // ersten Wiederkehrer); das Verzeichnis des Ergebnisses wird danach
    // aufgelöst, damit Kurz- und Langnamen (RUNNER~1) gleich vergleichen.
    if let Ok(p) = std::fs::canonicalize(path) {
        return verbatim_stripped(p);
    }
    let mut cur = path.to_path_buf();
    let mut seen = std::collections::HashSet::new();
    while seen.insert(cur.to_string_lossy().to_lowercase()) {
        let Ok(target) = std::fs::read_link(&cur) else { break };
        cur = if target.is_absolute() { target } else { cur.parent().map(|d| d.join(&target)).unwrap_or(target) };
    }
    canonical_prefix(&cur)
}

/// Längsten existierenden Vorfahren auflösen, den Rest unverändert anhängen.
#[cfg(not(unix))]
fn canonical_prefix(path: &Path) -> PathBuf {
    let mut tail = Vec::new();
    let mut head = path.to_path_buf();
    loop {
        if let Ok(p) = std::fs::canonicalize(&head) {
            let mut out = verbatim_stripped(p);
            for part in tail.iter().rev() {
                out.push(part);
            }
            return out;
        }
        match (head.file_name().map(|n| n.to_os_string()), head.parent().map(Path::to_path_buf)) {
            (Some(name), Some(parent)) => {
                tail.push(name);
                head = parent;
            }
            _ => return path.to_path_buf(),
        }
    }
}

#[cfg(not(unix))]
fn verbatim_stripped(p: PathBuf) -> PathBuf {
    let s = p.to_string_lossy();
    PathBuf::from(s.strip_prefix(r"\\?\").unwrap_or(&s).to_string())
}

#[cfg(all(test, unix))]
mod tests {
    use super::realpath;
    use std::path::Path;

    #[test]
    fn dangling_link_resolves_as_far_as_possible() {
        let dir = std::env::temp_dir().join(format!("ruttla-rp-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let link = dir.join("gone");
        let _ = std::fs::remove_file(&link);
        std::os::unix::fs::symlink("missing/target.txt", &link).unwrap();
        let real = realpath(&std::fs::canonicalize(&dir).unwrap().join("gone"));
        assert!(real.ends_with(Path::new("missing/target.txt")), "{real:?}");
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn loop_returns_unresolved_rest() {
        let dir = std::env::temp_dir().join(format!("ruttla-rp-loop-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let a = dir.join("a");
        let b = dir.join("b");
        let _ = std::fs::remove_file(&a);
        let _ = std::fs::remove_file(&b);
        std::os::unix::fs::symlink("b", &a).unwrap();
        std::os::unix::fs::symlink("a", &b).unwrap();
        let base = std::fs::canonicalize(&dir).unwrap();
        let real = realpath(&base.join("a"));
        assert!(real.starts_with(&base), "{real:?}");
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
