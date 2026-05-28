import Foundation
import AppKit
import Vision

struct DetectedObject: Codable {
	let objectId: String
	let x: Int
	let y: Int
	let width: Int
	let height: Int
	let confidence: Double?
}

struct DetectionOutput: Codable {
	let imagePath: String
	let detector: String
	let count: Int
	let objects: [DetectedObject]
}

enum DetectionError: Error, LocalizedError {
	case imageNotFound(String)
	case cannotCreateCGImage(String)

	var errorDescription: String? {
		switch self {
		case .imageNotFound(let path):
			return "Image not found: \(path)"
		case .cannotCreateCGImage(let path):
			return "Cannot create CGImage from: \(path)"
		}
	}
}

func resolveImagePath() -> URL {
	let fileManager = FileManager.default
	let candidates = [
		"./input/food1.png",
		"./swift/input/food1.png"
	]
	for item in candidates {
		if fileManager.fileExists(atPath: item) {
			return URL(fileURLWithPath: item)
		}
	}
	return URL(fileURLWithPath: candidates[0])
}

func loadCGImage(from url: URL) throws -> CGImage {
	guard FileManager.default.fileExists(atPath: url.path) else {
		throw DetectionError.imageNotFound(url.path)
	}

	guard let nsImage = NSImage(contentsOf: url) else {
		throw DetectionError.cannotCreateCGImage(url.path)
	}

	var proposedRect = CGRect(origin: .zero, size: nsImage.size)
	guard let cgImage = nsImage.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil) else {
		throw DetectionError.cannotCreateCGImage(url.path)
	}

	return cgImage
}

func normalizedRectToPixelTopLeft(_ rect: CGRect, imageWidth: Int, imageHeight: Int) -> (x: Int, y: Int, w: Int, h: Int) {
	let width = max(0, Int(round(rect.width * Double(imageWidth))))
	let height = max(0, Int(round(rect.height * Double(imageHeight))))
	let x = max(0, Int(round(rect.minX * Double(imageWidth))))
	let yTop = max(0, Int(round((1.0 - rect.maxY) * Double(imageHeight))))
	return (x, yTop, width, height)
}

func makeRGBA8Buffer(cgImage: CGImage) -> (pixels: [UInt8], width: Int, height: Int)? {
	let width = cgImage.width
	let height = cgImage.height
	guard width > 0, height > 0 else {
		return nil
	}

	var pixels = [UInt8](repeating: 0, count: width * height * 4)
	guard let context = CGContext(
		data: &pixels,
		width: width,
		height: height,
		bitsPerComponent: 8,
		bytesPerRow: width * 4,
		space: CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB(),
		bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
	) else {
		return nil
	}

	context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
	return (pixels, width, height)
}

func hasMeaningfulTransparentBackground(cgImage: CGImage, alphaThreshold: UInt8 = 8) -> Bool {
	guard let rgba = makeRGBA8Buffer(cgImage: cgImage) else {
		return false
	}

	let width = rgba.width
	let height = rgba.height
	let total = max(1, width * height)
	var transparentCount = 0
	var foregroundCount = 0

	for idx in stride(from: 3, to: rgba.pixels.count, by: 4) {
		let alpha = rgba.pixels[idx]
		if alpha <= alphaThreshold {
			transparentCount += 1
		} else {
			foregroundCount += 1
		}
	}

	if foregroundCount == 0 {
		return false
	}

	let transparentRatio = Double(transparentCount) / Double(total)
	return transparentRatio >= 0.1
}

func detectByAlphaConnectedComponents(cgImage: CGImage, alphaThreshold: UInt8 = 8, minAreaRatio: Double = 0.0002) -> [DetectedObject] {
	guard let rgba = makeRGBA8Buffer(cgImage: cgImage) else {
		return []
	}

	let width = rgba.width
	let height = rgba.height
	let totalPixels = width * height
	let minArea = max(16, Int(Double(totalPixels) * minAreaRatio))

	var visited = [UInt8](repeating: 0, count: totalPixels)
	var objects: [DetectedObject] = []

	@inline(__always)
	func isForeground(_ x: Int, _ y: Int) -> Bool {
		let pixelIndex = y * width + x
		let alphaIndex = pixelIndex * 4 + 3
		return rgba.pixels[alphaIndex] > alphaThreshold
	}

	let dx = [1, -1, 0, 0]
	let dy = [0, 0, 1, -1]

	for y in 0..<height {
		for x in 0..<width {
			let start = y * width + x
			if visited[start] == 1 || !isForeground(x, y) {
				continue
			}

			var queue: [Int] = [start]
			visited[start] = 1
			var head = 0

			var minX = x
			var maxX = x
			var minY = y
			var maxY = y
			var area = 0

			while head < queue.count {
				let current = queue[head]
				head += 1

				let cx = current % width
				let cy = current / width
				area += 1

				if cx < minX { minX = cx }
				if cx > maxX { maxX = cx }
				if cy < minY { minY = cy }
				if cy > maxY { maxY = cy }

				for i in 0..<4 {
					let nx = cx + dx[i]
					let ny = cy + dy[i]
					if nx < 0 || nx >= width || ny < 0 || ny >= height {
						continue
					}
					let next = ny * width + nx
					if visited[next] == 1 || !isForeground(nx, ny) {
						continue
					}
					visited[next] = 1
					queue.append(next)
				}
			}

			if area < minArea {
				continue
			}

			objects.append(
				DetectedObject(
					objectId: "obj_tmp",
					x: minX,
					y: minY,
					width: maxX - minX + 1,
					height: maxY - minY + 1,
					confidence: nil
				)
			)
		}
	}

	return objects
}

