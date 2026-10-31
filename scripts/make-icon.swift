// Draws the app icon (gold books on a night shelf) into an .iconset folder for iconutil.
// Usage: swift scripts/make-icon.swift /path/AppIcon.iconset
import AppKit

let out = URL(fileURLWithPath: CommandLine.arguments[1])
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

func color(_ hex: UInt32, _ alpha: CGFloat = 1) -> NSColor {
    NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
}

func draw(_ size: Int) -> Data {
    let s = CGFloat(size)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let unit = s / 1024

    // macOS icon grid: an 824pt rounded square centred in 1024.
    let tile = NSRect(x: 100 * unit, y: 100 * unit, width: 824 * unit, height: 824 * unit)
    color(0x17132A).setFill()
    NSBezierPath(roundedRect: tile, xRadius: 185 * unit, yRadius: 185 * unit).fill()
    color(0x1E1930).setFill()
    NSBezierPath(ovalIn: tile.insetBy(dx: 110 * unit, dy: 110 * unit)).fill()

    // Shelf plank.
    color(0xF4EEE3, 0.5).setFill()
    NSBezierPath(roundedRect: NSRect(x: 250 * unit, y: 300 * unit, width: 524 * unit, height: 30 * unit),
                 xRadius: 15 * unit, yRadius: 15 * unit).fill()

    // Three books, the last one leaning.
    let books: [(x: CGFloat, h: CGFloat, alpha: CGFloat, tilt: CGFloat)] = [
        (300, 300, 1.0, 0), (410, 380, 0.8, 0), (545, 280, 0.55, 14),
    ]
    for book in books {
        let rect = NSRect(x: book.x * unit, y: 340 * unit, width: 92 * unit, height: book.h * unit)
        let path = NSBezierPath(roundedRect: rect, xRadius: 18 * unit, yRadius: 18 * unit)
        if book.tilt != 0 {
            let t = NSAffineTransform()
            t.translateX(by: rect.minX, yBy: rect.minY)
            t.rotate(byDegrees: -book.tilt)
            t.translateX(by: -rect.minX, yBy: -rect.minY)
            path.transform(using: t as AffineTransform)
        }
        color(0xF2A541, book.alpha).setFill()
        path.fill()
        if book.tilt == 0 && size >= 64 {
            color(0x120F1C, 0.3).setFill()
            NSRect(x: rect.minX, y: rect.maxY - 70 * unit, width: rect.width, height: 10 * unit).fill()
            NSRect(x: rect.minX, y: rect.maxY - 100 * unit, width: rect.width, height: 10 * unit).fill()
        }
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for base in [16, 32, 128, 256, 512] {
    try draw(base).write(to: out.appendingPathComponent("icon_\(base)x\(base).png"))
    try draw(base * 2).write(to: out.appendingPathComponent("icon_\(base)x\(base)@2x.png"))
}
