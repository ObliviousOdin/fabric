// swift-tools-version: 5.10

import PackageDescription

let package = Package(
    name: "FabricLinkCore",
    platforms: [
        .iOS(.v17),
        .macOS(.v14),
    ],
    products: [
        .library(name: "FabricLinkCore", targets: ["FabricLinkCore"]),
    ],
    targets: [
        .binaryTarget(
            name: "FabricLinkCoreFFI",
            path: "Artifacts/FabricLinkCoreFFI.xcframework"
        ),
        .target(
            name: "FabricLinkCore",
            dependencies: ["FabricLinkCoreFFI"],
            path: "Sources/FabricLinkCore"
        ),
    ]
)
