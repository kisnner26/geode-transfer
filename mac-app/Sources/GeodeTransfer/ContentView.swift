import SwiftUI

struct ContentView: View {
    @Bindable var model: TransferModel
    @State private var showConfirmation = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            GeodeBackground()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    header
                    transferRoute
                    categories
                    options
                    activity
                }
                .padding(28)
                .frame(maxWidth: 1120, alignment: .leading)
            }
            .scrollIndicators(.hidden)
        }
        .preferredColorScheme(.dark)
        .confirmationDialog("Start transfer?", isPresented: $showConfirmation, titleVisibility: .visible) {
            Button("Transfer now") { Task { await model.transfer() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Existing matching files on \(model.target?.name ?? "the target") will be overwritten. A safety backup is created first.")
        }
        .animation(reduceMotion ? nil : .easeInOut(duration: 0.2), value: model.phase)
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 20) {
            VStack(alignment: .leading, spacing: 8) {
                Text("GEODE")
                    .font(.system(.largeTitle, design: .rounded).bold())
                    .tracking(3)
                Text("move your data between devices")
                    .font(.title3.bold())
                    .foregroundStyle(GeodeTheme.mint)
                Text("Saves, mods and settings — verified after every transfer.")
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("Refresh devices", systemImage: "arrow.clockwise") {
                Task { await model.refreshDevices() }
            }
            .buttonStyle(.bordered)
            .tint(GeodeTheme.violet)
            .disabled(model.isRunning)
        }
        .accessibilityElement(children: .combine)
    }

    private var transferRoute: some View {
        GeodePanel {
            VStack(alignment: .leading, spacing: 16) {
                Label("transfer route", systemImage: "arrow.left.arrow.right")
                    .font(.headline)
                    .foregroundStyle(GeodeTheme.gold)
                HStack(spacing: 14) {
                    DevicePicker(title: "from", selection: $model.sourceID, devices: model.devices, excludedID: model.targetID)
                    Image(systemName: "arrow.right")
                        .font(.title2.bold())
                        .foregroundStyle(GeodeTheme.mint)
                        .accessibilityHidden(true)
                    DevicePicker(title: "to", selection: $model.targetID, devices: model.devices, excludedID: model.sourceID)
                }
                if model.devices.isEmpty, model.phase != .loading {
                    ContentUnavailableView("No devices found", systemImage: "iphone.slash", description: Text("Connect and unlock both devices, then choose Refresh devices."))
                }
            }
        }
    }

    private var categories: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("what moves")
                .font(.headline)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 230), spacing: 12)], spacing: 12) {
                ForEach(TransferCategory.allCases) { category in
                    CategoryButton(category: category, isSelected: model.selectedCategories.contains(category)) {
                        model.toggle(category)
                    }
                }
            }
        }
    }

    private var options: some View {
        GeodePanel {
            VStack(alignment: .leading, spacing: 12) {
                Text("safety")
                    .font(.headline)
                Toggle("Copy the signing certificate and password", isOn: $model.includeCertificate)
                    .tint(GeodeTheme.coral)
                Text("Leave this off unless the destination needs the same development signing identity.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                Toggle("Keep the intermediate backup on this Mac", isOn: $model.keepBackup)
                    .tint(GeodeTheme.mint)
            }
        }
    }

    private var activity: some View {
        GeodePanel {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Label(statusTitle, systemImage: statusIcon)
                        .font(.headline)
                        .foregroundStyle(statusColor)
                    Spacer()
                    Button("Start transfer", systemImage: "arrow.right.circle.fill") {
                        showConfirmation = true
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(GeodeTheme.violet)
                    .disabled(!model.canTransfer)
                }
                Text(model.output)
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(.black.opacity(0.25), in: .rect(cornerRadius: 10))
                    .accessibilityLabel("Transfer status: \(model.output)")
            }
        }
    }

    private var statusTitle: String {
        switch model.phase {
        case .ready: "ready"
        case .loading: "checking devices"
        case .running: "transfer in progress"
        case .completed: "transfer complete"
        case .failed: "needs attention"
        }
    }

    private var statusIcon: String {
        switch model.phase {
        case .ready: "checkmark.seal.fill"
        case .loading, .running: "arrow.triangle.2.circlepath"
        case .completed: "checkmark.circle.fill"
        case .failed: "exclamationmark.triangle.fill"
        }
    }

    private var statusColor: Color {
        switch model.phase {
        case .ready, .completed: GeodeTheme.mint
        case .loading, .running: GeodeTheme.gold
        case .failed: GeodeTheme.coral
        }
    }
}

private struct DevicePicker: View {
    let title: String
    @Binding var selection: Device.ID?
    let devices: [Device]
    let excludedID: Device.ID?

    private var availableDevices: [Device] { devices.filter { $0.id != excludedID } }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.caption.bold())
                .foregroundStyle(.secondary)
            Picker(title, selection: $selection) {
                Text("Choose device").tag(Device.ID?.none)
                ForEach(availableDevices) { device in
                    Text("\(device.name) · \(device.model) · \(device.connectionLabel)").tag(Optional(device.id))
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(.black.opacity(0.2), in: .rect(cornerRadius: 10))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct CategoryButton: View {
    let category: TransferCategory
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: category.icon)
                    .font(.title3)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 3) {
                    Text(category.title).font(.headline)
                    Text(category.detail).font(.footnote).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isSelected ? GeodeTheme.mint : .secondary)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(isSelected ? GeodeTheme.violet.opacity(0.32) : GeodeTheme.panel, in: .rect(cornerRadius: 14))
            .overlay {
                RoundedRectangle(cornerRadius: 14)
                    .stroke(isSelected ? GeodeTheme.mint.opacity(0.65) : GeodeTheme.line, lineWidth: 1)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(category.title), \(isSelected ? "selected" : "not selected")")
        .accessibilityHint("Double-click to \(isSelected ? "exclude" : "include") this category")
    }
}

private struct GeodeBackground: View {
    var body: some View {
        LinearGradient(colors: [GeodeTheme.ink, GeodeTheme.plum], startPoint: .topLeading, endPoint: .bottomTrailing)
            .ignoresSafeArea()
            .overlay(alignment: .topTrailing) {
                HexPattern()
                    .stroke(GeodeTheme.violet.opacity(0.24), lineWidth: 2)
                    .frame(width: 340, height: 260)
                    .offset(x: 55, y: -42)
                    .accessibilityHidden(true)
            }
    }
}

private struct HexPattern: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let side = 34.0
        let vertical = side * 0.866
        for row in -1...8 {
            for column in -1...8 {
                let x = Double(column) * side * 1.5 + (row.isMultiple(of: 2) ? 0 : side * 0.75)
                let y = Double(row) * vertical
                let center = CGPoint(x: x, y: y)
                for index in 0...6 {
                    let angle = Double(index) * .pi / 3
                    let point = CGPoint(x: center.x + side * cos(angle), y: center.y + side * sin(angle))
                    if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
                }
            }
        }
        return path
    }
}
