import Foundation

#if canImport(UIKit)
import UIKit
#endif

private struct Args {
    let a2dPath: String
    let playSeconds: TimeInterval

    static func parse() -> Args {
        var path = "ani2d/output/out.a2d"
        var seconds: TimeInterval = 1.5

        var i = 1
        while i < CommandLine.arguments.count {
            let arg = CommandLine.arguments[i]
            if arg == "--a2d" || arg == "--a2dPath" {
                if i + 1 < CommandLine.arguments.count {
                    path = CommandLine.arguments[i + 1]
                    i += 1
                }
            } else if arg == "--playSeconds" {
                if i + 1 < CommandLine.arguments.count,
                   let value = Double(CommandLine.arguments[i + 1]),
                   value > 0 {
                    seconds = value
                    i += 1
                }
            }
            i += 1
        }

        return Args(a2dPath: path, playSeconds: seconds)
    }
}

@main
struct TestPlayA2D {
    static func main() {
        let args = Args.parse()
        let url = URL(fileURLWithPath: args.a2dPath)

        print("[test_play_a2d] input: \(url.path)")

        do {
            let decoded = try A2DDecoder.decode(fileURL: url)
            print("[test_play_a2d] decode ok")
            print("[test_play_a2d] frameCount=\(decoded.metadata.frameCount), atlas=\(decoded.metadata.atlas.width)x\(decoded.metadata.atlas.height)")
            print("[test_play_a2d] firstDuration=\(decoded.frameDurations.first ?? 0)")
        } catch {
            print("[test_play_a2d] decode failed: \(error.localizedDescription)")
            exit(2)
        }

        #if canImport(UIKit)
        runUIKitPlaybackSmokeTest(url: url, playSeconds: args.playSeconds)
        #else
        print("[test_play_a2d] UIKit unavailable in this runtime, skip A2DPlayerView play test")
        #endif
    }

    #if canImport(UIKit)
    @MainActor
    private static func runUIKitPlaybackSmokeTest(url: URL, playSeconds: TimeInterval) {
        var done = false
        var success = true

        DispatchQueue.main.async {
            let player = A2DPlayerView(frame: CGRect(x: 0, y: 0, width: 320, height: 240))
            do {
                try player.load(from: url)
                player.play(loop: true)
                print("[test_play_a2d] play started")
            } catch {
                print("[test_play_a2d] player load/play failed: \(error.localizedDescription)")
                success = false
                done = true
                return
            }

            DispatchQueue.main.asyncAfter(deadline: .now() + playSeconds) {
                player.pause()
                player.showLastFrame()
                print("[test_play_a2d] play paused and moved to last frame")
                done = true
            }
        }

        while !done {
            RunLoop.main.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
        }

        if success {
            print("[test_play_a2d] UIKit render logic smoke test passed")
            exit(0)
        } else {
            exit(3)
        }
    }
    #endif
}
