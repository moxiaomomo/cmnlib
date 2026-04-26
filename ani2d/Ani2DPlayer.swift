import Foundation
import CoreGraphics
import ImageIO

#if canImport(UIKit)
import UIKit
public typealias A2DPlatformImage = UIImage
#elseif canImport(AppKit)
import AppKit
public typealias A2DPlatformImage = NSImage
#else
#error("A2D requires UIKit or AppKit")
#endif

public struct A2DFrame: Decodable, Sendable {
    public let index: Int
    public let name: String?
    public let state: String?
    public let stateFrameIndex: Int?
    public let x: Int
    public let y: Int
    public let w: Int
    public let h: Int
    public let durationMs: Int?
}

public struct A2DStateMachine: Decodable, Sendable {
    public let name: String
    public let frameIndices: [Int]
    public let frameCount: Int?
}

public struct A2DAtlas: Decodable, Sendable {
    public let width: Int
    public let height: Int
    public let layout: String
    public let padding: Int?
}

public struct A2DMetadata: Decodable, Sendable {
    public let type: String
    public let version: Int
    public let atlas: A2DAtlas
    public let fps: Int
    public let frameCount: Int
    public let stateMachineCount: Int?
    public let stateMachines: [A2DStateMachine]?
    public let frames: [A2DFrame]
}

public struct A2DDecodedAsset: Sendable {
    public let metadata: A2DMetadata
    public let atlasData: Data
    public let atlasImage: A2DPlatformImage
    public let frames: [A2DPlatformImage]
    public let frameDurations: [TimeInterval]
    public let orderedStateNames: [String]
    public let stateFrameIndicesByName: [String: [Int]]
}

#if canImport(UIKit)
public enum A2DInteractionType: String, Sendable {
    case singleTap
    case doubleTap
    case longPressBegan
    case longPressChanged
    case longPressEnded
    case longPressCancelled
    case dragBegan
    case dragChanged
    case dragEnded
    case dragCancelled
}

public struct A2DInteractionEvent: Sendable {
    public let type: A2DInteractionType
    public let location: CGPoint
    public let normalizedLocation: CGPoint
    public let translation: CGPoint
    public let velocity: CGPoint
    public let stateName: String?
    public let displayedFrameIndex: Int?
}
#endif

public enum A2DError: Error, LocalizedError {
    case fileTooSmall
    case invalidMagic
    case unsupportedVersion(UInt8)
    case invalidPayloadLength
    case invalidAtlasImage
    case invalidAtlasCGImage
    case frameCropFailed(index: Int)
    case noFrames

    public var errorDescription: String? {
        switch self {
        case .fileTooSmall:
            return NSLocalizedString("a2d_error_file_too_small", comment: "A2D file header is too short")
        case .invalidMagic:
            return NSLocalizedString("a2d_error_invalid_magic", comment: "A2D magic mismatch")
        case .unsupportedVersion(let version):
            return String(
                format: NSLocalizedString("a2d_error_unsupported_version", comment: "Unsupported A2D version with number"),
                version
            )
        case .invalidPayloadLength:
            return NSLocalizedString("a2d_error_invalid_payload_length", comment: "A2D payload length is incomplete")
        case .invalidAtlasImage:
            return NSLocalizedString("a2d_error_invalid_atlas_image", comment: "Failed to read atlas PNG")
        case .invalidAtlasCGImage:
            return NSLocalizedString("a2d_error_invalid_atlas_cgimage", comment: "Failed to create CGImage from atlas")
        case .frameCropFailed(let index):
            return String(
                format: NSLocalizedString("a2d_error_frame_crop_failed", comment: "Failed to crop frame at index"),
                index
            )
        case .noFrames:
            return NSLocalizedString("a2d_error_no_frames", comment: "No playable frames in A2D")
        }
    }
}

public enum A2DDecoder {
    private static let magic = Data([0x41, 0x4E, 0x49, 0x32, 0x44])
    private static let headerSize = 18

    private struct A2DStateNamesMetadata: Decodable {
        let stateMachines: [A2DStateMachine]?
    }

    public static func decode(fileURL: URL) throws -> A2DDecodedAsset {
        let data = try Data(contentsOf: fileURL)
        return try decode(data: data)
    }

