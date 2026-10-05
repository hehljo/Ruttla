//! `ruttla-engine` — Rust-Engine für deklarative Regeln (ADR-0011).

fn main() {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("--version") => println!("ruttla-engine {}", env!("CARGO_PKG_VERSION")),
        _ => {
            eprintln!("usage: ruttla-engine --version");
            std::process::exit(2);
        }
    }
}
