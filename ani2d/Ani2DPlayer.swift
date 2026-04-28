import Foundation
import CoreGraphics
import ImageIO

#if canImport(UIKit)
import UIKit
import AVFoundation
public typealias A2DPlatformImage = UIImage
#elseif canImport(AppKit)
import AppKit
public typealias A2DPlatformImage = NSImage
#else
#error("A2D requires UIKit or AppKit")
#endif

// MARK: - JSON Models (VERSION=2)

public struct A2DFrameInfo: Decodable, Sendable {
    public let index: Int
    public let name: String?
    public let x: Int?
    public let y: Int?
    public let w: Int
    public let h: Int
    public let byteSize: Int?
    public let sourceW: Int?
    public let sourceH: Int?
    public let offsetX: Int?
    public let offsetY: Int?
    public let durationMs: Int?
}

public struct A2DAtlasInfo: Decodable, Sendable {
    public let width: Int
    public let height: Int
    public let layout: String
    public let padding: Int?
    public let byteSize: Int
}

public struct A2DStateInfo: Decodable, Sendable {
    public let name: String
    public let fps: Int
    public let frameCount: Int
    public let storage: String?
    public let atlas: A2DAtlasInfo?
    public let bgm: A2DBgmInfo?
    public let frames: [A2DFrameInfo]
}

public struct A2DBgmInfo: Decodable, Sendable {
    public let codec: String
    public let byteSize: Int
    public let fileName: String?
}

public struct A2DFileMetadata: Decodable, Sendable {
    public let type: String
    public let version: Int
    public let fps: Int
    public let stateCount: Int
    public let totalFrameCount: Int?
    public let states: [A2DStateInfo]
}

// MARK: - Decoded State (frames lazily decoded from one state's visual data)

public struct A2DDecodedState: Sendable {
    public let stateName: String
    public let frames: [A2DPlatformImage]
    public let frameDurations: [TimeInterval]
}

// MARK: - Asset (holds raw visual chunks; decodes per state on demand)

/// Holds the parsed .a2d file. State visual chunks are stored raw in memory;
/// frames are decoded only when that state is first requested.
/// Each state is decoded at most once per `load()` call.
public final class A2DDecodedAsset: @unchecked Sendable {
    public let metadata: A2DFileMetadata
    public let orderedStateNames: [String]
    let atlasDataByState: [String: Data]
    let rawFrameDataByState: [String: [Data]]
    let bgmDataByState: [String: Data]
    private var decodedStateCache: [String: A2DDecodedState] = [:]

    init(
        metadata: A2DFileMetadata,
        orderedStateNames: [String],
        atlasDataByState: [String: Data],
        rawFrameDataByState: [String: [Data]],
        bgmDataByState: [String: Data]
    ) {
        self.metadata = metadata
        self.orderedStateNames = orderedStateNames
        self.atlasDataByState = atlasDataByState
        self.rawFrameDataByState = rawFrameDataByState
        self.bgmDataByState = bgmDataByState
    }

    /// Returns decoded frames for `stateName` on first call.
    /// Subsequent calls for the same state return the cached result.
    public func decodedState(for stateName: String) throws -> A2DDecodedState {
        if let cached = decodedStateCache[stateName] {
            return cached
        }
        guard let stateInfo = metadata.states.first(where: { $0.name == stateName }) else {
            throw A2DError.stateNotFound(stateName)
        }

        let storage = (stateInfo.storage?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? "atlas")
        let decoded: A2DDecodedState
        if storage == "raw" {
            guard let rawFrameData = rawFrameDataByState[stateName] else {
                throw A2DError.stateNotFound(stateName)
            }
            decoded = try A2DDecoder.decodeStateFramesFromRaw(
                rawFrameData: rawFrameData,
                stateInfo: stateInfo,
                fallbackFps: metadata.fps
            )
        } else {
            guard let atlasData = atlasDataByState[stateName] else {
                throw A2DError.stateNotFound(stateName)
            }
            decoded = try A2DDecoder.decodeStateFramesFromAtlas(
                atlasData: atlasData,
                stateInfo: stateInfo,
                fallbackFps: metadata.fps
            )
        }
        decodedStateCache[stateName] = decoded
        return decoded
    }

