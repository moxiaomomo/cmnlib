import Foundation
import Vision
import CoreImage
import AppKit
import ImageIO
import UniformTypeIdentifiers

// MARK: - 辅助函数：确保输出路径的后缀是 .png
func forcePNGExtension(for path: String) -> String {
    let nsPath = path as NSString
    let ext = nsPath.pathExtension.lowercased()
    if ext == "png" {
        return path
    }
    let dir = nsPath.deletingLastPathComponent
    let filename = nsPath.deletingPathExtension
    return (dir as NSString).appendingPathComponent("\(filename).png")
}

// MARK: - PNG 写入与可选压缩
func writeCompressedPNG(cgImage: CGImage, outputPath: String) -> Bool {
    let outputURL = URL(fileURLWithPath: outputPath)
    guard let destination = CGImageDestinationCreateWithURL(
        outputURL as CFURL,
        UTType.png.identifier as CFString,
        1,
        nil
    ) else {
        fputs("   ❌ 无法创建 PNG 输出目标\n", stderr)
        return false
    }

    // PNG 为无损格式，这里使用较优过滤参数来帮助减小体积。
    let pngProps: [CFString: Any] = [
        kCGImagePropertyPNGCompressionFilter: 5,
        kCGImagePropertyPNGInterlaceType: 0,
    ]
    let imageProps: [CFString: Any] = [
        kCGImagePropertyPNGDictionary: pngProps
    ]

    CGImageDestinationAddImage(destination, cgImage, imageProps as CFDictionary)
    guard CGImageDestinationFinalize(destination) else {
        fputs("   ❌ PNG 写入失败\n", stderr)
        return false
    }
    return true
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
func processSingleImage(inputPath: String, outputPath: String) -> Bool {
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

            guard writeCompressedPNG(cgImage: outputCGImage, outputPath: outputPath) else {
                return false
            }
            tryOptimizePNGWithPngquant(filePath: outputPath)
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

guard args.count == 4 else {
    print("""
    ╔═══════════════════════════════════════════════════╗
    ║   Usage: removebg <type> <input> <output>        ║
    ║                                                 ║
    ║   type=0: 单图模式                               ║
    ║     removebg 0 input.jpg output.png              ║
    ║                                                 ║
    ║   type=1: 批量模式 (输入输出必须为文件夹)          ║
    ║     removebg 1 ./input_folder/ ./output_folder/   ║
    ╚═══════════════════════════════════════════════════╝
    """)
    exit(1)
}

let typeStr    = args[1]
let inputPath  = args[2]
var outputPath = args[3]

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
    
    outputPath = forcePNGExtension(for: outputPath)
    
    print("📸 开始处理单张图片...")
    if processSingleImage(inputPath: inputPath, outputPath: outputPath) {
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
    
    print("🚀 发现 \(imageFiles.count) 张图片，开始批量处理...\n")
    
    var successCount = 0
    var failCount = 0
    
    for (index, fileName) in imageFiles.enumerated() {
        let fullInputPath = (inputPath as NSString).appendingPathComponent(fileName)
        let filenameWithoutExt = (fileName as NSString).deletingPathExtension
        let outputFileName = "\(filenameWithoutExt).png"
        let fullOutputPath = (outputPath as NSString).appendingPathComponent(outputFileName)
        
        if fileManager.fileExists(atPath: fullOutputPath) {
            print("[\(index + 1)/\(imageFiles.count)] ⏭️  跳过已存在: \(outputFileName)")
            successCount += 1
            continue
        }
        
        print("[\(index + 1)/\(imageFiles.count)] 🧠 处理中: \(fileName) -> \(outputFileName)")
        
        // 因为 processSingleImage 内部有了 autoreleasepool，这里批量跑多少张都不会内存泄漏或崩溃
        if processSingleImage(inputPath: fullInputPath, outputPath: fullOutputPath) {
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