func sortAndRenumber(_ objects: [DetectedObject]) -> [DetectedObject] {
	let sorted = objects.sorted { lhs, rhs in
		if lhs.y == rhs.y {
			return lhs.x < rhs.x
		}
		return lhs.y < rhs.y
	}

	return sorted.enumerated().map { idx, object in
		DetectedObject(
			objectId: "obj_\(idx + 1)",
			x: object.x,
			y: object.y,
			width: object.width,
			height: object.height,
			confidence: object.confidence
		)
	}
}

func detectBySaliency(cgImage: CGImage) -> [DetectedObject] {
	let request = VNGenerateObjectnessBasedSaliencyImageRequest()
	let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])

	do {
		try handler.perform([request])
	} catch {
		return []
	}

	guard let result = request.results?.first,
		  let salientObjects = result.salientObjects,
		  !salientObjects.isEmpty else {
		return []
	}

	let imageWidth = cgImage.width
	let imageHeight = cgImage.height
	let imageArea = max(1, imageWidth * imageHeight)

	var objects: [DetectedObject] = []
	for (idx, observation) in salientObjects.enumerated() {
		let pixelRect = normalizedRectToPixelTopLeft(observation.boundingBox, imageWidth: imageWidth, imageHeight: imageHeight)
		let area = pixelRect.w * pixelRect.h
		if area < imageArea / 500 {
			continue
		}
		objects.append(
			DetectedObject(
				objectId: "obj_\(idx + 1)",
				x: pixelRect.x,
				y: pixelRect.y,
				width: pixelRect.w,
				height: pixelRect.h,
				confidence: nil
			)
		)
	}

	return objects
}

func detectByRectangles(cgImage: CGImage) -> [DetectedObject] {
	let request = VNDetectRectanglesRequest()
	request.maximumObservations = 20
	request.minimumSize = 0.05
	request.minimumAspectRatio = 0.2

	let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
	do {
		try handler.perform([request])
	} catch {
		return []
	}

	guard let observations = request.results else {
		return []
	}

	let imageWidth = cgImage.width
	let imageHeight = cgImage.height
	var objects: [DetectedObject] = []

	for (idx, obs) in observations.enumerated() {
		let pixelRect = normalizedRectToPixelTopLeft(obs.boundingBox, imageWidth: imageWidth, imageHeight: imageHeight)
		objects.append(
			DetectedObject(
				objectId: "obj_\(idx + 1)",
				x: pixelRect.x,
				y: pixelRect.y,
				width: pixelRect.w,
				height: pixelRect.h,
				confidence: obs.confidence.isFinite ? Double(obs.confidence) : nil
			)
		)
	}

	return objects
}

func detectObjectsInFoodImage() throws -> DetectionOutput {
	let imageURL = resolveImagePath()
	let cgImage = try loadCGImage(from: imageURL)

	var detector = "alpha_connected_components"
	var objects: [DetectedObject] = []

	if hasMeaningfulTransparentBackground(cgImage: cgImage) {
		objects = detectByAlphaConnectedComponents(cgImage: cgImage)
	}

	if objects.isEmpty {
		detector = "vision_saliency"
		objects = detectBySaliency(cgImage: cgImage)
	}

	if objects.isEmpty {
		detector = "vision_rectangles"
		objects = detectByRectangles(cgImage: cgImage)
	}

	objects = sortAndRenumber(objects)

	return DetectionOutput(
		imagePath: imageURL.path,
		detector: detector,
		count: objects.count,
		objects: objects
	)
}

func saveAnnotatedImage(cgImage: CGImage, objects: [DetectedObject], outputPath: String) {
	let width = cgImage.width
	let height = cgImage.height
	let colorSpace = CGColorSpaceCreateDeviceRGB()

	guard let context = CGContext(
		data: nil,
		width: width,
		height: height,
		bitsPerComponent: 8,
		bytesPerRow: 0,
		space: colorSpace,
		bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
	) else {
		return
	}

	context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
	context.setLineWidth(3)
	context.setStrokeColor(NSColor.systemGreen.cgColor)

	for object in objects {
		let yBottom = height - object.y - object.height
		let rect = CGRect(x: object.x, y: yBottom, width: object.width, height: object.height)
		context.stroke(rect)
	}

	guard let outCGImage = context.makeImage() else {
		return
	}

	let nsImage = NSImage(cgImage: outCGImage, size: NSSize(width: width, height: height))
	guard
		let tiffData = nsImage.tiffRepresentation,
		let bitmap = NSBitmapImageRep(data: tiffData),
		let pngData = bitmap.representation(using: .png, properties: [:])
	else {
		return
	}

	let outputURL = URL(fileURLWithPath: outputPath)
	try? FileManager.default.createDirectory(at: outputURL.deletingLastPathComponent(), withIntermediateDirectories: true)
	try? pngData.write(to: outputURL)
}

func main() {
	do {
		let output = try detectObjectsInFoodImage()
		let encoder = JSONEncoder()
		encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

		let jsonData = try encoder.encode(output)
		if let text = String(data: jsonData, encoding: .utf8) {
			print(text)
		}

		let outputPath = "./swift/output/food1_objects_from_swift.json"
		try FileManager.default.createDirectory(atPath: "./swift/output", withIntermediateDirectories: true)
		try jsonData.write(to: URL(fileURLWithPath: outputPath))

		let imageURL = resolveImagePath()
		let cgImage = try loadCGImage(from: imageURL)
		saveAnnotatedImage(cgImage: cgImage, objects: output.objects, outputPath: "./swift/output/food1_objects_annotated_by_swift.png")

		print("Saved JSON: \(outputPath)")
		print("Saved annotated image: ./swift/output/food1_objects_annotated_by_swift.png")
	} catch {
		fputs("Error: \(error.localizedDescription)\n", stderr)
		exit(1)
	}
}

main()