    public func hasBgm(for stateName: String) -> Bool {
        return bgmDataByState[stateName] != nil
    }

    public func bgmData(for stateName: String) -> Data? {
        return bgmDataByState[stateName]
    }
}

// MARK: - Interaction (UIKit only)

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

// MARK: - Errors

public enum A2DError: Error, LocalizedError {
    case fileTooSmall
    case invalidMagic
    case unsupportedVersion(UInt8)
    case invalidPayloadLength
    case invalidAtlasImage
    case invalidAtlasCGImage
    case frameCropFailed(index: Int)
    case invalidRawFrameData(index: Int)
    case frameGeometryInvalid(index: Int)
    case noFrames
    case stateNotFound(String)

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
        case .invalidRawFrameData(let index):
            return "Invalid raw frame data at index \(index)"
        case .frameGeometryInvalid(let index):
            return "Invalid frame geometry at index \(index)"
        case .noFrames:
            return NSLocalizedString("a2d_error_no_frames", comment: "No playable frames in A2D")
        case .stateNotFound(let name):
            return String(
                format: NSLocalizedString("a2d_error_state_not_found", comment: "State not found in A2D"),
                name
            )
        }
    }
}

// MARK: - Decoder

public enum A2DDecoder {
    private static let magic = Data([0x41, 0x4E, 0x49, 0x32, 0x44]) // "ANI2D"
    // header: magic(5B) + version(1B) + stateCount(uint16LE) + jsonSize(uint32LE) = 12 bytes
    private static let headerSize = 12

    public static func decode(fileURL: URL) throws -> A2DDecodedAsset {
        let data = try Data(contentsOf: fileURL)
        return try decode(data: data)
    }

    public static func decode(data: Data) throws -> A2DDecodedAsset {
        guard data.count >= headerSize else {
            throw A2DError.fileTooSmall
        }

        let magic = data.subdata(in: 0..<5)
        guard magic == self.magic else {
            throw A2DError.invalidMagic
        }

        let version = data[5]
        guard version == 2 else {
            throw A2DError.unsupportedVersion(version)
        }

        let stateCount = Int(try readUInt16LE(from: data, offset: 6))
        let jsonSize = Int(try readUInt32LE(from: data, offset: 8))

        let jsonStart = headerSize
        let jsonEnd = jsonStart + jsonSize
        guard jsonEnd <= data.count else {
            throw A2DError.invalidPayloadLength
        }

        let jsonData = data.subdata(in: jsonStart..<jsonEnd)
        let metadata = try JSONDecoder().decode(A2DFileMetadata.self, from: jsonData)

        guard metadata.states.count == stateCount else {
            throw A2DError.invalidPayloadLength
        }

        // Advance past JSON, aligning to 8-byte boundary from start of file
        var offset = jsonEnd
        offset += alignPadLen(offset)

        var atlasDataByState: [String: Data] = [:]
        var rawFrameDataByState: [String: [Data]] = [:]
        var bgmDataByState: [String: Data] = [:]
        var orderedStateNames: [String] = []

        for stateInfo in metadata.states {
            let storage = (stateInfo.storage?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? "atlas")

            if storage == "raw" {
                var frameChunks: [Data] = []
                frameChunks.reserveCapacity(stateInfo.frames.count)

                for frame in stateInfo.frames {
                    let frameByteSize = frame.byteSize ?? 0
                    guard frameByteSize > 0 else {
                        throw A2DError.invalidPayloadLength
                    }
                    let frameEnd = offset + frameByteSize
                    guard frameEnd <= data.count else {
                        throw A2DError.invalidPayloadLength
                    }
                    frameChunks.append(data.subdata(in: offset..<frameEnd))
                    offset = frameEnd + alignPadLen(frameByteSize)
                }
                rawFrameDataByState[stateInfo.name] = frameChunks
            } else {
                guard let atlasInfo = stateInfo.atlas else {
                    throw A2DError.invalidPayloadLength
                }
                let byteSize = atlasInfo.byteSize
                guard byteSize > 0 else {
                    throw A2DError.invalidPayloadLength
                }
                let chunkEnd = offset + byteSize
                guard chunkEnd <= data.count else {
                    throw A2DError.invalidPayloadLength
                }
                atlasDataByState[stateInfo.name] = data.subdata(in: offset..<chunkEnd)
                // Advance by byteSize then pad to next 8-byte alignment
                offset = chunkEnd + alignPadLen(byteSize)
            }
            orderedStateNames.append(stateInfo.name)

            if let bgmInfo = stateInfo.bgm, bgmInfo.byteSize > 0 {
                let bgmEnd = offset + bgmInfo.byteSize
                guard bgmEnd <= data.count else {
                    throw A2DError.invalidPayloadLength
                }
                bgmDataByState[stateInfo.name] = data.subdata(in: offset..<bgmEnd)
                offset = bgmEnd + alignPadLen(bgmInfo.byteSize)
            }
        }

        return A2DDecodedAsset(
            metadata: metadata,
            orderedStateNames: orderedStateNames,
            atlasDataByState: atlasDataByState,
            rawFrameDataByState: rawFrameDataByState,
            bgmDataByState: bgmDataByState
        )
    }

