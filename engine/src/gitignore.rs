//! Git's own ignore/index semantics, matching ruttla/gitignore.py.
use std::collections::HashSet;
use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

pub struct GitIgnore {
    pub status: String,
    pub files: HashSet<String>,
    pub dirs: HashSet<String>,
}

// No target hooks (including fsmonitor), inherited repository redirects,
// network, prompts or index writes. Drain stdout while waiting, with the
// same 30 s bound as Python; stderr never enters a report.
fn git(root: &Path, args: &[&str]) -> Result<(bool, Vec<u8>), &'static str> {
    let mut cmd = Command::new("git");
    cmd.args(["-c", "core.fsmonitor=false", "-C"]).arg(root).args(args)
        .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
    for (key, _) in std::env::vars_os() {
        if key.to_string_lossy().starts_with("GIT_") {
            cmd.env_remove(key);
        }
    }
    cmd.env("GIT_OPTIONAL_LOCKS", "0").env("GIT_TERMINAL_PROMPT", "0");
    let mut child = cmd.spawn().map_err(|e| {
        if e.kind() == std::io::ErrorKind::NotFound { "git_unavailable" } else { "git_error" }
    })?;
    let mut stdout = child.stdout.take().ok_or("git_error")?;
    let reader = thread::spawn(move || {
        let mut output = Vec::new();
        stdout.read_to_end(&mut output).map(|_| output)
    });
    let started = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) if started.elapsed() < Duration::from_secs(30) => {
                thread::sleep(Duration::from_millis(10));
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                break Err("git_error");
            }
        }
    };
    let output = reader.join().map_err(|_| "git_error")?.map_err(|_| "git_error")?;
    Ok((status?.success(), output))
}

pub fn git_ignored(root: &Path) -> GitIgnore {
    let mut ignored = GitIgnore {
        status: "applied".into(), files: HashSet::new(), dirs: HashSet::new(),
    };
    let output = (|| {
        let (ok, output) = git(root, &["rev-parse", "--is-inside-work-tree"])?;
        if !ok || String::from_utf8_lossy(&output).trim() != "true" {
            return Err("not_repository");
        }
        let (ok, output) = git(root, &[
            "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z", "--", ".",
        ])?;
        if ok { Ok(output) } else { Err("git_error") }
    })();
    match output {
        Err(status) => ignored.status = status.into(),
        Ok(output) => {
            for raw in output.split(|b| *b == 0).filter(|p| !p.is_empty()) {
                let path = String::from_utf8_lossy(raw).into_owned();
                if let Some(dir) = path.strip_suffix('/') {
                    ignored.dirs.insert(dir.into());
                } else {
                    ignored.files.insert(path);
                }
            }
        }
    }
    ignored
}
