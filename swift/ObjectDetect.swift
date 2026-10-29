import Foundation
import AppKit
import Vision

struct DetectedObject: Codable {
    var objectId: String
    var objectName: String
    var x: Int
    var y: Int
    var width: Int
    var height: Int
    var confidence: Double = 1.0
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

func parseInputImageURL() throws -> URL {
	let args = Array(CommandLine.arguments.dropFirst())
	guard let first = args.first, !first.isEmpty else {
		throw DetectionError.imageNotFound("Missing input image path. Usage: swift ExtraFoodList.swift <image_path>")
	}
	return URL(fileURLWithPath: first)
}

func buildOutputPaths(for imageURL: URL) -> (jsonPath: String, annotatedPath: String) {
	let baseName = imageURL.deletingPathExtension().lastPathComponent
	let outputDir = "./swift/output"
	let jsonPath = "\(outputDir)/\(baseName)_objects_from_swift.json"
	let annotatedPath = "\(outputDir)/\(baseName)_objects_annotated_by_swift.png"
	return (jsonPath, annotatedPath)
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

func normalizeRowAlignment(objects: [DetectedObject], rowThresholdRatio: Double = 0.4) -> [DetectedObject] {
	guard !objects.isEmpty else {
		return objects
	}

	let avgHeight = Double(objects.reduce(0) { $0 + $1.height }) / Double(objects.count)
	let rowThreshold = max(1.0, avgHeight * rowThresholdRatio)

	let sortedByY = objects.sorted { lhs, rhs in
		if lhs.y == rhs.y {
			return lhs.x < rhs.x
		}
		return lhs.y < rhs.y
	}

	var normalized = sortedByY
	var rowStart = 0

	while rowStart < normalized.count {
		let baseY = normalized[rowStart].y
		var rowEnd = rowStart

		let rowMinY = normalized[rowStart...rowEnd].map { $0.y }.min() ?? normalized[rowStart].y
		let rowMaxHeight = normalized[rowStart...rowEnd].map { $0.height }.max() ?? normalized[rowStart].height

		while rowEnd + 1 < normalized.count {
			let nextY = normalized[rowEnd + 1].y
			//if Double(nextY - baseY) < rowThreshold {
			if nextY<rowMinY && Double(rowMinY - nextY) < rowThreshold || 
					nextY>=rowMinY && Double(nextY)<Double(rowMinY+rowMaxHeight) {
				rowEnd += 1
			} else {
				break
			}
		}

		for idx in rowStart...rowEnd {
			normalized[idx].y = rowMinY
			normalized[idx].height = rowMaxHeight
		}

		rowStart = rowEnd + 1
	}
	// print(normalized)
	return normalized
}

func mergeObjectsInSameRow(objects: [DetectedObject], closeGapRatio: Double = 0.02) -> [DetectedObject] {
	guard !objects.isEmpty else {
		return objects
	}

	let avgWidth = Double(objects.reduce(0) { $0 + $1.width }) / Double(objects.count)
	let closeGapThreshold = max(1, Int(round(avgWidth * closeGapRatio)))

	let grouped = Dictionary(grouping: objects) { $0.y }
	let sortedRowKeys = grouped.keys.sorted()
	var mergedAllRows: [DetectedObject] = []

	for rowY in sortedRowKeys {
		guard var rowObjects = grouped[rowY] else {
			continue
		}
		rowObjects.sort { $0.x < $1.x }

		var mergedRow: [DetectedObject] = []
		var index = 0

		while index < rowObjects.count {
			var current = rowObjects[index]
			var nextIndex = index + 1

			while nextIndex < rowObjects.count {
				let next = rowObjects[nextIndex]

				let x1 = current.x
				let width1 = current.width
				let right1 = x1 + width1

				let x2 = next.x
				let width2 = next.width
				let right2 = x2 + width2

				let isNear = (x1 <= x2) && (right1 <= x2) && ((x2 - right1) <= closeGapThreshold) || (x1 >= x2) && (x1 <= right2) && ((x1 - right2) <= closeGapThreshold)
				let isOverlap = (x1 <= x2) && (right1 > x2) && (right1 < right2) || (x1 >= x2) && (x1 < right2) && (right1 >= right2)
				let isContain = (x1 <= x2) && (right1 >= right2) || (x1 >= x2) && (right1 <= right2)

				guard isNear || isOverlap || isContain else {
					break
				}

				if isNear {
					// (1) 挨着: x = x1, width = x2 - x1 + width2
					current.x = x1
					current.width = x2 - x1 + width2
				} else if isOverlap {
					// (2) 重叠: x = x1, width = x2 - x1 + width2
					current.x = x1
					current.width = x2 - x1 + width2
				} else {
					// (3) 包含: x = x1, width = width1
					current.x = x1
					current.width = width1>width2 ? width1 : width2
				}

				current.y = min(current.y, next.y)
				current.height = max(current.height, next.height)
				current.confidence = max(current.confidence, next.confidence)

				nextIndex += 1
			}

			mergedRow.append(current)
			index = nextIndex
		}

		mergedAllRows.append(contentsOf: mergedRow)
	}

	return mergedAllRows
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

	// 坐标系原点在左上角，x向右递增，y向下递增
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
					objectName: "obj_tmp",
					x: minX,
					y: minY,
					width: maxX - minX + 1,
					height: maxY - minY + 1,
					confidence: 1.0
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
			objectName: "obj_\(idx + 1)",
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
				objectName: "obj_\(idx + 1)",
				x: pixelRect.x,
				y: pixelRect.y,
				width: pixelRect.w,
				height: pixelRect.h,
				confidence: 1.0
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
				objectName: "obj_\(idx + 1)",
				x: pixelRect.x,
				y: pixelRect.y,
				width: pixelRect.w,
				height: pixelRect.h,
				confidence: obs.confidence.isFinite ? Double(obs.confidence) : 1.0
			)
		)
	}

	return objects
}

