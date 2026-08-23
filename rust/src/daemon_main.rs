fn main() {
    let rt = tokio::runtime::Builder::new_multi_thread().enable_all().build().expect("tokio runtime");
    if let Err(e) = rt.block_on(browser_cli::server::run()) {
        eprintln!("[daemon] fatal: {e}");
        std::process::exit(1);
    }
}
