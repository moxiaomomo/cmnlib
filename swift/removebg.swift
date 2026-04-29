import Foundation
import Vision
import CoreImage
import AppKit
import ImageIO
import UniformTypeIdentifiers

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
func processSingleImage(inputPath: String, outputPath: String, outputFormat: OutputFormat, webpQuality: Int) -> Bool {
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

        let request = VNGenerateForegroundInstanceMaskRequest()

        do {
            let handler = VNImageRequestHandler(cgImage: cgImage)
            try handler.perform([request])

            guard let result = request.results?.first else {
                fputs("   ❌ 未检测到前景主体\n", stderr)
                return false
            }

            let maskPixelBuffer = try result.generateScaledMaskForImage(forInstances: result.allInstances, from: handler)
            let ciContext = CIContext(options: [.useSoftwareRenderer: false])
            let originalCIImage = CIImage(cgImage: cgImage)
            let maskCIImage = CIImage(cvPixelBuffer: maskPixelBuffer)
            
            let extent = originalCIImage.extent
            let clearImage = CIImage(color: CIColor.clear).cropped(to: extent)

            guard let filter = CIFilter(name: "CIBlendWithMask") else { return false }
            filter.setValue(originalCIImage, forKey: kCIInputImageKey)
            filter.setValue(maskCIImage,      forKey: kCIInputMaskImageKey)
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

var outputFormat: OutputFormat = .png
var webpQuality = 82

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
    
    print("📸 开始处理单张图片，输出格式: \(outputFormat.displayName)...")
    if processSingleImage(inputPath: inputPath, outputPath: outputPath, outputFormat: outputFormat, webpQuality: webpQuality) {
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
    
    print("🚀 发现 \(imageFiles.count) 张图片，开始批量处理，输出格式: \(outputFormat.displayName)...\n")
    
    var successCount = 0
    var failCount = 0
    
    for (index, fileName) in imageFiles.enumerated() {
        let fullInputPath = (inputPath as NSString).appendingPathComponent(fileName)
        let filenameWithoutExt = (fileName as NSString).deletingPathExtension
        let outputFileName = "\(filenameWithoutExt).\(outputFormat.fileExtension)"
        let fullOutputPath = (outputPath as NSString).appendingPathComponent(outputFileName)
        
        if fileManager.fileExists(atPath: fullOutputPath) {
            print("[\(index + 1)/\(imageFiles.count)] ⏭️  跳过已存在: \(outputFileName)")
            successCount += 1
            continue
        }
        
        print("[\(index + 1)/\(imageFiles.count)] 🧠 处理中: \(fileName) -> \(outputFileName)")
        
        // 因为 processSingleImage 内部有了 autoreleasepool，这里批量跑多少张都不会内存泄漏或崩溃
        if processSingleImage(inputPath: fullInputPath, outputPath: fullOutputPath, outputFormat: outputFormat, webpQuality: webpQuality) {
            successCount += 1
        } else {
            failCount += 1
        }
    }
    
    print("\n🎉 批量处理完成！")
    print("   ✅ 成功: \(successCount) 张")
    if failCount > 0 {
        print("   ❌ 失败: \(failCount) 张")
    }
}
