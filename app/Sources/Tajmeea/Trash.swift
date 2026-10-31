import Foundation

/// Moves a removed channel's files to the Trash, one by one so Finder's «Put Back» works,
/// then the year and section folders they leave empty. Nothing else in the folder is touched.
enum Trash {
    struct Result {
        var moved = 0
        var failed = 0
    }

    static func move(_ paths: [String], folder: String, includingFolder: Bool,
                     using trash: (URL) throws -> Void = { try FileManager.default.trashItem(at: $0, resultingItemURL: nil) }) -> Result {
        var result = Result()
        let top = URL(fileURLWithPath: folder).standardizedFileURL
        var leftBehind = Set<String>()
        for path in paths {
            let url = URL(fileURLWithPath: path).standardizedFileURL
            let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
            guard values?.isRegularFile == true, values?.isSymbolicLink != true else { continue }
            do {
                try trash(url)
                result.moved += 1
                // Only folders that held these files, and only inside the channel's folder.
                var dir = url.deletingLastPathComponent()
                while dir.path.hasPrefix(top.path + "/") {
                    leftBehind.insert(dir.path)
                    dir = dir.deletingLastPathComponent()
                }
            } catch {
                result.failed += 1
            }
        }
        if includingFolder { leftBehind.insert(top.path) }
        for path in leftBehind.sorted(by: { $0.count > $1.count }) {  // deepest first
            guard let contents = try? FileManager.default.contentsOfDirectory(atPath: path),
                  contents.allSatisfy({ $0 == ".DS_Store" }) else { continue }
            try? trash(URL(fileURLWithPath: path, isDirectory: true))
        }
        return result
    }
}
