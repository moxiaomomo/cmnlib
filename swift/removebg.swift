// RGB -> HSV，输出 h/s/v 均为 [0, 1]
func rgbToHSV(r: Double, g: Double, b: Double) -> (h: Double, s: Double, v: Double) {
    let maxV = max(r, g, b)
    let minV = min(r, g, b)
    let delta = maxV - minV
    var h: Double = 0.0

    if delta > 1e-6 {
        if maxV == r {
            h = ((g - b) / delta).truncatingRemainder(dividingBy: 6.0)
        } else if maxV == g {
            h = (b - r) / delta + 2.0
        } else {
            h = (r - g) / delta + 4.0
        }
        h /= 6.0
        if h < 0 { h += 1.0 }
    }

    let s = maxV <= 1e-6 ? 0.0 : delta / maxV
    return (h, s, maxV)
}

func hueCircularDistance(_ a: Double, _ b: Double) -> Double {
    let d = abs(a - b)
    return min(d, 1.0 - d)
}

// 自动检测图片边缘主色相（H），返回主色相（0~1）
func detectDominantEdgeHue(cgImage: CGImage) -> Double? {
    let width = cgImage.width
    let height = cgImage.height
    guard width > 8, height > 8 else { return nil }

    var rgbaPixels = [UInt8](repeating: 0, count: width * height * 4)
    guard
        let rgbColorSpace = CGColorSpace(name: CGColorSpace.sRGB),
        let rgbContext = CGContext(
            data: &rgbaPixels,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: rgbColorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )
    else {
        return nil
    }
    rgbContext.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

    let bins = 72
    var hist = [Double](repeating: 0.0, count: bins)
    let edgeWidth = max(2, min(width, height) / 16)

    for y in 0..<height {
        for x in 0..<width {
            if x < edgeWidth || x >= width - edgeWidth || y < edgeWidth || y >= height - edgeWidth {
                let idx = (y * width + x) * 4
                let r = Double(rgbaPixels[idx]) / 255.0
                let g = Double(rgbaPixels[idx + 1]) / 255.0
                let b = Double(rgbaPixels[idx + 2]) / 255.0
                let a = Double(rgbaPixels[idx + 3]) / 255.0

                let hsv = rgbToHSV(r: r, g: g, b: b)
                // 忽略低饱和/低亮度像素，避免灰边干扰主色相统计
                if hsv.s < 0.08 || hsv.v < 0.08 || a < 0.1 {
                    continue
                }

                let weight = hsv.s * hsv.v * a
                let binIndex = Int(hsv.h * Double(bins)) % bins
                hist[binIndex] += weight
            }
        }
    }

    guard let (maxIdx, maxWeight) = hist.enumerated().max(by: { $0.element < $1.element }), maxWeight > 0 else {
        return nil
    }
    return (Double(maxIdx) + 0.5) / Double(bins)
}
import Foundation
import Vision
import CoreImage
import AppKit
import ImageIO
import UniformTypeIdentifiers

struct RemoveBGOptions {
    var backgroundMode: BackgroundMode
    var maskDilateRadius: Double
    var maskBlurRadius: Double
    var minForegroundRatio: Double
    var chromaKeyThreshold: Double
    var chromaKeySoftness: Double
    var chromaKeyMinimumGreen: Double
    var watermarkRemovalEnabled: Bool
    var watermarkMinConfidence: Double
    var watermarkEdgeMarginRatio: Double
    var watermarkMaxAreaRatio: Double
    var watermarkMaxHeightRatio: Double
    var watermarkRightSideMinRatio: Double
    var watermarkBottomMaxRatio: Double
    var watermarkMinLuma: Double
    var watermarkMaxSaturation: Double
    var watermarkBoxPaddingRatio: Double
    var watermarkRepairRadius: Double
}

enum BackgroundMode {
    case vision
    case chromaKey
    case hybrid
    case autoChromaKey

    var displayName: String {
        switch self {
        case .vision:
            return "vision"
        case .chromaKey:
            return "chromaKey"
        case .hybrid:
            return "hybrid"
        case .autoChromaKey:
            return "autoChromaKey"
        }
    }

    static func parse(_ value: String) -> BackgroundMode? {
        switch value.lowercased() {
        case "vision":
            return .vision
        case "chromakey", "chroma_key", "chroma-key":
            return .chromaKey
        case "hybrid":
            return .hybrid
        case "autochromakey", "auto_chromakey", "auto-chromakey":
            return .autoChromaKey
        default:
            return nil
        }
    }
}

enum OutputFormat: String {
    case png
    case webp

    var fileExtension: String {
        rawValue
    }

    var displayName: String {
        rawValue.uppercased()
    }

    var utTypeIdentifier: CFString? {
        switch self {
        case .png:
            return UTType.png.identifier as CFString
        case .webp:
            return UTType(filenameExtension: "webp")?.identifier as CFString?
        }
    }
}

func estimateForegroundRatio(maskPixelBuffer: CVPixelBuffer) -> Double {
    CVPixelBufferLockBaseAddress(maskPixelBuffer, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(maskPixelBuffer, .readOnly) }

    let width = CVPixelBufferGetWidth(maskPixelBuffer)
    let height = CVPixelBufferGetHeight(maskPixelBuffer)
    let bytesPerRow = CVPixelBufferGetBytesPerRow(maskPixelBuffer)
    guard let baseAddress = CVPixelBufferGetBaseAddress(maskPixelBuffer) else {
        return 0.0
    }

    let ptr = baseAddress.bindMemory(to: UInt8.self, capacity: bytesPerRow * height)
    var nonZeroCount = 0
    let threshold: UInt8 = 16

    for y in 0..<height {
        let rowStart = ptr.advanced(by: y * bytesPerRow)
        for x in 0..<width {
            if rowStart[x] > threshold {
                nonZeroCount += 1
            }
        }
    }

    let total = max(1, width * height)
    return Double(nonZeroCount) / Double(total)
}

