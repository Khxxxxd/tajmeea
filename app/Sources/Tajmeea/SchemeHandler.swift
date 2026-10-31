import Foundation
import WebKit

/// Serves the bundled interface at tajmeea://app/… so the page gets a real origin and a strict CSP,
/// plus the file covers the engine makes, at tajmeea://app/covers/<channel>/<message>.png.
final class SchemeHandler: NSObject, WKURLSchemeHandler {
    private let root: URL
    private let covers: URL

    init(root: URL, covers: URL) {
        self.root = root.standardizedFileURL
        self.covers = covers.standardizedFileURL
    }

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else { return }
        var path = url.path.isEmpty || url.path == "/" ? "index.html" : String(url.path.dropFirst())
        var base = root
        if path.hasPrefix("covers/") {
            base = covers
            path = String(path.dropFirst("covers/".count))
        }
        let file = base.appendingPathComponent(path).standardizedFileURL
        guard file.path.hasPrefix(base.path + "/"), let data = try? Data(contentsOf: file) else {
            task.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let headers = [
            "Content-Type": SchemeHandler.mime(file.pathExtension),
            "Content-Length": String(data.count),
            "Cache-Control": "no-store",
        ]
        if let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers) {
            task.didReceive(response)
        }
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}

    private static func mime(_ ext: String) -> String {
        switch ext.lowercased() {
        case "html": return "text/html; charset=utf-8"
        case "js": return "text/javascript; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "svg": return "image/svg+xml"
        case "png": return "image/png"
        case "ttf": return "font/ttf"
        case "woff2": return "font/woff2"
        default: return "application/octet-stream"
        }
    }
}