    public static func getStateNames(fileURL: URL) throws -> [String] {
        let data = try Data(contentsOf: fileURL)
        return try getStateNames(data: data)
    }

    public static func getStateNames(data: Data) throws -> [String] {
        guard data.count >= headerSize else {
            throw A2DError.fileTooSmall
        }
        let magic = data.subdata(in: 0..<5)
        guard magic == self.magic else {
            throw A2DError.invalidMagic
        }
        let version = data[5]
        guard version == 2 else {
            throw A2DError.unsupportedVersion(version)
        }
        let jsonSize = Int(try readUInt32LE(from: data, offset: 8))
        let jsonEnd = headerSize + jsonSize
        guard jsonEnd <= data.count else {
            throw A2DError.invalidPayloadLength
        }
        let jsonData = data.subdata(in: headerSize..<jsonEnd)

        struct QuickMeta: Decodable {
            struct StateInfo: Decodable { let name: String }
            let states: [StateInfo]
        }
        let meta = try JSONDecoder().decode(QuickMeta.self, from: jsonData)
        let names = meta.states
            .map { $0.name.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        return names.isEmpty ? ["default"] : names
    }

    /// Decodes all frames for a single state from its atlas PNG bytes.
    /// Called lazily by `A2DDecodedAsset.decodedState(for:)`.
    static func decodeStateFramesFromAtlas(
        atlasData: Data,
        stateInfo: A2DStateInfo,
        fallbackFps: Int
    ) throws -> A2DDecodedState {
        let atlasCGImage = try makeAtlasCGImage(atlasData: atlasData)

        guard !stateInfo.frames.isEmpty else {
            throw A2DError.noFrames
        }

        var frames: [A2DPlatformImage] = []
        frames.reserveCapacity(stateInfo.frames.count)

        for frameInfo in stateInfo.frames {
            frames.append(try decodeSingleFrameFromAtlas(atlasCGImage: atlasCGImage, frameInfo: frameInfo))
        }

        let durations = buildFrameDurations(stateInfo: stateInfo, fallbackFps: fallbackFps)
        return A2DDecodedState(stateName: stateInfo.name, frames: frames, frameDurations: durations)
    }

    static func decodeStateFramesFromRaw(
        rawFrameData: [Data],
        stateInfo: A2DStateInfo,
        fallbackFps: Int
    ) throws -> A2DDecodedState {
        guard !stateInfo.frames.isEmpty else {
            throw A2DError.noFrames
        }
        guard rawFrameData.count == stateInfo.frames.count else {
            throw A2DError.invalidPayloadLength
        }

        var frames: [A2DPlatformImage] = []
        frames.reserveCapacity(rawFrameData.count)

        for (idx, frameBytes) in rawFrameData.enumerated() {
            let frameInfo = stateInfo.frames[idx]
            frames.append(
                try decodeSingleFrameFromRaw(
                    frameData: frameBytes,
                    frameInfo: frameInfo,
                    index: idx
                )
            )
        }

        let durations = buildFrameDurations(stateInfo: stateInfo, fallbackFps: fallbackFps)
        return A2DDecodedState(stateName: stateInfo.name, frames: frames, frameDurations: durations)
    }

    // MARK: Helpers

    /// Returns the number of padding bytes needed to align `n` to 8 bytes.
    /// Matches Python's `(-n) % 8`.
    private static func alignPadLen(_ n: Int, alignment: Int = 8) -> Int {
        return (alignment - n % alignment) % alignment
    }

    private static func makePlatformImage(from cgImage: CGImage) -> A2DPlatformImage {
        #if canImport(UIKit)
        return UIImage(cgImage: cgImage, scale: 1.0, orientation: .up)
        #elseif canImport(AppKit)
        return NSImage(cgImage: cgImage, size: NSSize(width: cgImage.width, height: cgImage.height))
        #endif
    }

    static func makeAtlasCGImage(atlasData: Data) throws -> CGImage {
        guard
            let source = CGImageSourceCreateWithData(atlasData as CFData, nil),
            let atlasCGImage = CGImageSourceCreateImageAtIndex(source, 0, nil)
        else {
            throw A2DError.invalidAtlasImage
        }
        return atlasCGImage
    }

    static func decodeSingleFrameFromAtlas(
        atlasCGImage: CGImage,
        frameInfo: A2DFrameInfo
    ) throws -> A2DPlatformImage {
        guard
            let x = frameInfo.x,
            let y = frameInfo.y,
            frameInfo.w > 0,
            frameInfo.h > 0
        else {
            throw A2DError.frameGeometryInvalid(index: frameInfo.index)
        }
        let rect = CGRect(x: x, y: y, width: frameInfo.w, height: frameInfo.h)
        guard let cropped = atlasCGImage.cropping(to: rect) else {
            throw A2DError.frameCropFailed(index: frameInfo.index)
        }
        return try makePlatformImageWithRestoredCanvas(from: cropped, frameInfo: frameInfo)
    }

    static func decodeSingleFrameFromRaw(
        frameData: Data,
        frameInfo: A2DFrameInfo,
        index: Int
    ) throws -> A2DPlatformImage {
        guard
            let source = CGImageSourceCreateWithData(frameData as CFData, nil),
            let frameCGImage = CGImageSourceCreateImageAtIndex(source, 0, nil)
        else {
            throw A2DError.invalidRawFrameData(index: index)
        }
        return try makePlatformImageWithRestoredCanvas(from: frameCGImage, frameInfo: frameInfo)
    }

    private static func makePlatformImageWithRestoredCanvas(
        from cgImage: CGImage,
        frameInfo: A2DFrameInfo
    ) throws -> A2DPlatformImage {
        let sourceW = max(1, frameInfo.sourceW ?? frameInfo.w)
        let sourceH = max(1, frameInfo.sourceH ?? frameInfo.h)
        let offsetX = frameInfo.offsetX ?? 0
        let offsetY = frameInfo.offsetY ?? 0

        if sourceW == cgImage.width, sourceH == cgImage.height, offsetX == 0, offsetY == 0 {
            return makePlatformImage(from: cgImage)
        }

        guard
            let colorSpace = cgImage.colorSpace ?? CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil,
                width: sourceW,
                height: sourceH,
                bitsPerComponent: 8,
                bytesPerRow: 0,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
            )
        else {
            throw A2DError.invalidAtlasCGImage
        }

        context.clear(CGRect(x: 0, y: 0, width: sourceW, height: sourceH))
        // `offsetY` comes from Python/Pillow top-left coordinates.
        // CoreGraphics draws in bottom-left coordinates, so convert only the Y origin
        // and avoid applying a global vertical flip that can invert the final frame.
        let drawY = sourceH - offsetY - cgImage.height
        context.draw(
            cgImage,
            in: CGRect(x: offsetX, y: drawY, width: cgImage.width, height: cgImage.height)
        )

        guard let restored = context.makeImage() else {
            throw A2DError.invalidAtlasCGImage
        }
        return makePlatformImage(from: restored)
    }

