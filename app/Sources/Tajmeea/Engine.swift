import Foundation

/// The Python engine as a child process. One JSON object per line in each direction; stderr goes to a log file.
final class Engine {
    private let process = Process()
    private let input = Pipe()
    private let output = Pipe()
    private var buffer = Data()
    private var stopping = false
    private let onLine: (String) -> Void
    private let onExit: (Int32) -> Void

    init(python: URL, engineDir: URL, log: URL, onLine: @escaping (String) -> Void, onExit: @escaping (Int32) -> Void) {
        self.onLine = onLine
        self.onExit = onExit
        process.executableURL = python
        process.arguments = ["-m", "tajmeea_engine"]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = engineDir.path
        env["PYTHONUNBUFFERED"] = "1"
        // Never write .pyc files into the signed app bundle.
        env["PYTHONPYCACHEPREFIX"] = Paths.caches.appendingPathComponent("pycache").path
        process.environment = env
        process.standardInput = input
        process.standardOutput = output
        process.standardError = Engine.logHandle(log)
    }

    func start() throws {
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard let self = self, !data.isEmpty else { return }
            self.buffer.append(data)
            while let newline = self.buffer.firstIndex(of: 0x0A) {
                let lineData = self.buffer.subdata(in: self.buffer.startIndex..<newline)
                self.buffer.removeSubrange(self.buffer.startIndex...newline)
                if let line = String(data: lineData, encoding: .utf8), !line.isEmpty {
                    DispatchQueue.main.async { self.onLine(line) }
                }
            }
        }
        process.terminationHandler = { [weak self] proc in
            guard let self = self else { return }
            self.output.fileHandleForReading.readabilityHandler = nil
            let status = proc.terminationStatus
            if !self.stopping {
                DispatchQueue.main.async { self.onExit(status) }
            }
        }
        try process.run()
    }

    /// False when the engine can't be reached any more. The old `write(_:)` raised an exception
    /// there and took the whole app down mid-download; this one reports it so the app can restart the engine.
    @discardableResult
    func send(_ line: String) -> Bool {
        // While quitting, stdin is already closed and the page may still be asking things: drop them.
        guard !stopping, process.isRunning, let data = (line + "\n").data(using: .utf8) else { return false }
        do {
            try input.fileHandleForWriting.write(contentsOf: data)
            return true
        } catch {
            NSLog("Tajmeea: couldn't write to the engine: \(error)")
            return false
        }
    }

    /// Ends an engine that stopped listening; its exit then restarts it like any other exit.
    func kill() {
        if process.isRunning { process.terminate() }
    }

    /// Closing stdin asks the engine to stop jobs cleanly (no half files left behind).
    func stop() {
        stopping = true
        try? input.fileHandleForWriting.close()
        let deadline = Date().addingTimeInterval(4)
        while process.isRunning && Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        if process.isRunning { process.terminate() }
    }

    private static func logHandle(_ url: URL) -> FileHandle? {
        let fm = FileManager.default
        try? fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let size = (try? fm.attributesOfItem(atPath: url.path))?[.size] as? Int, size > 5_000_000 {
            let old = url.appendingPathExtension("1")
            try? fm.removeItem(at: old)
            try? fm.moveItem(at: url, to: old)
        }
        if !fm.fileExists(atPath: url.path) { fm.createFile(atPath: url.path, contents: nil) }
        let handle = try? FileHandle(forWritingTo: url)
        handle?.seekToEndOfFile()
        return handle
    }
}

enum Paths {
    static let home = FileManager.default.homeDirectoryForCurrentUser
    /// Same rule as the engine: TAJMEEA_HOME moves everything (used by tests and separate profiles).
    static let support = ProcessInfo.processInfo.environment["TAJMEEA_HOME"].map { URL(fileURLWithPath: $0) }
        ?? home.appendingPathComponent("Library/Application Support/Tajmeea")
    static let caches = home.appendingPathComponent("Library/Caches/Tajmeea")
    static let log = home.appendingPathComponent("Library/Logs/Tajmeea/engine.log")

    /// The ui/ and engine/ folders: inside the app bundle, or a source checkout via TAJMEEA_RESOURCES.
    static var resources: URL {
        if let custom = ProcessInfo.processInfo.environment["TAJMEEA_RESOURCES"] {
            return URL(fileURLWithPath: custom)
        }
        return Bundle.main.resourceURL ?? URL(fileURLWithPath: ".")
    }

    static var python: URL? {
        let candidates = [
            ProcessInfo.processInfo.environment["TAJMEEA_PYTHON"].map { URL(fileURLWithPath: $0) },
            support.appendingPathComponent("venv/bin/python3"),
        ].compactMap { $0 }
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0.path) }
    }
}
