// Adapted from OpenAI's Codex screenshot skill (Apache-2.0).
// AgentSwitchboard narrows the helper to exactly one frontmost layer-0 window by PID.

import AppKit
import CoreGraphics
import Foundation

struct Bounds: Encodable {
  let x: Int
  let y: Int
  let width: Int
  let height: Int
}

struct WindowInfo: Encodable {
  let id: Int
  let owner: String
  let name: String
  let bundle_id: String?
  let bounds: Bounds
}

struct Response: Encodable {
  let selected: WindowInfo?
}

guard let frontmost = NSWorkspace.shared.frontmostApplication else {
  print("{\"selected\":null}")
  exit(0)
}

let frontmostPID = frontmost.processIdentifier
let ownerName = frontmost.localizedName ?? "Unknown app"
let bundleID = frontmost.bundleIdentifier
let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]

guard let raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
  print("{\"selected\":null}")
  exit(0)
}

var selected: WindowInfo?
for entry in raw {
  guard let ownerPID = entry[kCGWindowOwnerPID as String] as? NSNumber,
        ownerPID.int32Value == frontmostPID else {
    continue
  }

  let layer = (entry[kCGWindowLayer as String] as? NSNumber)?.intValue ?? 0
  if layer != 0 {
    continue
  }

  guard let number = entry[kCGWindowNumber as String] as? NSNumber,
        let boundsDict = entry[kCGWindowBounds as String] as? [String: Any] else {
    continue
  }

  let x = Int((boundsDict["X"] as? NSNumber)?.doubleValue ?? 0)
  let y = Int((boundsDict["Y"] as? NSNumber)?.doubleValue ?? 0)
  let width = Int((boundsDict["Width"] as? NSNumber)?.doubleValue ?? 0)
  let height = Int((boundsDict["Height"] as? NSNumber)?.doubleValue ?? 0)
  if width <= 0 || height <= 0 {
    continue
  }

  selected = WindowInfo(
    id: number.intValue,
    owner: ownerName,
    name: (entry[kCGWindowName as String] as? String) ?? "",
    bundle_id: bundleID,
    bounds: Bounds(x: x, y: y, width: width, height: height)
  )
  break
}

let response = Response(selected: selected)
let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]

if let data = try? encoder.encode(response),
   let json = String(data: data, encoding: .utf8) {
  print(json)
} else {
  fputs("{\"selected\":null}\n", stderr)
  exit(1)
}