func estimateForegroundRatio(maskCGImage: CGImage) -> Double {
    let width = maskCGImage.width
    let height = maskCGImage.height
    guard width > 0, height > 0 else {
        return 0.0
    }

    var pixels = [UInt8](repeating: 0, count: width * height)
    guard
        let colorSpace = CGColorSpace(name: CGColorSpace.genericGrayGamma2_2),
        let context = CGContext(
            data: &pixels,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.none.rawValue
        )
    else {
        return 0.0
    }

    context.draw(maskCGImage, in: CGRect(x: 0, y: 0, width: width, height: height))

    let threshold: UInt8 = 16
    let nonZeroCount = pixels.reduce(0) { partial, value in
        partial + (value > threshold ? 1 : 0)
    }
    return Double(nonZeroCount) / Double(max(1, width * height))
}

func clamp01(_ value: Double) -> Double {
    min(max(value, 0.0), 1.0)
}

func clampRect(_ rect: CGRect, to bounds: CGRect) -> CGRect {
    let x = max(bounds.minX, rect.minX)
    let y = max(bounds.minY, rect.minY)
    let maxX = min(bounds.maxX, rect.maxX)
    let maxY = min(bounds.maxY, rect.maxY)
    if maxX <= x || maxY <= y {
        return .null
    }
    return CGRect(x: x, y: y, width: maxX - x, height: maxY - y)
}

