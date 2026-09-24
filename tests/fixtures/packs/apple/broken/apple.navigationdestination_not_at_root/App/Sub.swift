import SwiftUI
struct Sub: View { var body: some View { List {}.navigationDestination(for: Int.self) { _ in Text("d") } } }
