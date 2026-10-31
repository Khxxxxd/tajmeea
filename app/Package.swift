// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Tajmeea",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "Tajmeea", path: "Sources/Tajmeea")
    ]
)
