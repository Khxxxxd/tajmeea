import AppKit
import ServiceManagement
import UserNotifications
import WebKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var web: WKWebView!
    private var engine: Engine?
    private var restarts: [Date] = []
    private var quitting = false
    private var english = false
    private var statusItem: NSStatusItem!
    private var statusText = ""

    /// Menu and dialog words in the person's chosen language.
    private func say(_ arabic: String, _ english: String) -> String { self.english ? english : arabic }

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()

        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(SchemeHandler(root: Paths.resources.appendingPathComponent("ui"),
                                                 covers: Paths.support.appendingPathComponent("covers")),
                                   forURLScheme: "tajmeea")
        let relay = MessageRelay(owner: self)
        config.userContentController.add(relay, name: "engine")
        config.userContentController.add(relay, name: "native")

        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        if #available(macOS 13.3, *) { web.isInspectable = ProcessInfo.processInfo.environment["TAJMEEA_DEBUG"] != nil }

        // The page runs under a transparent title bar so the design reaches the very top edge.
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1240, height: 800),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered, defer: false
        )
        window.title = "تجميعة"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(red: 0x12 / 255, green: 0x0F / 255, blue: 0x1C / 255, alpha: 1)
        window.appearance = NSAppearance(named: .darkAqua)
        window.minSize = NSSize(width: 1080, height: 700)
        window.isReleasedWhenClosed = false
        window.delegate = self
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 1240, height: 800))
        web.frame = container.bounds
        web.autoresizingMask = [.width, .height]
        container.addSubview(web)
        let titleBarHeight = window.frame.height - window.contentLayoutRect.height
        let drag = TitleBarDragView(frame: NSRect(x: 0, y: container.bounds.height - titleBarHeight,
                                                  width: container.bounds.width, height: titleBarHeight))
        drag.autoresizingMask = [.width, .minYMargin]
        container.addSubview(drag)
        window.contentView = container
        window.center()
        window.setFrameAutosaveName("TajmeeaMain")
        installStatusItem()
        // Opened by macOS at login: stay in the menu bar and update quietly; otherwise show the window.
        if AppDelegate.launchedAtLogin() {
            NSApp.setActivationPolicy(.accessory)
        } else {
            showWindow(nil)
        }

        let ready = startEngine()
        let page = ready ? "tajmeea://app/index.html" : "tajmeea://app/index.html?setup=missing"
        web.load(URLRequest(url: URL(string: page)!))
        installEditingKeys()
    }

    // MARK: Copy and paste

    /// With an Arabic keyboard layout, ⌘V reaches the page as ⌘ر and nothing gets pasted.
    /// The physical key codes are the same on every layout, so the app handles them itself.
    private func installEditingKeys() {
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self = self, self.window.isKeyWindow,
                  event.modifierFlags.intersection([.command, .shift, .option, .control]) == .command
            else { return event }
            switch event.keyCode {
            case 9: // V
                guard let text = NSPasteboard.general.string(forType: .string) else { return nil }
                self.callPage("paste", text) { _ in }
            case 8, 7: // C, X
                self.callPage("copySelection", event.keyCode == 7 ? "cut" : "copy") { result in
                    guard let text = result as? String, !text.isEmpty else { return }
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(text, forType: .string)
                }
            case 0: // A
                self.callPage("selectAll", "") { _ in }
            default:
                return event
            }
            return nil
        }
    }

    private func callPage(_ function: String, _ argument: String, done: @escaping (Any?) -> Void) {
        guard let data = try? JSONSerialization.data(withJSONObject: [argument]),
              let json = String(data: data, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.TajmeeaBridge ? window.TajmeeaBridge.\(function)(\(json)[0]) : null") { result, _ in
            done(result)
        }
    }

    // Closing the window keeps downloads going from the menu bar; opening the app again brings it back.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { showWindow(nil) }
        return true
    }

    @objc private func showWindow(_ sender: Any?) {
        NSApp.setActivationPolicy(.regular)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private static func launchedAtLogin() -> Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent else { return false }
        return event.eventID == kAEOpenApplication
            && event.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
    }

    /// Quitting stops downloads, so ask first when one is running.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard engine != nil, web != nil else { return .terminateNow }
        web.evaluateJavaScript("window.TajmeeaApp ? window.TajmeeaApp.busy() : 0") { [weak self] result, _ in
            guard let self = self, ((result as? NSNumber)?.intValue ?? 0) > 0 else {
                NSApp.reply(toApplicationShouldTerminate: true)
                return
            }
            NSApp.activate(ignoringOtherApps: true)
            let alert = NSAlert()
            alert.messageText = self.say("فيه تنزيل شغال", "A download is running")
            alert.informativeText = self.say(
                "إذا طلعت الحين يوقف التنزيل. الملفات اللي نزلت تبقى، وتكمّل بعدين من «حدّث».",
                "Quitting stops it. Files already saved stay, and Update picks up where it left off.")
            alert.addButton(withTitle: self.say("ارجع", "Keep downloading"))
            alert.addButton(withTitle: self.say("اطلع", "Quit"))
            NSApp.reply(toApplicationShouldTerminate: alert.runModal() == .alertSecondButtonReturn)
        }
        return .terminateLater
    }

    func windowWillClose(_ notification: Notification) {
        toPage(#"{"event":"window.closed","data":{}}"#)
        // No window, no Dock icon: Tajmeea carries on from the menu bar.
        DispatchQueue.main.async { NSApp.setActivationPolicy(.accessory) }
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        engine?.stop()
    }

    // MARK: Engine

    @discardableResult
    private func startEngine() -> Bool {
        guard let python = Paths.python else { return false }
        let engine = Engine(
            python: python,
            engineDir: Paths.resources.appendingPathComponent("engine"),
            log: Paths.log,
            onLine: { [weak self] line in self?.toPage(line) },
            onExit: { [weak self] status in self?.engineExited(status) }
        )
        do {
            try engine.start()
            self.engine = engine
            return true
        } catch {
            NSLog("Tajmeea: engine failed to start: \(error)")
            return false
        }
    }

    private func engineExited(_ status: Int32) {
        guard !quitting else { return }
        NSLog("Tajmeea: engine exited with \(status)")
        restarts = restarts.filter { $0.timeIntervalSinceNow > -60 } + [Date()]
        guard restarts.count <= 3, startEngine() else {
            toPage(#"{"event":"engine.failed","data":{}}"#)
            return
        }
        toPage(#"{"event":"engine.restarted","data":{}}"#)
    }

    private func toPage(_ json: String) {
        web.evaluateJavaScript("window.TajmeeaBridge && window.TajmeeaBridge.receive(\(json))")
    }

    // MARK: Messages from the page

    fileprivate func received(_ message: WKScriptMessage) {
        guard let body = message.body as? String else { return }
        if message.name == "engine" {
            if let engine = engine, !engine.send(body), !quitting { engine.kill() }
        } else if message.name == "native" {
            handleNative(body)
        }
    }

    private func handleNative(_ body: String) {
        guard let data = body.data(using: .utf8),
              let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = message["id"] as? Int,
              let action = message["action"] as? String else { return }
        let args = message["args"] as? [String: Any] ?? [:]
        let path = (args["path"] as? String).map { URL(fileURLWithPath: $0) }

        switch action {
        case "pickFolder":
            let panel = NSOpenPanel()
            panel.canChooseDirectories = true
            panel.canChooseFiles = false
            panel.canCreateDirectories = true
            panel.allowsMultipleSelection = false
            panel.prompt = args["prompt"] as? String ?? say("اختر", "Choose")
            panel.message = args["message"] as? String ?? say("اختر وين تنحفظ ملفات القناة", "Choose where the channel's files go")
            if let start = args["start"] as? String {
                var dir = URL(fileURLWithPath: start)
                while !FileManager.default.fileExists(atPath: dir.path) && dir.path != "/" { dir.deleteLastPathComponent() }
                panel.directoryURL = dir
            }
            panel.beginSheetModal(for: window) { [weak self] response in
                self?.reply(id, response == .OK ? panel.url?.path : nil)
            }
        case "openPath":
            guard let url = path, FileManager.default.fileExists(atPath: url.path) else {
                return replyError(id, "الملف مو موجود بمكانه. يمكن انحذف أو انتقل.")
            }
            NSWorkspace.shared.open(url)
            reply(id, true)
        case "reveal":
            guard let url = path else { return reply(id, false) }
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir) {
                if isDir.boolValue { NSWorkspace.shared.open(url) } else { NSWorkspace.shared.activateFileViewerSelecting([url]) }
                reply(id, true)
            } else {
                replyError(id, "المجلد مو موجود. يمكن انحذف أو انتقل.")
            }
        case "preview":
            guard let url = path, FileManager.default.fileExists(atPath: url.path) else {
                return replyError(id, say("الملف مو موجود بمكانه. يمكن انحذف أو انتقل.", "The file isn't there any more."))
            }
            let quickLook = Process()
            quickLook.executableURL = URL(fileURLWithPath: "/usr/bin/qlmanage")
            quickLook.arguments = ["-p", url.path]
            quickLook.standardOutput = FileHandle.nullDevice
            quickLook.standardError = FileHandle.nullDevice
            try? quickLook.run()
            reply(id, true)
        case "notify":
            // Only when the person is somewhere else; inside the app the screen already shows it.
            guard !NSApp.isActive, Bundle.main.bundleIdentifier != nil else { return reply(id, false) }
            let content = UNMutableNotificationContent()
            content.title = args["title"] as? String ?? say("تجميعة", "Tajmeea")
            content.body = args["body"] as? String ?? ""
            content.sound = .default
            let center = UNUserNotificationCenter.current()
            center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
                guard granted else { return }
                center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
            }
            reply(id, true)
        case "setLanguage":
            english = (args["language"] as? String) == "en"
            buildMenu()
            reply(id, true)
        case "status":
            statusText = args["text"] as? String ?? ""
            statusItem?.button?.toolTip = statusText.isEmpty ? say("تجميعة", "Tajmeea") : statusText
            reply(id, true)
        case "trash":
            // Paths come from the engine's own record of what it saved for that channel.
            let paths = args["paths"] as? [String] ?? []
            let folder = args["folder"] as? String ?? ""
            let includingFolder = args["ownFolder"] as? Bool ?? false
            Task.detached {
                let result = Trash.move(paths, folder: folder, includingFolder: includingFolder)
                await MainActor.run { self.reply(id, ["moved": result.moved, "failed": result.failed]) }
            }
        case "readClipboard":
            reply(id, NSPasteboard.general.string(forType: .string) ?? "")
        case "openURL":
            if let raw = args["url"] as? String, let url = URL(string: raw), ["https", "tg"].contains(url.scheme ?? "") {
                NSWorkspace.shared.open(url)
            }
            reply(id, true)
        default:
            replyError(id, "طلب مو معروف.")
        }
    }

    private func reply(_ id: Int, _ result: Any?) {
        send(["id": id, "result": result ?? NSNull()])
    }

    private func replyError(_ id: Int, _ text: String) {
        send(["id": id, "error": ["message": text, "code": "native"]])
    }

    private func send(_ object: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: object),
              let json = String(data: data, encoding: .utf8) else { return }
        toPage(json)
    }

    // MARK: Self-check

    /// TAJMEEA_SNAPSHOT=/path.png saves what the window shows a few seconds after launch.
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let target = ProcessInfo.processInfo.environment["TAJMEEA_SNAPSHOT"] else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            guard let self = self else { return }
            self.web.evaluateJavaScript("document.getElementById('app').innerText") { text, _ in
                try? ((text as? String) ?? "").write(toFile: target + ".txt", atomically: true, encoding: .utf8)
            }
            self.web.takeSnapshot(with: nil) { image, _ in
                if let tiff = image?.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                   let png = rep.representation(using: .png, properties: [:]) {
                    try? png.write(to: URL(fileURLWithPath: target))
                }
                if ProcessInfo.processInfo.environment["TAJMEEA_QUIT_AFTER_SNAPSHOT"] != nil {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
                }
            }
        }
    }

    // MARK: Links

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.cancel) }
        if url.scheme == "tajmeea" { return decisionHandler(.allow) }
        if ["https", "tg"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        decisionHandler(.cancel)
    }

    // MARK: Menu bar icon

    private func installStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        let image = NSImage(systemSymbolName: "books.vertical", accessibilityDescription: say("تجميعة", "Tajmeea"))
        image?.isTemplate = true
        statusItem.button?.image = image
        statusItem.button?.toolTip = say("تجميعة", "Tajmeea")
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
    }

    /// Built fresh each time it opens, so the status line and the login switch are always current.
    func menuNeedsUpdate(_ menu: NSMenu) {
        guard menu === statusItem?.menu else { return }
        menu.removeAllItems()
        let status = menu.addItem(withTitle: statusText.isEmpty ? say("تجميعة", "Tajmeea") : statusText, action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(.separator())
        menu.addItem(withTitle: say("افتح تجميعة", "Open Tajmeea"), action: #selector(showWindow(_:)), keyEquivalent: "").target = self
        menu.addItem(withTitle: say("حدّث كل القنوات الحين", "Update all channels now"), action: #selector(updateAll(_:)), keyEquivalent: "").target = self
        menu.addItem(.separator())
        let login = menu.addItem(withTitle: say("افتحها مع تشغيل الجهاز", "Open at login"), action: #selector(toggleOpenAtLogin(_:)), keyEquivalent: "")
        login.target = self
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(.separator())
        menu.addItem(withTitle: say("اطلع من تجميعة", "Quit Tajmeea"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "")
    }

    @objc private func updateAll(_ sender: Any?) {
        web.evaluateJavaScript("window.TajmeeaApp && window.TajmeeaApp.updateAll()")
    }

    @objc private func toggleOpenAtLogin(_ sender: Any?) {
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled { try service.unregister() } else { try service.register() }
        } catch {
            NSApp.activate(ignoringOtherApps: true)
            let alert = NSAlert()
            alert.messageText = say("ما قدرنا نغيّرها", "Couldn't change that")
            alert.informativeText = error.localizedDescription
            alert.runModal()
        }
        // macOS may want the person to allow it once in System Settings › Login Items.
        if service.status == .requiresApproval { SMAppService.openSystemSettingsLoginItems() }
    }

    // MARK: Menu

    private func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: say("عن تجميعة", "About Tajmeea"),
                        action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: say("أخفِ تجميعة", "Hide Tajmeea"), action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: say("اطلع من تجميعة", "Quit Tajmeea"),
                        action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        // Without an Edit menu, ⌘C / ⌘V do nothing inside the page.
        let editItem = NSMenuItem()
        let edit = NSMenu(title: say("تحرير", "Edit"))
        edit.addItem(withTitle: say("تراجع", "Undo"), action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: say("إعادة", "Redo"), action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: say("قص", "Cut"), action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: say("نسخ", "Copy"), action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: say("لصق", "Paste"), action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: say("تحديد الكل", "Select All"), action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        let windowItem = NSMenuItem()
        let windowMenu = NSMenu(title: say("النافذة", "Window"))
        windowMenu.addItem(withTitle: say("تصغير", "Minimize"), action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: say("سكّر النافذة", "Close Window"), action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowItem.submenu = windowMenu
        main.addItem(windowItem)

        NSApp.mainMenu = main
        NSApp.windowsMenu = windowMenu
    }
}

/// The web page swallows mouse events, so this strip over the title bar keeps the window draggable.
private final class TitleBarDragView: NSView {
    override var mouseDownCanMoveWindow: Bool { true }

    override func mouseDown(with event: NSEvent) {
        guard let window = window else { return }
        guard event.clickCount == 2 else { return window.performDrag(with: event) }
        // Honour System Settings › Desktop & Dock › "Double-click a window's title bar to …".
        switch UserDefaults.standard.string(forKey: "AppleActionOnDoubleClick") {
        case "Minimize": window.performMiniaturize(nil)
        case "None": break
        default: window.performZoom(nil)
        }
    }
}

/// WKUserContentController keeps its handlers alive; this weak hop avoids a retain cycle with the delegate.
private final class MessageRelay: NSObject, WKScriptMessageHandler {
    weak var owner: AppDelegate?

    init(owner: AppDelegate) {
        self.owner = owner
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        MainActor.assumeIsolated { owner?.received(message) }
    }
}