func rgbToLuma(r: Double, g: Double, b: Double) -> Double {
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

func sampleRectColorStats(cgImage: CGImage, rect: CGRect) -> (luma: Double, saturation: Double)? {
    let width = cgImage.width
    let height = cgImage.height
    guard width > 0, height > 0 else {
        return nil
    }

    var rgbaPixels = [UInt8](repeating: 0, count: width * height * 4)
    guard
        let rgbColorSpace = CGColorSpace(name: CGColorSpace.sRGB),
        let rgbContext = CGContext(
            data: &rgbaPixels,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: rgbColorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )
    else {
        return nil
    }

    rgbContext.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

    let sampleRect = rect.integral
    let startX = max(0, Int(sampleRect.minX))
    let startY = max(0, Int(sampleRect.minY))
    let endX = min(width, Int(sampleRect.maxX))
    let endY = min(height, Int(sampleRect.maxY))
    guard startX < endX, startY < endY else {
        return nil
    }

    let step = max(1, min(endX - startX, endY - startY) / 24)
    var lumaSum = 0.0
    var saturationSum = 0.0
    var count = 0

    for y in stride(from: startY, to: endY, by: step) {
        for x in stride(from: startX, to: endX, by: step) {
            let rgbaIndex = (y * width + x) * 4
            let r = Double(rgbaPixels[rgbaIndex]) / 255.0
            let g = Double(rgbaPixels[rgbaIndex + 1]) / 255.0
            let b = Double(rgbaPixels[rgbaIndex + 2]) / 255.0
            let a = Double(rgbaPixels[rgbaIndex + 3]) / 255.0
            guard a > 0.1 else { continue }

            let hsv = rgbToHSV(r: r, g: g, b: b)
            lumaSum += rgbToLuma(r: r, g: g, b: b)
            saturationSum += hsv.s
            count += 1
        }
    }

    guard count > 0 else {
        return nil
    }

    return (lumaSum / Double(count), saturationSum / Double(count))
}

func shouldTreatTextBoxAsWatermark(_ rect: CGRect, imageSize: CGSize, options: RemoveBGOptions) -> Bool {
    let imageWidth = max(1.0, imageSize.width)
    let imageHeight = max(1.0, imageSize.height)
    let edgeMargin = min(imageWidth, imageHeight) * options.watermarkEdgeMarginRatio
    let maxArea = imageWidth * imageHeight * options.watermarkMaxAreaRatio
    let maxHeight = imageHeight * options.watermarkMaxHeightRatio
    let area = rect.width * rect.height
    let centerX = rect.midX / imageWidth
    let centerY = rect.midY / imageHeight

    let touchesEdge = rect.minX <= edgeMargin
        || rect.maxX >= imageWidth - edgeMargin
        || rect.minY <= edgeMargin
        || rect.maxY >= imageHeight - edgeMargin

    let inRightBottomQuadrant = centerX >= options.watermarkRightSideMinRatio
        && centerY <= options.watermarkBottomMaxRatio

    return touchesEdge && inRightBottomQuadrant && area <= maxArea && rect.height <= maxHeight
}

func buildTextMaskCIImage(size: CGSize, rects: [CGRect], blurRadius: Double) -> CIImage? {
    let width = Int(size.width)
    let height = Int(size.height)
    guard width > 0, height > 0, !rects.isEmpty else {
        return nil
    }

    var pixels = [UInt8](repeating: 0, count: width * height)
    guard
        let colorSpace = CGColorSpace(name: CGColorSpace.genericGrayGamma2_2),
        let context = CGContext(
            data: &pixels,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.none.rawValue
        )
    else {
        return nil
    }

    context.setFillColor(gray: 0.0, alpha: 1.0)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.setFillColor(gray: 1.0, alpha: 1.0)
    for rect in rects {
        context.fill(rect)
    }

    guard let maskCGImage = context.makeImage() else {
        return nil
    }

    var maskCIImage = CIImage(cgImage: maskCGImage)
    if blurRadius > 0, let blurFilter = CIFilter(name: "CIGaussianBlur") {
        blurFilter.setValue(maskCIImage, forKey: kCIInputImageKey)
        blurFilter.setValue(blurRadius, forKey: kCIInputRadiusKey)
        if let out = blurFilter.outputImage {
            maskCIImage = out.cropped(to: CGRect(origin: .zero, size: size))
        }
    }
    return maskCIImage
}

func attemptTextWatermarkRemoval(
    cgImage: CGImage,
    ciContext: CIContext,
    options: RemoveBGOptions
) -> CGImage? {
    guard options.watermarkRemovalEnabled else {
        return cgImage
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    request.minimumTextHeight = 0.01

    do {
        let handler = VNImageRequestHandler(cgImage: cgImage)
        try handler.perform([request])
        let observations = request.results ?? []
        if observations.isEmpty {
            return cgImage
        }

        let imageSize = CGSize(width: cgImage.width, height: cgImage.height)
        let imageBounds = CGRect(origin: .zero, size: imageSize)
        let padding = min(imageSize.width, imageSize.height) * options.watermarkBoxPaddingRatio
        var candidateRects: [CGRect] = []

        for observation in observations {
            guard let topCandidate = observation.topCandidates(1).first else {
                continue
            }
            if topCandidate.confidence < 0.25 {
                continue
            }

            let textRect = VNImageRectForNormalizedRect(observation.boundingBox, cgImage.width, cgImage.height)
            var expandedRect = textRect.insetBy(dx: -padding, dy: -padding)
            expandedRect = clampRect(expandedRect, to: imageBounds)
            if expandedRect.isNull {
                continue
            }

            if shouldTreatTextBoxAsWatermark(expandedRect, imageSize: imageSize, options: options) {
                candidateRects.append(expandedRect)
            }
        }

        if candidateRects.isEmpty {
            return cgImage
        }

        guard let maskCIImage = buildTextMaskCIImage(
            size: imageSize,
            rects: candidateRects,
            blurRadius: max(0.0, options.watermarkRepairRadius * 0.35)
        ) else {
            return cgImage
        }

        let originalCIImage = CIImage(cgImage: cgImage)
        var repairedCIImage = originalCIImage
        if let medianFilter = CIFilter(name: "CIMedianFilter") {
            medianFilter.setValue(repairedCIImage, forKey: kCIInputImageKey)
            if let out = medianFilter.outputImage {
                repairedCIImage = out.cropped(to: imageBounds)
            }
        }
        if options.watermarkRepairRadius > 0, let blurFilter = CIFilter(name: "CIGaussianBlur") {
            blurFilter.setValue(repairedCIImage, forKey: kCIInputImageKey)
            blurFilter.setValue(options.watermarkRepairRadius, forKey: kCIInputRadiusKey)
            if let out = blurFilter.outputImage {
                repairedCIImage = out.cropped(to: imageBounds)
            }
        }

        guard let blendFilter = CIFilter(name: "CIBlendWithMask") else {
            return cgImage
        }
        blendFilter.setValue(repairedCIImage, forKey: kCIInputImageKey)
        blendFilter.setValue(maskCIImage, forKey: kCIInputMaskImageKey)
        blendFilter.setValue(originalCIImage, forKey: kCIInputBackgroundImageKey)

        guard let outputCIImage = blendFilter.outputImage?.cropped(to: imageBounds),
              let outputCGImage = ciContext.createCGImage(outputCIImage, from: imageBounds) else {
            return cgImage
        }

        fputs("   ℹ️ 检测到疑似文字水印区域 \(candidateRects.count) 处，已执行预处理\n", stderr)
        return outputCGImage
    } catch {
        fputs("   ⚠️ 文字水印预处理失败，已跳过: \(error)\n", stderr)
        return cgImage
    }
}

func generateVisionMask(cgImage: CGImage) throws -> (maskCIImage: CIImage, foregroundRatio: Double) {
    let request = VNGenerateForegroundInstanceMaskRequest()
    let handler = VNImageRequestHandler(cgImage: cgImage)
    try handler.perform([request])

    guard let result = request.results?.first else {
        throw NSError(domain: "RemoveBG", code: 1, userInfo: [NSLocalizedDescriptionKey: "未检测到前景主体"])
    }

    let maskPixelBuffer = try result.generateScaledMaskForImage(forInstances: result.allInstances, from: handler)
    let foregroundRatio = estimateForegroundRatio(maskPixelBuffer: maskPixelBuffer)
    return (CIImage(cvPixelBuffer: maskPixelBuffer), foregroundRatio)
}

func generateChromaKeyMaskCGImage(cgImage: CGImage, options: RemoveBGOptions) -> CGImage? {
    let width = cgImage.width
    let height = cgImage.height
    guard width > 0, height > 0 else {
        return nil
    }

    var rgbaPixels = [UInt8](repeating: 0, count: width * height * 4)
    guard
        let rgbColorSpace = CGColorSpace(name: CGColorSpace.sRGB),
        let rgbContext = CGContext(
            data: &rgbaPixels,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: rgbColorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )
    else {
        return nil
    }

    rgbContext.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

    let threshold = options.chromaKeyThreshold
    let softness = max(0.001, options.chromaKeySoftness)
    let minimumGreen = max(0.0, min(options.chromaKeyMinimumGreen, 1.0))

    var maskPixels = [UInt8](repeating: 0, count: width * height)
    for pixelIndex in 0..<(width * height) {
        let rgbaIndex = pixelIndex * 4
        let r = Double(rgbaPixels[rgbaIndex]) / 255.0
        let g = Double(rgbaPixels[rgbaIndex + 1]) / 255.0
        let b = Double(rgbaPixels[rgbaIndex + 2]) / 255.0
        let a = Double(rgbaPixels[rgbaIndex + 3]) / 255.0

        let dominance = g - max(r, b)
        let greenRatio = g / max(0.0001, r + g + b)

        var backgroundScore = clamp01((dominance - threshold) / softness)
        if greenRatio < minimumGreen {
            backgroundScore *= clamp01(greenRatio / max(0.0001, minimumGreen))
        }

        let foregroundAlpha = clamp01((1.0 - backgroundScore) * a)
        maskPixels[pixelIndex] = UInt8(clamp01(foregroundAlpha) * 255.0)
    }

    guard
        let grayColorSpace = CGColorSpace(name: CGColorSpace.genericGrayGamma2_2),
        let provider = CGDataProvider(data: Data(maskPixels) as CFData)
    else {
        return nil
    }

    return CGImage(
        width: width,
        height: height,
        bitsPerComponent: 8,
        bitsPerPixel: 8,
        bytesPerRow: width,
        space: grayColorSpace,
        bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
        provider: provider,
        decode: nil,
        shouldInterpolate: false,
        intent: .defaultIntent
    )
}

func generateAutoHueMaskCGImage(cgImage: CGImage, targetHue: Double, options: RemoveBGOptions) -> CGImage? {
    let width = cgImage.width
    let height = cgImage.height
    guard width > 0, height > 0 else {
        return nil
    }

    var rgbaPixels = [UInt8](repeating: 0, count: width * height * 4)
    guard
        let rgbColorSpace = CGColorSpace(name: CGColorSpace.sRGB),
        let rgbContext = CGContext(
            data: &rgbaPixels,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: rgbColorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )
    else {
        return nil
    }

    rgbContext.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

    let threshold = max(0.0, min(options.chromaKeyThreshold, 0.5))
    let softness = max(0.001, min(options.chromaKeySoftness, 0.5))
    let minSaturation = max(0.0, min(options.chromaKeyMinimumGreen, 1.0))

    var maskPixels = [UInt8](repeating: 0, count: width * height)
    for pixelIndex in 0..<(width * height) {
        let rgbaIndex = pixelIndex * 4
        let r = Double(rgbaPixels[rgbaIndex]) / 255.0
        let g = Double(rgbaPixels[rgbaIndex + 1]) / 255.0
        let b = Double(rgbaPixels[rgbaIndex + 2]) / 255.0
        let a = Double(rgbaPixels[rgbaIndex + 3]) / 255.0

        let hsv = rgbToHSV(r: r, g: g, b: b)
        let dist = hueCircularDistance(hsv.h, targetHue)
        let hueMatch = 1.0 - clamp01((dist - threshold) / softness)
        let satGate = clamp01((hsv.s - minSaturation) / max(0.001, 1.0 - minSaturation))
        let valueGate = clamp01((hsv.v - 0.05) / 0.95)

        // 距离目标色相越近、饱和度越高，越倾向判定为背景
        let backgroundScore = clamp01(hueMatch * satGate * valueGate)
        let foregroundAlpha = clamp01((1.0 - backgroundScore) * a)
        maskPixels[pixelIndex] = UInt8(foregroundAlpha * 255.0)
    }

    guard
        let grayColorSpace = CGColorSpace(name: CGColorSpace.genericGrayGamma2_2),
        let provider = CGDataProvider(data: Data(maskPixels) as CFData)
    else {
        return nil
    }

    return CGImage(
        width: width,
        height: height,
        bitsPerComponent: 8,
        bitsPerPixel: 8,
        bytesPerRow: width,
        space: grayColorSpace,
        bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
        provider: provider,
        decode: nil,
        shouldInterpolate: false,
        intent: .defaultIntent
    )
}

func runProcess(executablePath: String, arguments: [String]) -> Bool {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executablePath)
    process.arguments = arguments

    do {
        try process.run()
        process.waitUntilExit()
        return process.terminationStatus == 0
    } catch {
        return false
    }
}

func findPythonWithPillow() -> String? {
    let currentDir = FileManager.default.currentDirectoryPath
    let env = ProcessInfo.processInfo.environment
    let candidates = [
        env["REMOVEBG_WEBP_PYTHON"],
        (currentDir as NSString).appendingPathComponent(".venv/bin/python3"),
        (currentDir as NSString).appendingPathComponent("../.venv/bin/python3"),
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ].compactMap { $0 }

    for candidate in candidates {
        guard FileManager.default.fileExists(atPath: candidate) else {
            continue
        }
        if runProcess(executablePath: candidate, arguments: ["-c", "import PIL"]) {
            return candidate
        }
    }
    return nil
}

func writeImageViaImageIO(cgImage: CGImage, outputPath: String, format: OutputFormat, webpQuality: Int) -> Bool {
    let outputURL = URL(fileURLWithPath: outputPath)
    guard let typeIdentifier = format.utTypeIdentifier else {
        return false
    }

    guard let destination = CGImageDestinationCreateWithURL(
        outputURL as CFURL,
        typeIdentifier,
        1,
        nil
    ) else {
        return false
    }

    let imageProps: [CFString: Any]
    switch format {
    case .png:
        let pngProps: [CFString: Any] = [
            kCGImagePropertyPNGCompressionFilter: 5,
            kCGImagePropertyPNGInterlaceType: 0,
        ]
        imageProps = [
            kCGImagePropertyPNGDictionary: pngProps
        ]
    case .webp:
        imageProps = [
            kCGImageDestinationLossyCompressionQuality: Double(webpQuality) / 100.0
        ]
    }

    CGImageDestinationAddImage(destination, cgImage, imageProps as CFDictionary)
    return CGImageDestinationFinalize(destination)
}

func writeWebPWithPythonFallback(cgImage: CGImage, outputPath: String, webpQuality: Int) -> Bool {
    guard let pythonPath = findPythonWithPillow() else {
        fputs("   ❌ 当前系统不支持原生 WEBP 写出，且未找到可用的 Python Pillow 环境\n", stderr)
        return false
    }

    let tempPNGPath = outputPath + ".tmp.png"
    defer {
        try? FileManager.default.removeItem(atPath: tempPNGPath)
    }

    guard writeImageViaImageIO(cgImage: cgImage, outputPath: tempPNGPath, format: .png, webpQuality: webpQuality) else {
        fputs("   ❌ WEBP 回退编码前的临时 PNG 写入失败\n", stderr)
        return false
    }

    let script = "import sys; from PIL import Image; img = Image.open(sys.argv[1]).convert('RGBA'); img.save(sys.argv[2], format='WEBP', quality=int(sys.argv[3]), method=6)"
    let ok = runProcess(executablePath: pythonPath, arguments: ["-c", script, tempPNGPath, outputPath, String(webpQuality)])
    if !ok {
        fputs("   ❌ Python Pillow WEBP 编码失败\n", stderr)
    }
    return ok
}

// MARK: - 辅助函数：确保输出路径的后缀符合目标格式
func forceOutputExtension(for path: String, format: OutputFormat) -> String {
    let nsPath = path as NSString
    let ext = nsPath.pathExtension.lowercased()
    if ext == format.fileExtension {
        return path
    }
    let dir = nsPath.deletingLastPathComponent
    let filename = nsPath.deletingPathExtension
    return (dir as NSString).appendingPathComponent("\(filename).\(format.fileExtension)")
}

// MARK: - 图片写入
func writeImage(cgImage: CGImage, outputPath: String, format: OutputFormat, webpQuality: Int) -> Bool {
    switch format {
    case .png:
        guard writeImageViaImageIO(cgImage: cgImage, outputPath: outputPath, format: .png, webpQuality: webpQuality) else {
            fputs("   ❌ PNG 写入失败\n", stderr)
            return false
        }
        return true
    case .webp:
        if writeImageViaImageIO(cgImage: cgImage, outputPath: outputPath, format: .webp, webpQuality: webpQuality) {
            return true
        }
        return writeWebPWithPythonFallback(cgImage: cgImage, outputPath: outputPath, webpQuality: webpQuality)
    }
}

func tryOptimizePNGWithPngquant(filePath: String) {
    // 默认关闭；设置环境变量 REMOVEBG_PNGQUANT=1 时启用。
    guard ProcessInfo.processInfo.environment["REMOVEBG_PNGQUANT"] == "1" else {
        return
    }

    let candidates = [
        "/opt/homebrew/bin/pngquant",
        "/usr/local/bin/pngquant",
        "/usr/bin/pngquant",
    ]
    guard let pngquantPath = candidates.first(where: { FileManager.default.fileExists(atPath: $0) }) else {
        fputs("   ⚠️ 已启用 REMOVEBG_PNGQUANT=1，但未找到 pngquant，可安装后重试\n", stderr)
        return
    }

    let process = Process()
    process.executableURL = URL(fileURLWithPath: pngquantPath)
    process.arguments = [
        "--force",
        "--skip-if-larger",
        "--quality=65-90",
        "--output",
        filePath,
        filePath,
    ]

    do {
        try process.run()
        process.waitUntilExit()
    } catch {
        fputs("   ⚠️ pngquant 压缩执行失败: \(error)\n", stderr)
    }
}

// MARK: - 核心逻辑：处理单张图片
func processSingleImage(
    inputPath: String,
    outputPath: String,
    outputFormat: OutputFormat,
    webpQuality: Int,
    options: RemoveBGOptions
) -> Bool {
    // 命令行工具批量处理大量图片时，显式包一层 autoreleasepool，
    // 避免 AppKit/CoreImage/Vision 临时对象累计过多。
    return autoreleasepool {
        guard let inputNSImage = NSImage(contentsOfFile: inputPath) else {
            fputs("   ❌ 无法读取图片: \(inputPath)\n", stderr)
            return false
        }

        guard let cgImage = inputNSImage.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            fputs("   ❌ 无法转换为 CGImage\n", stderr)
            return false
        }
        let ciContext = CIContext(options: [.useSoftwareRenderer: false])
        let preprocessedCGImage = attemptTextWatermarkRemoval(cgImage: cgImage, ciContext: ciContext, options: options) ?? cgImage
        let originalCIImage = CIImage(cgImage: preprocessedCGImage)
        let extent = originalCIImage.extent

        do {
            let maskCIImage: CIImage
            let foregroundRatio: Double

            switch options.backgroundMode {
            case .vision:
                let visionMask = try generateVisionMask(cgImage: preprocessedCGImage)
                maskCIImage = visionMask.maskCIImage
                foregroundRatio = visionMask.foregroundRatio
            case .chromaKey:
                guard let chromaMaskCGImage = generateChromaKeyMaskCGImage(cgImage: preprocessedCGImage, options: options) else {
                    fputs("   ❌ 绿幕抠图 mask 生成失败\n", stderr)
                    return false
                }
                maskCIImage = CIImage(cgImage: chromaMaskCGImage)
                foregroundRatio = estimateForegroundRatio(maskCGImage: chromaMaskCGImage)
            case .hybrid:
                guard let chromaMaskCGImage = generateChromaKeyMaskCGImage(cgImage: preprocessedCGImage, options: options) else {
                    fputs("   ❌ hybrid 模式下绿幕 mask 生成失败\n", stderr)
                    return false
                }

                let chromaMaskCIImage = CIImage(cgImage: chromaMaskCGImage)
                let chromaRatio = estimateForegroundRatio(maskCGImage: chromaMaskCGImage)

                if let maximumFilter = CIFilter(name: "CIMaximumCompositing") {
                    do {
                        let visionMask = try generateVisionMask(cgImage: preprocessedCGImage)
                        maximumFilter.setValue(visionMask.maskCIImage, forKey: kCIInputImageKey)
                        maximumFilter.setValue(chromaMaskCIImage, forKey: kCIInputBackgroundImageKey)
                        maskCIImage = maximumFilter.outputImage ?? chromaMaskCIImage
                        foregroundRatio = max(visionMask.foregroundRatio, chromaRatio)
                    } catch {
                        fputs("   ⚠️ Vision mask 生成失败，hybrid 模式回退为纯绿幕抠图: \(error)\n", stderr)
                        maskCIImage = chromaMaskCIImage
                        foregroundRatio = chromaRatio
                    }
                } else {
                    maskCIImage = chromaMaskCIImage
                    foregroundRatio = chromaRatio
                }
            case .autoChromaKey:
                // 自动检测背景主色相，并按色相环距离生成 mask
                if let hue = detectDominantEdgeHue(cgImage: preprocessedCGImage) {
                    // 基于已有参数作为“调节旋钮”来控制色相距离阈值/过渡和最低饱和度
                    let threshold = max(0.02, min(options.chromaKeyThreshold, 0.25))
                    let softness = max(0.03, min(options.chromaKeySoftness, 0.30))
                    let minSaturation = max(0.05, min(options.chromaKeyMinimumGreen, 0.85))
                    let autoOptions = RemoveBGOptions(
                        backgroundMode: .autoChromaKey,
                        maskDilateRadius: options.maskDilateRadius,
                        maskBlurRadius: options.maskBlurRadius,
                        minForegroundRatio: options.minForegroundRatio,
                        chromaKeyThreshold: threshold,
                        chromaKeySoftness: max(0.05, softness),
                        chromaKeyMinimumGreen: minSaturation,
                        watermarkRemovalEnabled: options.watermarkRemovalEnabled,
                        watermarkMinConfidence: options.watermarkMinConfidence,
                        watermarkEdgeMarginRatio: options.watermarkEdgeMarginRatio,
                        watermarkMaxAreaRatio: options.watermarkMaxAreaRatio,
                        watermarkMaxHeightRatio: options.watermarkMaxHeightRatio,
                        watermarkRightSideMinRatio: options.watermarkRightSideMinRatio,
                        watermarkBottomMaxRatio: options.watermarkBottomMaxRatio,
                        watermarkMinLuma: options.watermarkMinLuma,
                        watermarkMaxSaturation: options.watermarkMaxSaturation,
                        watermarkBoxPaddingRatio: options.watermarkBoxPaddingRatio,
                        watermarkRepairRadius: options.watermarkRepairRadius
                    )
                    guard let chromaMaskCGImage = generateAutoHueMaskCGImage(cgImage: preprocessedCGImage, targetHue: hue, options: autoOptions) else {
                        fputs("   ❌ autoChromaKey 模式下自动色相 mask 生成失败\n", stderr)
                        return false
                    }
                    maskCIImage = CIImage(cgImage: chromaMaskCGImage)
                    foregroundRatio = estimateForegroundRatio(maskCGImage: chromaMaskCGImage)
                    fputs("   ℹ️ 自动检测主色相: \(String(format: "%.3f", hue)), hueThreshold: \(String(format: "%.3f", threshold)), hueSoftness: \(String(format: "%.3f", softness)), minSaturation: \(String(format: "%.3f", minSaturation))\n", stderr)
                } else {
                    fputs("   ❌ autoChromaKey: 主色相检测失败，回退为绿色 chromaKey 参数\n", stderr)
                    guard let chromaMaskCGImage = generateChromaKeyMaskCGImage(cgImage: preprocessedCGImage, options: options) else {
                        fputs("   ❌ autoChromaKey 回退也失败\n", stderr)
                        return false
                    }
                    maskCIImage = CIImage(cgImage: chromaMaskCGImage)
                    foregroundRatio = estimateForegroundRatio(maskCGImage: chromaMaskCGImage)
                }
            }

            if options.minForegroundRatio > 0, foregroundRatio < options.minForegroundRatio {
                fputs("   ⚠️ 前景占比过低(\(String(format: "%.3f", foregroundRatio)))，保留原图: \(inputPath)\n", stderr)

                let outputDir = (outputPath as NSString).deletingLastPathComponent
                if !FileManager.default.fileExists(atPath: outputDir) {
                    try? FileManager.default.createDirectory(atPath: outputDir, withIntermediateDirectories: true)
                }

                guard writeImage(cgImage: preprocessedCGImage, outputPath: outputPath, format: outputFormat, webpQuality: webpQuality) else {
                    return false
                }
                if outputFormat == .png {
                    tryOptimizePNGWithPngquant(filePath: outputPath)
                }
                return true
            }

            var workingMaskCIImage = maskCIImage

            if options.maskDilateRadius > 0,
               let dilateFilter = CIFilter(name: "CIMorphologyMaximum") {
                dilateFilter.setValue(workingMaskCIImage, forKey: kCIInputImageKey)
                dilateFilter.setValue(options.maskDilateRadius, forKey: kCIInputRadiusKey)
                if let out = dilateFilter.outputImage {
                    workingMaskCIImage = out
                }
            }

            if options.maskBlurRadius > 0,
               let blurFilter = CIFilter(name: "CIGaussianBlur") {
                blurFilter.setValue(workingMaskCIImage, forKey: kCIInputImageKey)
                blurFilter.setValue(options.maskBlurRadius, forKey: kCIInputRadiusKey)
                if let out = blurFilter.outputImage {
                    workingMaskCIImage = out
                }
            }

            workingMaskCIImage = workingMaskCIImage.cropped(to: extent)
            let clearImage = CIImage(color: CIColor.clear).cropped(to: extent)

            guard let filter = CIFilter(name: "CIBlendWithMask") else { return false }
            filter.setValue(originalCIImage, forKey: kCIInputImageKey)
            filter.setValue(workingMaskCIImage, forKey: kCIInputMaskImageKey)
            filter.setValue(clearImage,       forKey: kCIInputBackgroundImageKey)

            guard let outputCIImage = filter.outputImage else { return false }
            
            let outputExtent = outputCIImage.extent
            guard let outputCGImage = ciContext.createCGImage(outputCIImage, from: outputExtent) else {
                return false
            }

            let outputDir = (outputPath as NSString).deletingLastPathComponent
            if !FileManager.default.fileExists(atPath: outputDir) {
                try? FileManager.default.createDirectory(atPath: outputDir, withIntermediateDirectories: true)
            }

            guard writeImage(cgImage: outputCGImage, outputPath: outputPath, format: outputFormat, webpQuality: webpQuality) else {
                return false
            }
            if outputFormat == .png {
                tryOptimizePNGWithPngquant(filePath: outputPath)
            }
            return true

        } catch {
            fputs("   ❌ Vision 引擎执行出错: \(error)\n", stderr)
            return false
        }
    } // end autoreleasepool
}

