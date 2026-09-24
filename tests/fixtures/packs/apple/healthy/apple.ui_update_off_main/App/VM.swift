import Foundation
func load() {
  Task.detached {
    await MainActor.run { isLoading = false }
  }
}
