import SwiftUI
import UIKit

public struct Ani2DPlayerContainerView: UIViewRepresentable {
    public enum Source {
        case fileURL(URL)
        case data(Data)
    }

    public let source: Source
    public var stateName: String? = nil
    public var loop: Bool = true
    public var autoPlay: Bool = true
    public var onInteraction: ((A2DInteractionEvent) -> Void)?
    public var onError: ((Error) -> Void)?

    public init(
        source: Source,
        stateName: String? = nil,
        loop: Bool = true,
        autoPlay: Bool = true,
        onInteraction: ((A2DInteractionEvent) -> Void)? = nil,
        onError: ((Error) -> Void)? = nil
    ) {
        self.source = source
        self.stateName = stateName
        self.loop = loop
        self.autoPlay = autoPlay
        self.onInteraction = onInteraction
        self.onError = onError
    }

    public func makeUIView(context: Context) -> A2DPlayerView {
        let view = A2DPlayerView()
        view.backgroundColor = .clear
        view.isOpaque = false
        view.onInteraction = onInteraction
        loadIfNeeded(into: view, context: context)
        return view
    }

    public func updateUIView(_ uiView: A2DPlayerView, context: Context) {
        context.coordinator.source = source
        context.coordinator.stateName = stateName
        context.coordinator.loop = loop
        context.coordinator.autoPlay = autoPlay
        context.coordinator.onInteraction = onInteraction
        context.coordinator.onError = onError
        uiView.onInteraction = onInteraction
        loadIfNeeded(into: uiView, context: context)

        if autoPlay {
            if let stateName {
                _ = uiView.play(stateName: stateName, loop: loop)
            } else {
                uiView.play(loop: loop)
            }
        }
    }

    public func makeCoordinator() -> Coordinator {
        Coordinator(
            source: source,
            stateName: stateName,
            loop: loop,
            autoPlay: autoPlay,
            onInteraction: onInteraction,
            onError: onError
        )
    }

    private func loadIfNeeded(into view: A2DPlayerView, context: Context) {
        do {
            switch source {
            case .fileURL(let url):
                let key = "url:\(url.absoluteString)"
                guard key != context.coordinator.lastLoadedKey else {
                    return
                }
                try view.load(from: url)
                context.coordinator.lastLoadedKey = key
            case .data(let data):
                let key = "data:\(data.count):\(data.hashValue)"
                guard key != context.coordinator.lastLoadedKey else {
                    return
                }
                try view.load(data: data)
                context.coordinator.lastLoadedKey = key
            }

            if autoPlay {
                if let stateName {
                    _ = view.play(stateName: stateName, loop: loop)
                } else {
                    view.play(loop: loop)
                }
            }
        } catch {
            onError?(error)
        }
    }

    public final class Coordinator {
        fileprivate var source: Source
        fileprivate var stateName: String?
        fileprivate var loop: Bool
        fileprivate var autoPlay: Bool
        fileprivate var onInteraction: ((A2DInteractionEvent) -> Void)?
        fileprivate var onError: ((Error) -> Void)?
        fileprivate var lastLoadedKey: String?

        fileprivate init(
            source: Source,
            stateName: String?,
            loop: Bool,
            autoPlay: Bool,
            onInteraction: ((A2DInteractionEvent) -> Void)?,
            onError: ((Error) -> Void)?
        ) {
            self.source = source
            self.stateName = stateName
            self.loop = loop
            self.autoPlay = autoPlay
            self.onInteraction = onInteraction
            self.onError = onError
        }
    }
}

public struct Ani2DPlayerDemoSwiftUIView: View {
    private static let maxLogCount = 60

    private let source: Ani2DPlayerContainerView.Source
    @State private var errorMessage: String?
    @State private var interactionLogs: [String] = []

    public init(fileURL: URL) {
        self.source = .fileURL(fileURL)
    }

    public init(data: Data) {
        self.source = .data(data)
    }

    public var body: some View {
        VStack(spacing: 14) {
            LinearGradient(
                colors: [.black.opacity(0.15), .blue.opacity(0.2), .mint.opacity(0.15)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .overlay {
                Ani2DPlayerContainerView(
                    source: source,
                    loop: true,
                    autoPlay: true,
                    onInteraction: { event in
                        appendInteractionLog(event)
                    },
                    onError: { err in
                        errorMessage = err.localizedDescription
                    }
                )
                .frame(width: 300, height: 240)
                .background(Color.clear)
            }
            .frame(height: 260)
            .clipShape(RoundedRectangle(cornerRadius: 14))

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Interaction Logs")
                        .font(.headline)
                    Spacer()
                    Button("Clear") {
                        interactionLogs.removeAll()
                    }
                    .font(.caption)
                }

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 6) {
                        if interactionLogs.isEmpty {
                            Text("暂无交互事件，点击/双击/长按/拖拽动画区域可查看日志")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        } else {
                            ForEach(Array(interactionLogs.enumerated()), id: \ .offset) { _, line in
                                Text(line)
                                    .font(.caption.monospaced())
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                    .padding(.vertical, 6)
                }
                .frame(maxHeight: 190)
                .padding(10)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 10))

                if let errorMessage {
                    Text(errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .padding(.top, 2)
                }
            }
            .padding(.horizontal, 12)
        }
        .padding(12)
    }

    private func appendInteractionLog(_ event: A2DInteractionEvent) {
        let message = String(
            format: "[%@] t=(%.1f, %.1f) n=(%.3f, %.3f) d=(%.1f, %.1f) v=(%.1f, %.1f) state=%@ frame=%@",
            event.type.rawValue,
            event.location.x,
            event.location.y,
            event.normalizedLocation.x,
            event.normalizedLocation.y,
            event.translation.x,
            event.translation.y,
            event.velocity.x,
            event.velocity.y,
            event.stateName ?? "nil",
            event.displayedFrameIndex.map(String.init) ?? "nil"
        )

        interactionLogs.insert(message, at: 0)
        if interactionLogs.count > Self.maxLogCount {
            interactionLogs.removeLast(interactionLogs.count - Self.maxLogCount)
        }
    }
}
