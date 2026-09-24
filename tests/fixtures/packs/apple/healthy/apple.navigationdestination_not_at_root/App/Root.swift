import SwiftUI
struct Root: View { var body: some View { NavigationStack { List {}.navigationDestination(for: Int.self) { _ in Text("d") } } } }
