// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "GeodeTransfer",
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "GeodeTransfer", targets: ["GeodeTransfer"])
    ],
    targets: [
        .executableTarget(name: "GeodeTransfer")
    ]
)