    static func buildFrameDurations(stateInfo: A2DStateInfo, fallbackFps: Int) -> [TimeInterval] {
        let effectiveFps = stateInfo.fps > 0 ? stateInfo.fps : max(1, fallbackFps)
        let defaultDuration = max(0.001, 1.0 / Double(effectiveFps))
        return stateInfo.frames.map { frame in
            if let ms = frame.durationMs, ms > 0 { return Double(ms) / 1000.0 }
            return defaultDuration
        }
    }

    private static func readUInt16LE(from data: Data, offset: Int) throws -> UInt16 {
        guard offset + 2 <= data.count else { throw A2DError.fileTooSmall }
        return UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
    }

    private static func readUInt32LE(from data: Data, offset: Int) throws -> UInt32 {
        guard offset + 4 <= data.count else { throw A2DError.fileTooSmall }
        return UInt32(data[offset])
            | (UInt32(data[offset + 1]) << 8)
            | (UInt32(data[offset + 2]) << 16)
            | (UInt32(data[offset + 3]) << 24)
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
    public var preloadSeconds: Double = 2.0
    public var backgroundBatchSeconds: Double = 1.0
    public var singleTapDebounceInterval: TimeInterval = 0.2
    public var onInteraction: ((A2DInteractionEvent) -> Void)?
    public var availableStateNames: [String] {
        asset?.orderedStateNames ?? []
    }

    private let imageView = UIImageView()
    private var currentDecodedState: A2DDecodedState?
    private var progressiveFrameDurations: [TimeInterval] = []
    private var progressiveAllDurations: [TimeInterval] = []
    private var progressiveStateInfo: A2DStateInfo?
    private var progressiveAtlasCGImage: CGImage?
    private var progressiveRawFrameData: [Data] = []
    private var progressiveNextDecodeIndex: Int = 0
    private var progressiveIsLoading: Bool = false
    private var progressiveLoadToken = UUID()
    private var lastPreparedRequest: (token: Int, stateName: String)?
    private let progressiveDecodeQueue = DispatchQueue(label: "ani2d.decode.queue", qos: .userInitiated)
    private var bgmPlayer: AVAudioPlayer?
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
        bgmPlayer?.stop()
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
        if playbackFrameIndices.isEmpty || currentDecodedState == nil {
            _ = selectState(nil, restart: true)
        }
        guard !playbackFrameIndices.isEmpty else {
            return
        }

        isPlaying = true
        playBgmForCurrentState(looping: loops)
        scheduledWork?.cancel()
        render(frameAt: currentFrameIndex)
        scheduleNextFrame()
    }