// ==========================================
// MARK: - 命令行参数解析与主流程
// ==========================================

let args = CommandLine.arguments

guard args.count >= 4 else {
    print("""
    ╔════════════════════════════════════════════════════════════════════════════╗
    ║   Usage: removebg <type> <input> <output> [--outputFmt png|webp]          ║
    ║                                          [--webpQuality 0-100]             ║
    ║                                          [--bgMode vision|chromaKey|hybrid|autoChromaKey]║
    ║                                          [--maskDilate 0-50]               ║
    ║                                          [--maskBlur 0-20]                 ║
    ║                                          [--minForegroundRatio 0-1]        ║
    ║                                          [--greenThreshold 0-1]            ║
    ║                                          [--greenSoftness 0-1]             ║
    ║                                          [--greenMinRatio 0-1]             ║
    ║                                          [--watermarkRemoval on|off]       ║
    ║                                          [--watermarkMinConfidence 0-1]    ║
    ║                                          [--watermarkRightSideMin 0-1]     ║
    ║                                          [--watermarkBottomMax 0-1]        ║
    ║                                          [--watermarkMinLuma 0-1]          ║
    ║                                          [--watermarkMaxSaturation 0-1]    ║
    ║                                          [--watermarkMaxAreaRatio 0-1]     ║
    ║                                          [--watermarkMaxHeightRatio 0-1]   ║
    ║                                          [--watermarkRepairRadius 0-30]    ║
    ║                                                                            ║
    ║   type=0: 单图模式                                                          ║
    ║     removebg 0 input.jpg output.png                                         ║
    ║     removebg 0 input.jpg output.webp --outputFmt webp --webpQuality 80      ║
    ║                                                                            ║
    ║   type=1: 批量模式 (输入输出必须为文件夹)                                     ║
    ║     removebg 1 ./input_folder/ ./output_folder/                             ║
    ║     removebg 1 ./input_folder/ ./output_folder/ --outputFmt webp            ║
    ║                   --webpQuality 80                                           ║
    ╚════════════════════════════════════════════════════════════════════════════╝
    """)
    exit(1)
}

