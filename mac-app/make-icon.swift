// Draws the Cipher app icon (1024×1024 PNG): a glowing orb on a dark rounded square.
import AppKit

let size: CGFloat = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"
// "full": edge-to-edge square for phones and web apps (they round the corners themselves).
let fullBleed = CommandLine.arguments.count > 2 && CommandLine.arguments[2] == "full"
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size), bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext
let space = CGColorSpaceCreateDeviceRGB()
func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor { CGColor(red: r / 255, green: g / 255, blue: b / 255, alpha: a) }

// macOS-style rounded square with a soft vertical gradient.
let inset: CGFloat = fullBleed ? 0 : 100
let tile = CGRect(x: inset, y: inset, width: size - 2 * inset, height: size - 2 * inset)
let tilePath = fullBleed ? CGPath(rect: tile, transform: nil) : CGPath(roundedRect: tile, cornerWidth: 185, cornerHeight: 185, transform: nil)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -14), blur: 30, color: rgb(0, 0, 0, 0.45))
ctx.addPath(tilePath); ctx.setFillColor(rgb(10, 12, 22)); ctx.fillPath()
ctx.restoreGState()
ctx.saveGState()
ctx.addPath(tilePath); ctx.clip()
let bg = CGGradient(colorsSpace: space, colors: [rgb(28, 36, 72), rgb(8, 10, 18)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: size / 2, y: tile.maxY), end: CGPoint(x: size / 2, y: tile.minY), options: [])

let c = CGPoint(x: size / 2, y: size / 2 + 10)
// Outer glow.
let glow = CGGradient(colorsSpace: space, colors: [rgb(120, 168, 255, 0.55), rgb(120, 168, 255, 0)] as CFArray, locations: [0, 1])!
ctx.drawRadialGradient(glow, startCenter: c, startRadius: 150, endCenter: c, endRadius: 380, options: [])
// Orbit ring.
ctx.setStrokeColor(rgb(150, 190, 255, 0.35)); ctx.setLineWidth(6)
ctx.strokeEllipse(in: CGRect(x: c.x - 300, y: c.y - 95, width: 600, height: 190))
// The orb.
let r: CGFloat = 215
ctx.saveGState()
ctx.addEllipse(in: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r)); ctx.clip()
let orb = CGGradient(colorsSpace: space, colors: [rgb(235, 243, 255), rgb(140, 182, 255), rgb(60, 98, 210), rgb(22, 34, 96)] as CFArray,
                     locations: [0, 0.28, 0.68, 1])!
ctx.drawRadialGradient(orb, startCenter: CGPoint(x: c.x - 70, y: c.y + 85), startRadius: 0, endCenter: c, endRadius: r, options: [.drawsAfterEndLocation])
// Faint scan lines across the orb.
ctx.setStrokeColor(rgb(255, 255, 255, 0.10)); ctx.setLineWidth(3)
var y = c.y - r
while y < c.y + r { ctx.move(to: CGPoint(x: c.x - r, y: y)); ctx.addLine(to: CGPoint(x: c.x + r, y: y)); y += 22 }
ctx.strokePath()
ctx.restoreGState()
// Front half of the ring, over the orb.
ctx.saveGState()
ctx.clip(to: CGRect(x: 0, y: 0, width: size, height: c.y))
ctx.setStrokeColor(rgb(170, 205, 255, 0.55)); ctx.setLineWidth(6)
ctx.strokeEllipse(in: CGRect(x: c.x - 300, y: c.y - 95, width: 600, height: 190))
ctx.restoreGState()
ctx.restoreGState()
NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print("wrote \(out)")
