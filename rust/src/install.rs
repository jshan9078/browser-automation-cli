//! `browser install`: download the same Chrome-for-Testing builds Playwright pins, into the same
//! cache layout (~/Library/Caches/ms-playwright or ~/.cache/ms-playwright), so the Python and Rust
//! daemons share one Chromium. No Python needed.
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

/// Playwright 1.58 pins: revision 1234 == Chrome for Testing 151.0.7922.34.
pub const REVISION: &str = "1234";
pub const VERSION: &str = "151.0.7922.34";
const CFT: &str = "https://cdn.playwright.dev/chrome-for-testing-public";
const PW: &str = "https://cdn.playwright.dev/dbazure/download/playwright/builds/chromium";

pub fn cache_dir() -> PathBuf {
    if let Ok(p) = std::env::var("PLAYWRIGHT_BROWSERS_PATH") { return PathBuf::from(p); }
    let home = std::env::var("HOME").unwrap_or_default();
    if cfg!(target_os = "macos") { Path::new(&home).join("Library/Caches/ms-playwright") } else { Path::new(&home).join(".cache/ms-playwright") }
}

struct Build { dir: &'static str, url: String, label: &'static str }

fn builds(headless_only: bool) -> Result<Vec<Build>, String> {
    let (os, arch) = (std::env::consts::OS, std::env::consts::ARCH);
    let (shell, full) = match (os, arch) {
        ("macos", "aarch64") => (format!("{CFT}/{VERSION}/mac-arm64/chrome-headless-shell-mac-arm64.zip"), format!("{CFT}/{VERSION}/mac-arm64/chrome-mac-arm64.zip")),
        ("macos", _) => (format!("{CFT}/{VERSION}/mac-x64/chrome-headless-shell-mac-x64.zip"), format!("{CFT}/{VERSION}/mac-x64/chrome-mac-x64.zip")),
        ("linux", "x86_64") => (format!("{CFT}/{VERSION}/linux64/chrome-headless-shell-linux64.zip"), format!("{CFT}/{VERSION}/linux64/chrome-linux64.zip")),
        ("linux", "aarch64") => (format!("{PW}/{REVISION}/chromium-headless-shell-linux-arm64.zip"), format!("{PW}/{REVISION}/chromium-linux-arm64.zip")),
        _ => return Err(format!("unsupported platform {os}/{arch}; set BROWSER_CHROME_PATH to a Chromium binary")),
    };
    let mut v = vec![Build { dir: "chromium_headless_shell", url: shell, label: "chrome-headless-shell (used for hidden sessions)" }];
    if !headless_only { v.push(Build { dir: "chromium", url: full, label: "Chromium (used for `create --show` / `show` windows)" }); }
    Ok(v)
}

pub fn run(args: &[String]) -> Result<(), String> {
    // Headless-only by default (~196 MB): agents never need a window. The headed build (~356 MB)
    // is fetched lazily on the first `show` / `create --show`, or up front with --all.
    let headless_only = !args.iter().any(|a| a == "--all" || a == "--full");
    let force = args.iter().any(|a| a == "--force");
    let cache = cache_dir();
    fs::create_dir_all(&cache).map_err(|e| format!("create {}: {e}", cache.display()))?;
    for b in builds(headless_only)? {
        let dest = cache.join(format!("{}-{REVISION}", b.dir));
        if dest.join("INSTALLATION_COMPLETE").exists() && !force {
            eprintln!("{} already installed at {}", b.label, dest.display());
            continue;
        }
        eprintln!("Downloading {} from {}", b.label, b.url);
        let zip_path = cache.join(format!("{}-{REVISION}.zip", b.dir));
        download(&b.url, &zip_path)?;
        let _ = fs::remove_dir_all(&dest);
        fs::create_dir_all(&dest).map_err(|e| e.to_string())?;
        eprintln!("Extracting to {}", dest.display());
        unzip(&zip_path, &dest)?;
        let _ = fs::remove_file(&zip_path);
        fs::write(dest.join("INSTALLATION_COMPLETE"), "").map_err(|e| e.to_string())?;
        fs::write(dest.join("DEPENDENCIES_VALIDATED"), "").ok();
        eprintln!("Installed {}", b.label);
    }
    let exe = crate::chrome::find_executable(true)?;
    if headless_only {
        eprintln!("Headed Chromium (for `create --show` login windows) will be downloaded automatically on first use; get it now with `browser install --all`.");
    }
    println!("{{\"success\": true, \"chromium\": \"{}\", \"version\": \"{VERSION}\"}}", exe.display());
    Ok(())
}

