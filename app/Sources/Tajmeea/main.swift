import AppKit
import ServiceManagement

// A write to an engine that just exited must come back as an error, not end the app.
signal(SIGPIPE, SIG_IGN)

// uninstall.sh runs this before it deletes the app, so «Open at login» doesn't stay behind in
// System Settings › Login Items. Only the app itself can take its own entry out.
if CommandLine.arguments.contains("--forget-login") {
    try? SMAppService.mainApp.unregister()
    exit(0)
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.regular)
    app.run()
}