func detectObjectsInFoodImage(imageURL: URL) throws -> DetectionOutput {
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

	objects = normalizeRowAlignment(objects: objects, rowThresholdRatio: 0.1)
	objects = mergeObjectsInSameRow(objects: objects, closeGapRatio: 0.02)
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

func printFoodsWithName(foodCateIconObjects: [DetectedObject]) {
	let foodEnNames: [String] = [
		"rice","noodles","wheet","corn",
		"greens","potato","lotus root","tomato","melon","carrot",
		"apple","strawberry","banana","grape","orange",
		"meat","shrimp","egg","tofu","nut",
		"yogurt","milk","cheese","seasoning","oil"
	]
	for idx in 0..<foodCateIconObjects.count {
		print("DetectedObject(objectId: \"\(foodEnNames[idx])\", objectName: \"\(foodEnNames[idx])\", x: \(foodCateIconObjects[idx].x), y: \(foodCateIconObjects[idx].y), width: \(foodCateIconObjects[idx].width), height: \(foodCateIconObjects[idx].height)),")
	}
}

func printFoodCatesWithName(foodCateIconObjects: [DetectedObject]) {
	let foodCateEnNames: [String] = [
		"milk","beverages","alcoholic beverages","nuts","infant food",
		"cookie","dried beans","fruits","fats and oils","livestock meat",
		"poultry meat","sugar","fungi and algae","vegetables","tubers",
		"egg products","condiments","grain","fast food","seafood"
	]
	for idx in 0..<foodCateIconObjects.count {
		print("DetectedObject(objectId: \"\(foodCateEnNames[idx])\", objectName: \"\(foodCateEnNames[idx])\", x: \(foodCateIconObjects[idx].x), y: \(foodCateIconObjects[idx].y), width: \(foodCateIconObjects[idx].width), height: \(foodCateIconObjects[idx].height)),")
	}
}

func printFactsWithName(factObjects: [DetectedObject]) {
	let factEnNames: [String] = [
		"energy","protein","FAT","CHO","vitaminA",
		"vitaminC","vitaminE","thiamin","riboflavin","niacin",
		"calcium","iron","zinc","phosphorus","potassium",
		"sodium","magnesium","selenium","copper","manganese",
		"iodine","sfa","usfa","mufa","pufa",
		"water","cholesterol","beta-carotene","ash","dietary_fiber",
		"malic_acid", "mulssifiers","sweeteners","lemon","chlorophyll",
		"salt","sugar","calorie"
	]
	for idx in 0..<factObjects.count {
		print("DetectedObject(objectId: \"\(factEnNames[idx])\", objectName: \"\(factEnNames[idx])\", x: \(factObjects[idx].x), y: \(factObjects[idx].y), width: \(factObjects[idx].width), height: \(factObjects[idx].height)),")
	}
}

func printVehiclesWithName(vehicleObjects: [DetectedObject]) {
	for idx in 0..<vehicleObjects.count {
		if idx < 21 {
			print("DetectedObject(objectId: \"car_\(idx)\", objectName: \"car\", x: \(vehicleObjects[idx].x), y: \(vehicleObjects[idx].y), width: \(vehicleObjects[idx].width), height: \(vehicleObjects[idx].height)),")
		} else if idx < 35 {
			print("DetectedObject(objectId: \"ship_\(idx - 21)\", objectName: \"ship\", x: \(vehicleObjects[idx].x), y: \(vehicleObjects[idx].y), width: \(vehicleObjects[idx].width), height: \(vehicleObjects[idx].height)),")
		} else if idx < 49 {
			print("DetectedObject(objectId: \"plane_\(idx - 35)\", objectName: \"plane\", x: \(vehicleObjects[idx].x), y: \(vehicleObjects[idx].y), width: \(vehicleObjects[idx].width), height: \(vehicleObjects[idx].height)),")
		} else {
			print("DetectedObject(objectId: \"satellite_\(idx - 49)\", objectName: \"satellite\", x: \(vehicleObjects[idx].x), y: \(vehicleObjects[idx].y), width: \(vehicleObjects[idx].width), height: \(vehicleObjects[idx].height)),")
		}
	}
}

func main() {
	do {
		let imageURL = try parseInputImageURL()
		let output = try detectObjectsInFoodImage(imageURL: imageURL)
		let outputPaths = buildOutputPaths(for: imageURL)

		let encoder = JSONEncoder()
		encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

		let jsonData = try encoder.encode(output)
		// if let text = String(data: jsonData, encoding: .utf8) {
		// 	print(text)
		// }

		try FileManager.default.createDirectory(atPath: "./swift/output", withIntermediateDirectories: true)
		try jsonData.write(to: URL(fileURLWithPath: outputPaths.jsonPath))

		let cgImage = try loadCGImage(from: imageURL)
		saveAnnotatedImage(cgImage: cgImage, objects: output.objects, outputPath: outputPaths.annotatedPath)

		// print("Saved JSON: \(outputPaths.jsonPath)")
		print("Saved annotated image: \(outputPaths.annotatedPath)")

		// printFoodsWithName(foodCateIconObjects: output.objects)
		// printFoodCatesWithName(foodCateIconObjects: output.objects)
		// printFactsWithName(factObjects: output.objects)
		printVehiclesWithName(vehicleObjects: output.objects)
	} catch {
		fputs("Error: \(error.localizedDescription)\n", stderr)
		exit(1)
	}
}

main()