let typeStr    = args[1]
let inputPath  = args[2]
var outputPath = args[3]

var outputFormat: OutputFormat = .webp
var webpQuality = 82
var backgroundMode: BackgroundMode = .vision
var maskDilate: Double = 0
var maskBlur: Double = 0
var minForegroundRatio: Double = 0
var greenThreshold: Double = 0.08
var greenSoftness: Double = 0.18
var greenMinRatio: Double = 0.38
var watermarkRemovalEnabled = false
var watermarkMinConfidence: Double = 0.6
var watermarkEdgeMarginRatio: Double = 0.16
var watermarkMaxAreaRatio: Double = 0.1
var watermarkMaxHeightRatio: Double = 0.1
var watermarkRightSideMinRatio: Double = 0.6
var watermarkBottomMaxRatio: Double = 0.3
var watermarkMinLuma: Double = 0.56
var watermarkMaxSaturation: Double = 0.5
var watermarkBoxPaddingRatio: Double = 0.01
var watermarkRepairRadius: Double = 10.0
guard (args.count - 4) % 2 == 0 else {
    fputs("❌ 可选参数必须成对出现，例如 --outputFmt webp --webpQuality 80\n", stderr)
    exit(1)
}

var optionIndex = 4
while optionIndex < args.count {
    let option = args[optionIndex]
    let value = args[optionIndex + 1]

    switch option {
    case "--outputFmt":
        guard let parsedFormat = OutputFormat(rawValue: value.lowercased()) else {
            fputs("❌ --outputFmt 仅支持 png 或 webp\n", stderr)
            exit(1)
        }
        outputFormat = parsedFormat
    case "--webpQuality":
        guard let parsedQuality = Int(value), (0...100).contains(parsedQuality) else {
            fputs("❌ --webpQuality 必须是 0 到 100 之间的整数\n", stderr)
            exit(1)
        }
        webpQuality = parsedQuality
    case "--bgMode":
        guard let parsedMode = BackgroundMode.parse(value) else {
            fputs("❌ --bgMode 仅支持 vision、chromaKey、hybrid、autoChromaKey\n", stderr)
            exit(1)
        }
        backgroundMode = parsedMode
    case "--maskDilate":
        guard let parsedDilate = Double(value), (0...50).contains(parsedDilate) else {
            fputs("❌ --maskDilate 必须是 0 到 50 之间的数字\n", stderr)
            exit(1)
        }
        maskDilate = parsedDilate
    case "--maskBlur":
        guard let parsedBlur = Double(value), (0...20).contains(parsedBlur) else {
            fputs("❌ --maskBlur 必须是 0 到 20 之间的数字\n", stderr)
            exit(1)
        }
        maskBlur = parsedBlur
    case "--minForegroundRatio":
        guard let parsedRatio = Double(value), (0...1).contains(parsedRatio) else {
            fputs("❌ --minForegroundRatio 必须是 0 到 1 之间的数字\n", stderr)
            exit(1)
        }
        minForegroundRatio = parsedRatio
    case "--greenThreshold":
        guard let parsedThreshold = Double(value), (0...1).contains(parsedThreshold) else {
            fputs("❌ --greenThreshold 必须是 0 到 1 之间的数字\n", stderr)
            exit(1)
        }
        greenThreshold = parsedThreshold
    case "--greenSoftness":
        guard let parsedSoftness = Double(value), (0...1).contains(parsedSoftness), parsedSoftness > 0 else {
            fputs("❌ --greenSoftness 必须是大于 0 且不超过 1 的数字\n", stderr)
            exit(1)
        }
        greenSoftness = parsedSoftness
    case "--greenMinRatio":
        guard let parsedGreenRatio = Double(value), (0...1).contains(parsedGreenRatio) else {
            fputs("❌ --greenMinRatio 必须是 0 到 1 之间的数字\n", stderr)
            exit(1)
        }
        greenMinRatio = parsedGreenRatio
    case "--watermarkRemoval":
        switch value.lowercased() {
        case "on", "true", "1":
            watermarkRemovalEnabled = true
        case "off", "false", "0":
            watermarkRemovalEnabled = false
        default:
            fputs("❌ --watermarkRemoval 仅支持 on/off\n", stderr)
            exit(1)
        }
    case "--watermarkMinConfidence":
        guard let parsedValue = Double(value), (0...1).contains(parsedValue) else {
            fputs("❌ --watermarkMinConfidence 必须是 0 到 1 之间的数字\n", stderr)
            exit(1)
        }
        watermarkMinConfidence = parsedValue
    case "--watermarkRightSideMin":
        guard let parsedValue = Double(value), (0...1).contains(parsedValue) else {
            fputs("❌ --watermarkRightSideMin 必须是 0 到 1 之间的数字\n", stderr)
            exit(1)
        }
        watermarkRightSideMinRatio = parsedValue
    case "--watermarkBottomMax":
        guard let parsedValue = Double(value), (0...1).contains(parsedValue) else {
            fputs("❌ --watermarkBottomMax 必须是 0 到 1 之间的数字\n", stderr)
            exit(1)
        }
        watermarkBottomMaxRatio = parsedValue
    case "--watermarkMinLuma":
        guard let parsedValue = Double(value), (0...1).contains(parsedValue) else {
            fputs("❌ --watermarkMinLuma 必须是 0 到 1 之间的数字\n", stderr)
            exit(1)
        }
        watermarkMinLuma = parsedValue
    case "--watermarkMaxSaturation":
        guard let parsedValue = Double(value), (0...1).contains(parsedValue) else {
            fputs("❌ --watermarkMaxSaturation 必须是 0 到 1 之间的数字\n", stderr)
            exit(1)
        }
        watermarkMaxSaturation = parsedValue
    case "--watermarkMaxAreaRatio":
        guard let parsedValue = Double(value), (0...1).contains(parsedValue), parsedValue > 0 else {
            fputs("❌ --watermarkMaxAreaRatio 必须是大于 0 且不超过 1 的数字\n", stderr)
            exit(1)
        }
        watermarkMaxAreaRatio = parsedValue
    case "--watermarkMaxHeightRatio":
        guard let parsedValue = Double(value), (0...1).contains(parsedValue), parsedValue > 0 else {
            fputs("❌ --watermarkMaxHeightRatio 必须是大于 0 且不超过 1 的数字\n", stderr)
            exit(1)
        }
        watermarkMaxHeightRatio = parsedValue
    case "--watermarkRepairRadius":
        guard let parsedRadius = Double(value), (0...30).contains(parsedRadius) else {
            fputs("❌ --watermarkRepairRadius 必须是 0 到 30 之间的数字\n", stderr)
            exit(1)
        }
        watermarkRepairRadius = parsedRadius
    default:
        fputs("❌ 未知参数: \(option)\n", stderr)
        exit(1)
    }

    optionIndex += 2
}

