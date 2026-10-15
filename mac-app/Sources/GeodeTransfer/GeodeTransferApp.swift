import SwiftUI

@main
struct GeodeTransferApp: App {
    @State private var transfer = TransferModel()

    var body: some Scene {
        WindowGroup {
            ContentView(model: transfer)
                .frame(minWidth: 900, minHeight: 660)
                .task { await transfer.refreshDevices() }
        }
        .windowResizability(.contentSize)
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Refresh devices") {
                    Task { await transfer.refreshDevices() }
                }
                .keyboardShortcut("r", modifiers: .command)
                .disabled(transfer.isRunning)
            }
        }
    }
}
