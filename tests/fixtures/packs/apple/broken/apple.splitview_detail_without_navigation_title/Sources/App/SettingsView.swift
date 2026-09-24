import SwiftUI
struct SettingsView: View {
  var body: some View {
    NavigationSplitView {
      Text("Sidebar")
    } detail: {
      Form { Text("Inhalt") }
    }
  }
}