guard typeStr == "0" || typeStr == "1" else {
    fputs("❌ type 参数错误，只能是 0 或 1\n", stderr)
    exit(1)
}

let fileManager = FileManager.default
let removeBGOptions = RemoveBGOptions(
    backgroundMode: backgroundMode,
    maskDilateRadius: maskDilate,
    maskBlurRadius: maskBlur,
    minForegroundRatio: minForegroundRatio,
    chromaKeyThreshold: greenThreshold,
    chromaKeySoftness: greenSoftness,
    chromaKeyMinimumGreen: greenMinRatio,
    watermarkRemovalEnabled: watermarkRemovalEnabled,
    watermarkMinConfidence: watermarkMinConfidence,
    watermarkEdgeMarginRatio: watermarkEdgeMarginRatio,
    watermarkMaxAreaRatio: watermarkMaxAreaRatio,
    watermarkMaxHeightRatio: watermarkMaxHeightRatio,
    watermarkRightSideMinRatio: watermarkRightSideMinRatio,
    watermarkBottomMaxRatio: watermarkBottomMaxRatio,
    watermarkMinLuma: watermarkMinLuma,
    watermarkMaxSaturation: watermarkMaxSaturation,
    watermarkBoxPaddingRatio: watermarkBoxPaddingRatio,
    watermarkRepairRadius: watermarkRepairRadius
)

