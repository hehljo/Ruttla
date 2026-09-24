import SwiftUI
struct V: View { var body: some View {
  if #available(iOS 17.0, *) {
    ContentUnavailableView("leer", systemImage: "x")
  }
} }
