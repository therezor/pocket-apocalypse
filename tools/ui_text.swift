// Text rasteriser for tools/ui_art.py (macOS CoreText; no image libraries
// needed on the Python side).
//
//   swift ui_text.swift glyphs <font file> <px size> <cell height> <baseline> <out dir>
//       one 8-bit grey PNG per character 32..126 (<code>.png), the cell
//       <cell height> rows tall with the baseline <baseline> rows from the
//       top and as wide as the glyph's advance; coverage is the grey level
//   swift ui_text.swift text <font file> <px size> <out.png> <text>
//       the text on one line, grey coverage, cropped to its ink
import CoreGraphics
import CoreText
import Foundation
import ImageIO
import UniformTypeIdentifiers

func loadFont(_ path: String, _ size: CGFloat) -> CTFont {
    let url = URL(fileURLWithPath: path) as CFURL
    guard let descs = CTFontManagerCreateFontDescriptorsFromURL(url) as? [CTFontDescriptor], let d = descs.first else {
        fatalError("no font in \(path)")
    }
    return CTFontCreateWithFontDescriptor(d, size, nil)
}

func grey(_ w: Int, _ h: Int) -> CGContext {
    let ctx = CGContext(data: nil, width: max(w, 1), height: max(h, 1), bitsPerComponent: 8, bytesPerRow: 0,
                        space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
    ctx.setFillColor(gray: 0, alpha: 1)
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.setShouldAntialias(true)
    ctx.setAllowsFontSmoothing(false)
    ctx.setShouldSmoothFonts(false)
    ctx.setFillColor(gray: 1, alpha: 1)
    return ctx
}

func save(_ img: CGImage, _ path: String) {
    let dst = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(dst, img, nil)
    CGImageDestinationFinalize(dst)
}

func line(_ font: CTFont, _ s: String) -> CTLine {
    let attr = [kCTFontAttributeName: font, kCTForegroundColorFromContextAttributeName: true] as [CFString: Any]
    return CTLineCreateWithAttributedString(NSAttributedString(string: s, attributes: attr as [NSAttributedString.Key: Any]))
}

let a = CommandLine.arguments
if a.count >= 7 && a[1] == "glyphs" {
    let font = loadFont(a[2], CGFloat(Double(a[3])!))
    let cellH = Int(a[4])!, base = Int(a[5])!, dir = a[6]
    for code in 32...126 {
        let s = String(UnicodeScalar(UInt8(code)))
        let l = line(font, s)
        let adv = Int(CTLineGetTypographicBounds(l, nil, nil, nil).rounded())
        let ctx = grey(adv, cellH)
        ctx.textPosition = CGPoint(x: 0, y: CGFloat(cellH - base))
        CTLineDraw(l, ctx)
        save(ctx.makeImage()!, "\(dir)/\(code).png")
    }
} else if a.count >= 6 && a[1] == "text" {
    let font = loadFont(a[2], CGFloat(Double(a[3])!))
    let l = line(font, a[5])
    let ink = CTLineGetImageBounds(l, nil)
    let pad = 2
    let w = Int(ink.width.rounded(.up)) + 2 * pad, h = Int(ink.height.rounded(.up)) + 2 * pad
    let ctx = grey(w, h)
    ctx.textPosition = CGPoint(x: CGFloat(pad) - ink.minX, y: CGFloat(pad) - ink.minY)
    CTLineDraw(l, ctx)
    save(ctx.makeImage()!, a[4])
} else {
    fatalError("usage: see the header")
}