    @discardableResult
    public func play(stateName: String?, loop: Bool? = nil, requestToken: Int? = nil) -> Bool {
        _ = selectState(stateName, restart: true, requestToken: requestToken)
        play(loop: loop)
        return true
    }

    public func pause() {
        isPlaying = false
        scheduledWork?.cancel()
        scheduledWork = nil
        bgmPlayer?.pause()
    }

    public func stop() {
        pause()
        bgmPlayer?.stop()
        bgmPlayer?.currentTime = 0
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
    public func selectState(_ stateName: String?, restart: Bool = true, requestToken: Int? = nil) -> Bool {
        guard let asset else {
            return false
        }

        let trimmed = stateName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedStateName: String? = (trimmed?.isEmpty == false) ? trimmed : nil

        let selectedName: String
        if let name = normalizedStateName, asset.orderedStateNames.contains(name) {
            selectedName = name
        } else if let first = asset.orderedStateNames.first {
            selectedName = first
        } else {
            return false
        }

        if
            let requestToken,
            let lastPreparedRequest,
            lastPreparedRequest.token == requestToken,
            lastPreparedRequest.stateName == selectedName || selectedName=="default",
            currentDecodedState?.stateName == selectedName || selectedName=="default"
        {
            if restart {
                currentFrameIndex = 0
                render(frameAt: currentFrameIndex)
            }
            return true
        } else if (requestToken==nil) {
            if restart {
                currentFrameIndex = 0
                render(frameAt: currentFrameIndex)
            }
            return true
        }

        do {
            try prepareProgressiveDecoding(asset: asset, stateName: selectedName)
        } catch {
            return false
        }

        if let requestToken {
            lastPreparedRequest = (token: requestToken, stateName: selectedName)
        }

        let frameCount = currentDecodedState?.frames.count ?? 0
        playbackFrameIndices = frameCount > 0 ? Array(0..<frameCount) : []
        currentStateName = selectedName

        if restart || currentFrameIndex >= playbackFrameIndices.count {
            currentFrameIndex = 0
        }
        if playbackFrameIndices.isEmpty {
            currentFrameIndex = 0
        }
        if isPlaying {
            playBgmForCurrentState(looping: loops)
        }
        render(frameAt: currentFrameIndex)

        startBackgroundDecodingIfNeeded()
        return true
    }

    private func resetProgressiveState() {
        progressiveLoadToken = UUID()
        lastPreparedRequest = nil
        progressiveFrameDurations = []
        progressiveAllDurations = []
        progressiveStateInfo = nil
        progressiveAtlasCGImage = nil
        progressiveRawFrameData = []
        progressiveNextDecodeIndex = 0
        progressiveIsLoading = false
    }

    private func prepareProgressiveDecoding(asset: A2DDecodedAsset, stateName: String) throws {
        resetProgressiveState()

        guard let stateInfo = asset.metadata.states.first(where: { $0.name == stateName }) else {
            throw A2DError.stateNotFound(stateName)
        }
        progressiveStateInfo = stateInfo
        progressiveAllDurations = A2DDecoder.buildFrameDurations(stateInfo: stateInfo, fallbackFps: asset.metadata.fps)

        let totalFrames = stateInfo.frames.count
        guard totalFrames > 0 else {
            currentDecodedState = A2DDecodedState(stateName: stateName, frames: [], frameDurations: [])
            return
        }

        let storage = (stateInfo.storage?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? "atlas")
        if storage == "raw" {
            guard let rawData = asset.rawFrameDataByState[stateName], rawData.count == totalFrames else {
                throw A2DError.invalidPayloadLength
            }
            progressiveRawFrameData = rawData
        } else {
            guard let atlasData = asset.atlasDataByState[stateName] else {
                throw A2DError.stateNotFound(stateName)
            }
            progressiveAtlasCGImage = try A2DDecoder.makeAtlasCGImage(atlasData: atlasData)
        }

        let preloadCount = max(1, frameCountForSeconds(progressiveAllDurations, seconds: preloadSeconds))
        let initialEnd = min(totalFrames, preloadCount)
        let initialFrames = try decodeFramesRange(start: 0, endExclusive: initialEnd)
        progressiveFrameDurations = Array(progressiveAllDurations.prefix(initialEnd))
        progressiveNextDecodeIndex = initialEnd

        currentDecodedState = A2DDecodedState(
            stateName: stateName,
            frames: initialFrames,
            frameDurations: progressiveFrameDurations
        )
    }

    private func frameCountForSeconds(_ durations: [TimeInterval], seconds: Double) -> Int {
        let target = max(0.001, seconds)
        var sum: TimeInterval = 0
        var count = 0
        for d in durations {
            sum += d
            count += 1
            if sum >= target {
                break
            }
        }
        return max(1, count)
    }

    private func decodeFramesRange(start: Int, endExclusive: Int) throws -> [A2DPlatformImage] {
        guard let stateInfo = progressiveStateInfo else { return [] }
        guard start < endExclusive else { return [] }

        var out: [A2DPlatformImage] = []
        out.reserveCapacity(endExclusive - start)

        let storage = (stateInfo.storage?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? "atlas")
        if storage == "raw" {
            for idx in start..<endExclusive {
                out.append(
                    try A2DDecoder.decodeSingleFrameFromRaw(
                        frameData: progressiveRawFrameData[idx],
                        frameInfo: stateInfo.frames[idx],
                        index: idx
                    )
                )
            }
        } else {
            guard let atlasCGImage = progressiveAtlasCGImage else {
                throw A2DError.invalidAtlasImage
            }
            for idx in start..<endExclusive {
                out.append(
                    try A2DDecoder.decodeSingleFrameFromAtlas(
                        atlasCGImage: atlasCGImage,
                        frameInfo: stateInfo.frames[idx]
                    )
                )
            }
        }
        return out
    }

    private func startBackgroundDecodingIfNeeded() {
        guard let stateInfo = progressiveStateInfo else { return }
        guard progressiveNextDecodeIndex < stateInfo.frames.count else {
            progressiveIsLoading = false
            return
        }
        guard !progressiveIsLoading else { return }

        progressiveIsLoading = true
        let token = progressiveLoadToken

        progressiveDecodeQueue.async { [weak self] in
            Task { [weak self] in
                await self?.decodeNextBatch(token: token)
            }
        }
    }

    private nonisolated func decodeNextBatch(token: UUID) async {
        typealias DecodePlan = (
            stateInfo: A2DStateInfo,
            start: Int,
            end: Int,
            storage: String,
            durations: [TimeInterval],
            rawFrameData: [Data],
            atlasCGImage: CGImage?
        )

        let plan: DecodePlan? = await MainActor.run { [weak self] in
            guard let self else { return nil }
            guard let stateInfo = self.progressiveStateInfo else {
                self.progressiveIsLoading = false
                return nil
            }

            let start = self.progressiveNextDecodeIndex
            if start >= stateInfo.frames.count {
                self.progressiveIsLoading = false
                return nil
            }

            guard start < self.progressiveAllDurations.count else {
                self.progressiveIsLoading = false
                return nil
            }

            let remainingDurations = Array(self.progressiveAllDurations[start...])
            guard !remainingDurations.isEmpty else {
                self.progressiveIsLoading = false
                return nil
            }

            let batchFrames = self.frameCountForSeconds(remainingDurations, seconds: self.backgroundBatchSeconds)
            let endByDurations = start + max(1, batchFrames)
            let end = min(stateInfo.frames.count, min(self.progressiveAllDurations.count, endByDurations))
            guard end > start else {
                self.progressiveIsLoading = false
                return nil
            }

            let storage = (stateInfo.storage?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? "atlas")
            return (
                stateInfo: stateInfo,
                start: start,
                end: end,
                storage: storage,
                durations: self.progressiveAllDurations,
                rawFrameData: self.progressiveRawFrameData,
                atlasCGImage: self.progressiveAtlasCGImage
            )
        }

        guard let plan else {
            return
        }

        let frames: [A2DPlatformImage]
        do {
            var decodedFrames: [A2DPlatformImage] = []
            decodedFrames.reserveCapacity(plan.end - plan.start)

            if plan.storage == "raw" {
                for idx in plan.start..<plan.end {
                    decodedFrames.append(
                        try A2DDecoder.decodeSingleFrameFromRaw(
                            frameData: plan.rawFrameData[idx],
                            frameInfo: plan.stateInfo.frames[idx],
                            index: idx
                        )
                    )
                }
            } else {
                guard let atlasCGImage = plan.atlasCGImage else {
                    await MainActor.run { [weak self] in
                        self?.progressiveIsLoading = false
                    }
                    return
                }
                for idx in plan.start..<plan.end {
                    decodedFrames.append(
                        try A2DDecoder.decodeSingleFrameFromAtlas(
                            atlasCGImage: atlasCGImage,
                            frameInfo: plan.stateInfo.frames[idx]
                        )
                    )
                }
            }
            frames = decodedFrames
        } catch {
            await MainActor.run { [weak self] in
                self?.progressiveIsLoading = false
            }
            return
        }

        let durationsAppend = Array(plan.durations[plan.start..<plan.end])

        await MainActor.run { [weak self] in
            guard let self else { return }
            guard self.progressiveLoadToken == token else { return }
            guard var decoded = self.currentDecodedState else {
                self.progressiveIsLoading = false
                return
            }

            var newFrames = decoded.frames
            newFrames.append(contentsOf: frames)
            self.progressiveFrameDurations.append(contentsOf: durationsAppend)

            decoded = A2DDecodedState(
                stateName: decoded.stateName,
                frames: newFrames,
                frameDurations: self.progressiveFrameDurations
            )
            self.currentDecodedState = decoded
            self.playbackFrameIndices = Array(0..<newFrames.count)
            self.progressiveNextDecodeIndex = plan.end

            if self.progressiveNextDecodeIndex < plan.stateInfo.frames.count {
                self.progressiveDecodeQueue.async { [weak self] in
                    Task { [weak self] in
                        await self?.decodeNextBatch(token: token)
                    }
                }
            } else {
                self.progressiveIsLoading = false
            }
        }
    }

    private func playBgmForCurrentState(looping: Bool) {
        guard
            let asset,
            let stateName = currentStateName,
            let bgmData = asset.bgmData(for: stateName)
        else {
            bgmPlayer?.stop()
            bgmPlayer = nil
            return
        }

        do {
            let player = try AVAudioPlayer(data: bgmData)
            player.numberOfLoops = looping ? -1 : 0
            player.prepareToPlay()
            player.play()
            bgmPlayer = player
        } catch {
            bgmPlayer = nil
        }
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
        resetProgressiveState()
        self.asset = asset
        currentDecodedState = nil
        lastSingleTapEventTime = nil
        _ = selectState(nil, restart: true)

        if
            automaticallySizesToContent,
            let decodedState = currentDecodedState,
            !decodedState.frames.isEmpty
        {
            bounds.size = decodedState.frames[0].size
        }
    }

    private func render(frameAt index: Int) {
        guard
            let decodedState = currentDecodedState,
            playbackFrameIndices.indices.contains(index)
        else {
            return
        }
        let frameIndex = playbackFrameIndices[index]
        guard decodedState.frames.indices.contains(frameIndex) else {
            return
        }
        imageView.image = decodedState.frames[frameIndex]
    }

    private func scheduleNextFrame() {
        guard isPlaying, let _ = asset, let decodedState = currentDecodedState else {
            return
        }
        guard !playbackFrameIndices.isEmpty else {
            if progressiveIsLoading {
                let work = DispatchWorkItem { [weak self] in
                    guard let self else { return }
                    if self.isPlaying {
                        self.scheduleNextFrame()
                    }
                }
                scheduledWork = work
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.02, execute: work)
            } else {
                pause()
            }
            return
        }

        let actualFrameIndex = playbackFrameIndices[currentFrameIndex]
        let delay = decodedState.frameDurations[actualFrameIndex]
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.isPlaying,
                  let _ = self.asset,
                  let _ = self.currentDecodedState else {
                return
            }
            guard !self.playbackFrameIndices.isEmpty else {
                self.pause()
                return
            }

            let nextIndex = self.currentFrameIndex + 1
            if nextIndex >= self.playbackFrameIndices.count {
                if self.progressiveIsLoading {
                    // 已经到当前已解码末尾，等待下一批到达
                    self.currentFrameIndex = self.playbackFrameIndices.count - 1
                    let waitWork = DispatchWorkItem { [weak self] in
                        guard let self else { return }
                        if self.isPlaying {
                            self.scheduleNextFrame()
                        }
                    }
                    self.scheduledWork = waitWork
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.02, execute: waitWork)
                    return
                }

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
        _ = decodedState  // suppress unused warning; delay already captured

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
