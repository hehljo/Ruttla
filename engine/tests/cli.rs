use std::process::Command;

#[test]
fn version_flag_names_the_crate_version() {
    let out = Command::new(env!("CARGO_BIN_EXE_ruttla-engine"))
        .arg("--version")
        .output()
        .expect("engine binary runs");
    assert!(out.status.success());
    let text = String::from_utf8(out.stdout).unwrap();
    assert_eq!(text.trim(), format!("ruttla-engine {}", env!("CARGO_PKG_VERSION")));
}

#[test]
fn unknown_arguments_are_a_usage_error() {
    let out = Command::new(env!("CARGO_BIN_EXE_ruttla-engine"))
        .arg("--nope")
        .output()
        .expect("engine binary runs");
    assert_eq!(out.status.code(), Some(2));
}