/// Install the build needed for `headless` if no usable executable exists yet (lazy path for `show`).
pub fn ensure(headless: bool) -> Result<(), String> {
    if crate::chrome::find_executable(headless).is_ok() { return Ok(()); }
    if matches!(crate::chrome::config_engine().as_deref(), Some("system") | Some(_)) && crate::chrome::config_engine().as_deref() != Some("managed") && crate::chrome::config_engine().is_some() {
        return Err("engine is not 'managed'; not downloading. Fix with `browser engine managed` or install the configured browser.".into());
    }
    eprintln!("[daemon] no {} Chromium found; downloading it now (one-time)...", if headless { "headless" } else { "headed" });
    let cache = cache_dir();
    fs::create_dir_all(&cache).map_err(|e| e.to_string())?;
    let all = builds(false)?;
    let b = if headless { &all[0] } else { &all[1] };
    let dest = cache.join(format!("{}-{REVISION}", b.dir));
    let zip_path = cache.join(format!("{}-{REVISION}.zip", b.dir));
    download(&b.url, &zip_path)?;
    let _ = fs::remove_dir_all(&dest);
    fs::create_dir_all(&dest).map_err(|e| e.to_string())?;
    unzip(&zip_path, &dest)?;
    let _ = fs::remove_file(&zip_path);
    fs::write(dest.join("INSTALLATION_COMPLETE"), "").map_err(|e| e.to_string())?;
    fs::write(dest.join("DEPENDENCIES_VALIDATED"), "").ok();
    Ok(())
}

fn download(url: &str, to: &Path) -> Result<(), String> {
    let resp = ureq::get(url).timeout(std::time::Duration::from_secs(900)).call().map_err(|e| format!("download {url}: {e}"))?;
    let total: Option<u64> = resp.header("Content-Length").and_then(|s| s.parse().ok());
    let mut reader = resp.into_reader();
    let mut file = fs::File::create(to).map_err(|e| format!("create {}: {e}", to.display()))?;
    let mut buf = vec![0u8; 1 << 20];
    let mut done: u64 = 0; let mut last_pct = 0u64;
    loop {
        let n = reader.read(&mut buf).map_err(|e| format!("read: {e}"))?;
        if n == 0 { break; }
        file.write_all(&buf[..n]).map_err(|e| format!("write: {e}"))?;
        done += n as u64;
        if let Some(t) = total { let pct = done * 100 / t.max(1); if pct / 10 > last_pct / 10 { eprintln!("  {pct}% ({} MB)", done >> 20); last_pct = pct; } }
    }
    Ok(())
}

fn unzip(zip_path: &Path, dest: &Path) -> Result<(), String> {
    let f = fs::File::open(zip_path).map_err(|e| e.to_string())?;
    let mut archive = zip::ZipArchive::new(f).map_err(|e| format!("open zip: {e}"))?;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i).map_err(|e| e.to_string())?;
        let Some(rel) = entry.enclosed_name() else { continue };
        let out = dest.join(rel);
        let mode = entry.unix_mode().unwrap_or(0o644);
        if entry.is_dir() { fs::create_dir_all(&out).map_err(|e| e.to_string())?; continue; }
        if let Some(p) = out.parent() { fs::create_dir_all(p).map_err(|e| e.to_string())?; }
        if mode & 0o170000 == 0o120000 {
            // symlink entry: content is the target path (Chrome .app bundles use these)
            let mut target = String::new();
            entry.read_to_string(&mut target).map_err(|e| e.to_string())?;
            let _ = fs::remove_file(&out);
            #[cfg(unix)] std::os::unix::fs::symlink(&target, &out).map_err(|e| format!("symlink {}: {e}", out.display()))?;
            continue;
        }
        let mut o = fs::File::create(&out).map_err(|e| format!("create {}: {e}", out.display()))?;
        std::io::copy(&mut entry, &mut o).map_err(|e| e.to_string())?;
        #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; let _ = fs::set_permissions(&out, fs::Permissions::from_mode(mode & 0o777)); }
    }
    Ok(())
}
