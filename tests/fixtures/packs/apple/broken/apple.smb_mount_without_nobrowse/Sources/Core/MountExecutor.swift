import Foundation
func mount(_ src: String, _ mp: String) throws {
  let process = Process()
  process.executableURL = URL(fileURLWithPath: "/sbin/mount_smbfs")
  process.arguments = [src, mp]
  try process.run()
}