    public static func getStateNames(fileURL: URL) throws -> [String] {
        let data = try Data(contentsOf: fileURL)
        return try getStateNames(data: data)
    }

    public static func getStateNames(data: Data) throws -> [String] {
        let (_, jsonData) = try readPayload(data: data)
        let metadata = try JSONDecoder().decode(A2DStateNamesMetadata.self, from: jsonData)

        let stateNames = metadata.stateMachines?
            .map(\ .name)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty } ?? []

        if !stateNames.isEmpty {
            return stateNames
        }
        return ["default"]
    }

    public static func decode(data: Data) throws -> A2DDecodedAsset {
        let (atlasData, jsonData) = try readPayload(data: data)

        let metadata = try JSONDecoder().decode(A2DMetadata.self, from: jsonData)

        guard
            let source = CGImageSourceCreateWithData(atlasData as CFData, nil),
            let atlasCGImage = CGImageSourceCreateImageAtIndex(source, 0, nil)
        else {
            throw A2DError.invalidAtlasImage
        }
        let atlasImage = makePlatformImage(from: atlasCGImage)

        guard !metadata.frames.isEmpty else {
            throw A2DError.noFrames
        }

        var frames: [A2DPlatformImage] = []
        frames.reserveCapacity(metadata.frames.count)

        for frame in metadata.frames {
            let rect = CGRect(x: frame.x, y: frame.y, width: frame.w, height: frame.h)
            guard let cropped = atlasCGImage.cropping(to: rect) else {
                throw A2DError.frameCropFailed(index: frame.index)
            }
            let image = makePlatformImage(from: cropped)
            frames.append(image)
        }

        let defaultDuration = max(0.001, 1.0 / Double(max(1, metadata.fps)))
        let durations = metadata.frames.map { frame in
            if let durationMs = frame.durationMs, durationMs > 0 {
                return Double(durationMs) / 1000.0
            }
            return defaultDuration
        }

        let (orderedStateNames, stateFrameIndicesByName) = buildStateMap(metadata: metadata)

        return A2DDecodedAsset(
            metadata: metadata,
            atlasData: atlasData,
            atlasImage: atlasImage,
            frames: frames,
            frameDurations: durations,
            orderedStateNames: orderedStateNames,
            stateFrameIndicesByName: stateFrameIndicesByName
        )
    }

    private static func readPayload(data: Data) throws -> (atlasData: Data, jsonData: Data) {
        guard data.count >= headerSize else {
            throw A2DError.fileTooSmall
        }

        let magic = data.subdata(in: 0..<5)
        guard magic == self.magic else {
            throw A2DError.invalidMagic
        }

        let version = data[5]
        guard version == 1 else {
            throw A2DError.unsupportedVersion(version)
        }

        let atlasSize = Int(try readUInt64LE(from: data, offset: 6))
        let jsonSize = Int(try readUInt32LE(from: data, offset: 14))
        let atlasStart = headerSize
        let atlasEnd = atlasStart + atlasSize
        let jsonEnd = atlasEnd + jsonSize

        guard jsonEnd <= data.count else {
            throw A2DError.invalidPayloadLength
        }

        let atlasData = data.subdata(in: atlasStart..<atlasEnd)
        let jsonData = data.subdata(in: atlasEnd..<jsonEnd)
        return (atlasData, jsonData)
    }

    private static func buildStateMap(metadata: A2DMetadata) -> ([String], [String: [Int]]) {
        let frameCount = metadata.frames.count

        if let stateMachines = metadata.stateMachines, !stateMachines.isEmpty {
            var orderedNames: [String] = []
            var map: [String: [Int]] = [:]

            for sm in stateMachines {
                let filtered = sm.frameIndices.filter { $0 >= 0 && $0 < frameCount }
                guard !filtered.isEmpty else {
                    continue
                }
                orderedNames.append(sm.name)
                map[sm.name] = filtered
            }

            if !orderedNames.isEmpty {
                return (orderedNames, map)
            }
        }

        var orderedNames: [String] = []
        var map: [String: [Int]] = [:]
        for (idx, frame) in metadata.frames.enumerated() {
            guard let raw = frame.state, !raw.isEmpty else {
                continue
            }
            if map[raw] == nil {
                orderedNames.append(raw)
                map[raw] = []
            }
            map[raw, default: []].append(idx)
        }

        if !orderedNames.isEmpty {
            return (orderedNames, map)
        }

        let fallback = "default"
        let all = Array(0..<frameCount)
        return ([fallback], [fallback: all])
    }

    private static func makePlatformImage(from cgImage: CGImage) -> A2DPlatformImage {
        #if canImport(UIKit)
        return UIImage(cgImage: cgImage, scale: 1.0, orientation: .up)
        #elseif canImport(AppKit)
        return NSImage(cgImage: cgImage, size: NSSize(width: cgImage.width, height: cgImage.height))
        #endif
    }

    private static func readUInt32LE(from data: Data, offset: Int) throws -> UInt32 {
        let end = offset + 4
        guard end <= data.count else {
            throw A2DError.fileTooSmall
        }
        let b0 = UInt32(data[offset])
        let b1 = UInt32(data[offset + 1]) << 8
        let b2 = UInt32(data[offset + 2]) << 16
        let b3 = UInt32(data[offset + 3]) << 24
        return b0 | b1 | b2 | b3
    }

    private static func readUInt64LE(from data: Data, offset: Int) throws -> UInt64 {
        let end = offset + 8
        guard end <= data.count else {
            throw A2DError.fileTooSmall
        }
        var value: UInt64 = 0
        for i in 0..<8 {
            value |= UInt64(data[offset + i]) << UInt64(i * 8)
        }
        return value
    }
}

