import Foundation

struct Device: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let udid: String
    let name: String
    let model: String
    let os: String
    let kind: String
    let transport: String
    let pairing: String

    var connectionLabel: String {
        transport == "wired" ? "USB" : "Wi-Fi"
    }
}

enum TransferConnection: String, CaseIterable, Identifiable {
    case automatic
    case cable

    var id: Self { self }

    var title: String {
        switch self {
        case .automatic: "automatic"
        case .cable: "usb cable"
        }
    }
}

enum TransferCategory: String, CaseIterable, Identifiable {
    case saves
    case mods
    case modData = "mod-data"
    case modConfig = "mod-config"
    case songs
    case prefs

    var id: String { rawValue }

    var title: String {
        switch self {
        case .saves: "saves"
        case .mods: "mods"
        case .modData: "mod data"
        case .modConfig: "mod config"
        case .songs: "songs"
        case .prefs: "preferences"
        }
    }

    var detail: String {
        switch self {
        case .saves: "progress and local levels"
        case .mods: "installed .geode files"
        case .modData: "settings and key bindings"
        case .modConfig: "mod configuration folders"
        case .songs: "downloaded custom songs"
        case .prefs: "launcher preferences"
        }
    }

    var icon: String {
        switch self {
        case .saves: "square.stack.3d.up.fill"
        case .mods: "puzzlepiece.extension.fill"
        case .modData: "slider.horizontal.3"
        case .modConfig: "folder.fill"
        case .songs: "music.note.list"
        case .prefs: "gearshape.fill"
        }
    }
}

enum TransferPhase: Equatable {
    case ready
    case loading
    case running
    case completed
    case failed(String)
}
