//! Compatibility shim: `browser-daemon` now just execs `browser daemon` from the same directory.
fn main() {
    let me = std::env::current_exe().unwrap_or_default();
    let browser = me.parent().map(|d| d.join("browser")).unwrap_or_default();
    let target = if browser.exists() { browser } else { std::path::PathBuf::from("browser") };
    use std::os::unix::process::CommandExt;
    let err = std::process::Command::new(&target).arg("daemon").args(std::env::args().skip(1)).exec();
    eprintln!("browser-daemon: failed to exec {}: {err}", target.display());
    std::process::exit(1);
}