#if canImport(UIKit)
@MainActor
public final class A2DPlayerView: UIView {
    public private(set) var asset: A2DDecodedAsset?
    public private(set) var isPlaying = false
    public private(set) var currentStateName: String?
    public var loops = true
    public var automaticallySizesToContent = true
    public var singleTapDebounceInterval: TimeInterval = 0.2
    public var onInteraction: ((A2DInteractionEvent) -> Void)?
    public var availableStateNames: [String] {
        asset?.orderedStateNames ?? []
    }

    private let imageView = UIImageView()
    private var currentFrameIndex = 0
    private var scheduledWork: DispatchWorkItem?
    private var playbackFrameIndices: [Int] = []
    private var lastSingleTapEventTime: Date?
    private lazy var singleTapGesture: UITapGestureRecognizer = {
        let recognizer = UITapGestureRecognizer(target: self, action: #selector(handleSingleTap(_:)))
        recognizer.numberOfTapsRequired = 1
        return recognizer
    }()
    private lazy var doubleTapGesture: UITapGestureRecognizer = {
        let recognizer = UITapGestureRecognizer(target: self, action: #selector(handleDoubleTap(_:)))
        recognizer.numberOfTapsRequired = 2
        return recognizer
    }()
    private lazy var longPressGesture: UILongPressGestureRecognizer = {
        let recognizer = UILongPressGestureRecognizer(target: self, action: #selector(handleLongPress(_:)))
        recognizer.minimumPressDuration = 0.45
        return recognizer
    }()
    private lazy var panGesture: UIPanGestureRecognizer = {
        let recognizer = UIPanGestureRecognizer(target: self, action: #selector(handlePan(_:)))
        recognizer.maximumNumberOfTouches = 1
        return recognizer
    }()

    public override init(frame: CGRect) {
        super.init(frame: frame)
        commonInit()
    }

    public required init?(coder: NSCoder) {
        super.init(coder: coder)
        commonInit()
    }

    deinit {
        scheduledWork?.cancel()
    }

    public func load(from fileURL: URL) throws {
        let decoded = try A2DDecoder.decode(fileURL: fileURL)
        apply(asset: decoded)
    }

    public func load(data: Data) throws {
        let decoded = try A2DDecoder.decode(data: data)
        apply(asset: decoded)
    }
    
    public func getStateNames(from fileURL: URL) throws -> [String] {
        try A2DDecoder.getStateNames(fileURL: fileURL)
    }

    public func getStateNames(from data: Data) throws -> [String] {
        try A2DDecoder.getStateNames(data: data)
    }

    public func setInteractionHandler(_ handler: ((A2DInteractionEvent) -> Void)?) {
        onInteraction = handler
    }

    public func getStateNames() -> [String] {
        availableStateNames
    }

    public func play(loop: Bool? = nil) {
        if let loop {
            loops = loop
        }
        guard asset != nil else {
            return
        }
        if playbackFrameIndices.isEmpty {
            _ = selectState(nil, restart: true)
        }
        guard !playbackFrameIndices.isEmpty else {
            return
        }

        isPlaying = true
        scheduledWork?.cancel()
        render(frameAt: currentFrameIndex)
        scheduleNextFrame()
    }

    @discardableResult
    public func play(stateName: String?, loop: Bool? = nil) -> Bool {
        _ = selectState(stateName, restart: true)
        play(loop: loop)
        return true
    }

    public func pause() {
        isPlaying = false
        scheduledWork?.cancel()
        scheduledWork = nil
    }

    public func stop() {
        pause()
        currentFrameIndex = 0
        render(frameAt: currentFrameIndex)
    }

    public func seek(to frameIndex: Int, autoPlay: Bool = false) {
        guard asset != nil else {
            return
        }
        guard !playbackFrameIndices.isEmpty else {
            return
        }
        let safeIndex = min(max(frameIndex, 0), playbackFrameIndices.count - 1)
        currentFrameIndex = safeIndex
        render(frameAt: safeIndex)

        if autoPlay {
            play()
        }
    }

    public func showLastFrame() {
        guard asset != nil else {
            return
        }
        guard !playbackFrameIndices.isEmpty else {
            return
        }
        currentFrameIndex = max(0, playbackFrameIndices.count - 1)
        render(frameAt: currentFrameIndex)
    }

    @discardableResult
    public func selectState(_ stateName: String?, restart: Bool = true) -> Bool {
        guard let asset else {
            return false
        }

        let normalizedStateName: String?
        if let stateName {
            let trimmed = stateName.trimmingCharacters(in: .whitespacesAndNewlines)
            normalizedStateName = trimmed.isEmpty ? nil : trimmed
        } else {
            normalizedStateName = nil
        }

        let selectedName: String
        let selectedIndices: [Int]

        if
            let stateName = normalizedStateName,
            let indices = asset.stateFrameIndicesByName[stateName],
            !indices.isEmpty
        {
            selectedName = stateName
            selectedIndices = indices
        } else if
            let first = asset.orderedStateNames.first,
            let indices = asset.stateFrameIndicesByName[first],
            !indices.isEmpty
        {
            selectedName = first
            selectedIndices = indices
        } else {
            selectedName = "default"
            selectedIndices = Array(asset.frames.indices)
        }

        playbackFrameIndices = selectedIndices
        currentStateName = selectedName

        if restart || currentFrameIndex >= playbackFrameIndices.count {
            currentFrameIndex = 0
        }
        render(frameAt: currentFrameIndex)
        return true
    }

    private func commonInit() {
        isOpaque = false
        backgroundColor = .clear
        isUserInteractionEnabled = true

        imageView.backgroundColor = .clear
        imageView.isOpaque = false
        imageView.isUserInteractionEnabled = false
        imageView.contentMode = .scaleAspectFit
        imageView.clipsToBounds = false
        imageView.translatesAutoresizingMaskIntoConstraints = false

        singleTapGesture.require(toFail: doubleTapGesture)
        addGestureRecognizer(singleTapGesture)
        addGestureRecognizer(doubleTapGesture)
        addGestureRecognizer(longPressGesture)
        addGestureRecognizer(panGesture)

        addSubview(imageView)
        NSLayoutConstraint.activate([
            imageView.leadingAnchor.constraint(equalTo: leadingAnchor),
            imageView.trailingAnchor.constraint(equalTo: trailingAnchor),
            imageView.topAnchor.constraint(equalTo: topAnchor),
            imageView.bottomAnchor.constraint(equalTo: bottomAnchor)
        ])
    }

    private func apply(asset: A2DDecodedAsset) {
        pause()
        self.asset = asset
        lastSingleTapEventTime = nil
        _ = selectState(nil, restart: true)

        if
            automaticallySizesToContent,
            let firstIndex = playbackFrameIndices.first,
            asset.frames.indices.contains(firstIndex)
        {
            let firstFrame = asset.frames[firstIndex]
            bounds.size = firstFrame.size
        }
    }

    private func render(frameAt index: Int) {
        guard
            let asset,
            playbackFrameIndices.indices.contains(index)
        else {
            return
        }
        let frameIndex = playbackFrameIndices[index]
        guard asset.frames.indices.contains(frameIndex) else {
            return
        }
        imageView.image = asset.frames[frameIndex]
    }

    private func scheduleNextFrame() {
        guard isPlaying, let asset else {
            return
        }
        guard !playbackFrameIndices.isEmpty else {
            pause()
            return
        }

        let actualFrameIndex = playbackFrameIndices[currentFrameIndex]
        let delay = asset.frameDurations[actualFrameIndex]
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.isPlaying, let _ = self.asset else {
                return
            }
            guard !self.playbackFrameIndices.isEmpty else {
                self.pause()
                return
            }

            let nextIndex = self.currentFrameIndex + 1
            if nextIndex >= self.playbackFrameIndices.count {
                if self.loops {
                    self.currentFrameIndex = 0
                } else {
                    self.currentFrameIndex = self.playbackFrameIndices.count - 1
                    self.render(frameAt: self.currentFrameIndex)
                    self.pause()
                    return
                }
            } else {
                self.currentFrameIndex = nextIndex
            }

            self.render(frameAt: self.currentFrameIndex)
            self.scheduleNextFrame()
        }

        scheduledWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    private var displayedFrameIndex: Int? {
        guard playbackFrameIndices.indices.contains(currentFrameIndex) else {
            return nil
        }
        return playbackFrameIndices[currentFrameIndex]
    }

    private func emitInteraction(
        type: A2DInteractionType,
        recognizer: UIGestureRecognizer,
        translation: CGPoint = .zero,
        velocity: CGPoint = .zero
    ) {
        guard let onInteraction else {
            return
        }

        let location = recognizer.location(in: self)
        let normalizedLocation = CGPoint(
            x: bounds.width > 0 ? location.x / bounds.width : 0,
            y: bounds.height > 0 ? location.y / bounds.height : 0
        )

        onInteraction(
            A2DInteractionEvent(
                type: type,
                location: location,
                normalizedLocation: normalizedLocation,
                translation: translation,
                velocity: velocity,
                stateName: currentStateName,
                displayedFrameIndex: displayedFrameIndex
            )
        )
    }

    @objc private func handleSingleTap(_ recognizer: UITapGestureRecognizer) {
        guard recognizer.state == .ended else {
            return
        }

        let now = Date()
        if
            let lastTime = lastSingleTapEventTime,
            now.timeIntervalSince(lastTime) < singleTapDebounceInterval
        {
            return
        }
        lastSingleTapEventTime = now

        emitInteraction(type: .singleTap, recognizer: recognizer)
    }

    @objc private func handleDoubleTap(_ recognizer: UITapGestureRecognizer) {
        guard recognizer.state == .ended else {
            return
        }
        emitInteraction(type: .doubleTap, recognizer: recognizer)
    }

    @objc private func handleLongPress(_ recognizer: UILongPressGestureRecognizer) {
        let type: A2DInteractionType?
        switch recognizer.state {
        case .began:
            type = .longPressBegan
        case .changed:
            type = .longPressChanged
        case .ended:
            type = .longPressEnded
        case .cancelled, .failed:
            type = .longPressCancelled
        default:
            type = nil
        }

        guard let type else {
            return
        }
        emitInteraction(type: type, recognizer: recognizer)
    }

    @objc private func handlePan(_ recognizer: UIPanGestureRecognizer) {
        let type: A2DInteractionType?
        switch recognizer.state {
        case .began:
            type = .dragBegan
        case .changed:
            type = .dragChanged
        case .ended:
            type = .dragEnded
        case .cancelled, .failed:
            type = .dragCancelled
        default:
            type = nil
        }

        guard let type else {
            return
        }
        emitInteraction(
            type: type,
            recognizer: recognizer,
            translation: recognizer.translation(in: self),
            velocity: recognizer.velocity(in: self)
        )
    }
}
#endif