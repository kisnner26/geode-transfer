import SwiftUI

enum GeodeTheme {
    static let violet = Color(red: 0.46, green: 0.30, blue: 0.65)
    static let plum = Color(red: 0.15, green: 0.08, blue: 0.22)
    static let ink = Color(red: 0.055, green: 0.035, blue: 0.08)
    static let mint = Color(red: 0.46, green: 0.86, blue: 0.65)
    static let gold = Color(red: 0.96, green: 0.76, blue: 0.34)
    static let coral = Color(red: 0.95, green: 0.48, blue: 0.52)
    static let panel = Color.white.opacity(0.075)
    static let line = Color.white.opacity(0.15)
    static let cornerRadius = 16.0
    static let spacing = 16.0
}

struct GeodePanel<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(GeodeTheme.spacing)
            .background(GeodeTheme.panel, in: .rect(cornerRadius: GeodeTheme.cornerRadius))
            .overlay {
                RoundedRectangle(cornerRadius: GeodeTheme.cornerRadius)
                    .stroke(GeodeTheme.line, lineWidth: 1)
            }
    }
}
