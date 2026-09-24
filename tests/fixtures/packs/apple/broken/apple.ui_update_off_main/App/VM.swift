import Foundation
func load() {
  Task.detached {
    isLoading = false
  }
}
