import Foundation
import Observation

@MainActor @Observable
final class TransferModel {
    var devices: [Device] = []
    var sourceID: Device.ID?
    var targetID: Device.ID?
    var selectedCategories = Set(TransferCategory.allCases)
    var includeCertificate = false
    var keepBackup = false
    var phase: TransferPhase = .loading
    var output = "Looking for connected devices..."

    var source: Device? { devices.first { $0.id == sourceID } }
    var target: Device? { devices.first { $0.id == targetID } }
    var isRunning: Bool { phase == .loading || phase == .running }
    var canTransfer: Bool {
        source != nil && target != nil && sourceID != targetID && !selectedCategories.isEmpty && !isRunning
    }

    func refreshDevices() async {
        phase = .loading
        output = "Looking for connected devices..."
        do {
            let result = try await CommandRunner.run(arguments: ["devices", "--json"])
            devices = try JSONDecoder().decode([Device].self, from: Data(result.stdout.utf8))
            sourceID = devices.contains { $0.id == sourceID } ? sourceID : devices.first?.id
            targetID = devices.first { $0.id != sourceID }?.id
            phase = .ready
            output = devices.isEmpty ? "No compatible iPhone or iPad found." : "\(devices.count) device\(devices.count == 1 ? "" : "s") ready."
        } catch {
            phase = .failed(error.localizedDescription)
            output = error.localizedDescription
        }
    }

    func toggle(_ category: TransferCategory) {
        if selectedCategories.contains(category) {
            selectedCategories.remove(category)
        } else {
            selectedCategories.insert(category)
        }
    }

    func transfer() async {
        guard let source, let target else { return }
        phase = .running
        output = "Preparing transfer from \(source.name) to \(target.name)..."
        var arguments = [
            "transfer", "--from", source.id,
            "--to", target.id,
            "--only", selectedCategories.map(\.rawValue).sorted().joined(separator: ","),
            "--yes"
        ]
        if includeCertificate { arguments.append("--include-certificate") }
        if keepBackup { arguments.append("--keep") }

        do {
            let result = try await CommandRunner.run(arguments: arguments) { [weak self] line in
                Task { @MainActor in self?.output = line }
            }
            phase = .completed
            output = result.stdout.isEmpty ? "Transfer complete." : result.stdout
        } catch {
            phase = .failed(error.localizedDescription)
            output = error.localizedDescription
        }
    }
}

enum CommandRunner {
    struct Result: Sendable {
        let stdout: String
    }

    static func run(arguments: [String], onOutput: (@Sendable (String) -> Void)? = nil) async throws -> Result {
        try await Task.detached(priority: .userInitiated) { () throws -> Result in
            let script = try scriptURL()
            let process = Process()
            process.executableURL = URL(filePath: "/usr/bin/env")
            process.arguments = ["python3", script.path(percentEncoded: false)] + arguments

            let stdout = Pipe()
            let stderr = Pipe()
            process.standardOutput = stdout
            process.standardError = stderr
            process.qualityOfService = .userInitiated
            try process.run()
            process.waitUntilExit()

            let standardOutput = String(decoding: stdout.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            let standardError = String(decoding: stderr.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            for line in standardOutput.split(separator: "\n") {
                onOutput?(String(line))
            }
            guard process.terminationStatus == 0 else {
                throw TransferCommandError(message: standardError.isEmpty ? standardOutput : standardError)
            }
            return Result(stdout: standardOutput.trimmingCharacters(in: .whitespacesAndNewlines))
        }.value
    }

    private static func scriptURL() throws -> URL {
        if let configured = ProcessInfo.processInfo.environment["GEODE_TRANSFER_CLI"] {
            return URL(filePath: configured)
        }
        if let bundled = Bundle.main.url(forResource: "geode_transfer", withExtension: "py") {
            return bundled
        }
        let current = URL.currentDirectory()
        let localScript = current.appending(path: "../geode_transfer.py").standardized
        if FileManager.default.fileExists(atPath: localScript.path()) { return localScript }
        throw TransferCommandError(message: "The Geode Transfer engine was not found. Set GEODE_TRANSFER_CLI to geode_transfer.py.")
    }
}

struct TransferCommandError: LocalizedError {
    let message: String
    var errorDescription: String? { message.trimmingCharacters(in: .whitespacesAndNewlines) }
}