// --------------------------------------------------
// 模式 0：单张图片处理
// --------------------------------------------------
if typeStr == "0" {
    var isDir: ObjCBool = false
    guard fileManager.fileExists(atPath: inputPath, isDirectory: &isDir), !isDir.boolValue else {
        fputs("❌ type=0 时，输入路径必须是一个具体的图片文件\n", stderr)
        exit(1)
    }
    
    outputPath = forceOutputExtension(for: outputPath, format: outputFormat)
    
    print("📸 开始处理单张图片，输出格式: \(outputFormat.displayName)，背景模式: \(backgroundMode.displayName)...")
    if processSingleImage(
        inputPath: inputPath,
        outputPath: outputPath,
        outputFormat: outputFormat,
        webpQuality: webpQuality,
        options: removeBGOptions
    ) {
        print("✅ 抠图完成，已保存至: \(outputPath)")
    } else {
        fputs("❌ 处理失败\n", stderr)
        exit(1)
    }
}

// --------------------------------------------------
// 模式 1：批量文件夹处理
// --------------------------------------------------
else if typeStr == "1" {
    var isInputDir: ObjCBool = false
    var isOutputDir: ObjCBool = false
    
    guard fileManager.fileExists(atPath: inputPath, isDirectory: &isInputDir), isInputDir.boolValue else {
        fputs("❌ type=1 时，输入路径必须是一个存在的文件夹\n", stderr)
        exit(1)
    }
    
    if !fileManager.fileExists(atPath: outputPath, isDirectory: &isOutputDir) {
        print("📁 目标文件夹不存在，自动创建: \(outputPath)")
        try? fileManager.createDirectory(atPath: outputPath, withIntermediateDirectories: true)
    } else if !isOutputDir.boolValue {
        fputs("❌ type=1 时，输出路径必须是一个文件夹，不能是文件\n", stderr)
        exit(1)
    }
    
    guard let files = try? fileManager.contentsOfDirectory(atPath: inputPath) else {
        fputs("❌ 无法读取输入文件夹内容\n", stderr)
        exit(1)
    }
    
    let supportedExtensions: Set<String> = ["jpg", "jpeg", "png", "webp", "tiff", "tif", "bmp", "heic"]
    
    let imageFiles = files.filter { fileName in
        let ext = (fileName as NSString).pathExtension.lowercased()
        return supportedExtensions.contains(ext) && !fileName.hasPrefix(".")
    }
    
    if imageFiles.isEmpty {
        print("⚠️ 在 \(inputPath) 中没有找到支持格式的图片文件。")
        exit(0)
    }
    
    let workerCount = max(1, ProcessInfo.processInfo.activeProcessorCount)
    print("🚀 发现 \(imageFiles.count) 张图片，开始批量处理，输出格式: \(outputFormat.displayName)，背景模式: \(backgroundMode.displayName)，并发线程: \(workerCount)...\n")
    
    var successCount = 0
    var failCount = 0
    
    let statsQueue = DispatchQueue(label: "removebg.stats")
    let logQueue = DispatchQueue(label: "removebg.log")
    let queue = OperationQueue()
    queue.maxConcurrentOperationCount = workerCount
    queue.qualityOfService = .userInitiated

    for (index, fileName) in imageFiles.enumerated() {
        queue.addOperation {
            let fullInputPath = (inputPath as NSString).appendingPathComponent(fileName)
            let filenameWithoutExt = (fileName as NSString).deletingPathExtension
            let outputFileName = "\(filenameWithoutExt).\(outputFormat.fileExtension)"
            let fullOutputPath = (outputPath as NSString).appendingPathComponent(outputFileName)

            if fileManager.fileExists(atPath: fullOutputPath) {
                logQueue.sync {
                    print("[\(index + 1)/\(imageFiles.count)] ⏭️  跳过已存在: \(outputFileName)")
                }
                statsQueue.sync {
                    successCount += 1
                }
                return
            }

            logQueue.sync {
                print("[\(index + 1)/\(imageFiles.count)] 🧠 处理中: \(fileName) -> \(outputFileName)")
            }

            // processSingleImage 内部有 autoreleasepool，适合并发批处理
            let ok = processSingleImage(
                inputPath: fullInputPath,
                outputPath: fullOutputPath,
                outputFormat: outputFormat,
                webpQuality: webpQuality,
                options: removeBGOptions
            )
            statsQueue.sync {
                if ok {
                    successCount += 1
                } else {
                    failCount += 1
                }
            }
        }
    }

    queue.waitUntilAllOperationsAreFinished()
    
    print("\n🎉 批量处理完成！")
    print("   ✅ 成功: \(successCount) 张")
    if failCount > 0 {
        print("   ❌ 失败: \(failCount) 张")
    }
}
