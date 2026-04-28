import UIKit

@MainActor
public final class Ani2DPlayerDemoViewController: UIViewController {
    private let playerView = A2DPlayerView()
    private let stack = UIStackView()
    private let playButton = UIButton(type: .system)
    private let pauseButton = UIButton(type: .system)
    private let stopButton = UIButton(type: .system)
    private let onceButton = UIButton(type: .system)

    private let a2dURL: URL

    public init(a2dURL: URL) {
        self.a2dURL = a2dURL
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    public override func viewDidLoad() {
        super.viewDidLoad()
        title = "A2D Demo"
        view.backgroundColor = .systemBackground

        setupPlayerView()
        setupButtons()
        loadAndPlay()
    }

    public override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        if isMovingFromParent || isBeingDismissed {
            playerView.stop()
        } else {
            playerView.pause()
        }
    }

    private func setupPlayerView() {
        let host = UIView()
        host.translatesAutoresizingMaskIntoConstraints = false
        host.backgroundColor = UIColor.secondarySystemBackground
        host.layer.cornerRadius = 12
        host.clipsToBounds = true

        playerView.translatesAutoresizingMaskIntoConstraints = false
        playerView.backgroundColor = .clear

        view.addSubview(host)
        host.addSubview(playerView)

        NSLayoutConstraint.activate([
            host.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            host.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 24),
            host.widthAnchor.constraint(equalToConstant: 300),
            host.heightAnchor.constraint(equalToConstant: 240),

            playerView.leadingAnchor.constraint(equalTo: host.leadingAnchor),
            playerView.trailingAnchor.constraint(equalTo: host.trailingAnchor),
            playerView.topAnchor.constraint(equalTo: host.topAnchor),
            playerView.bottomAnchor.constraint(equalTo: host.bottomAnchor)
        ])
    }

    private func setupButtons() {
        stack.axis = .horizontal
        stack.alignment = .fill
        stack.distribution = .fillEqually
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false

        playButton.setTitle("Play", for: .normal)
        pauseButton.setTitle("Pause", for: .normal)
        stopButton.setTitle("Stop", for: .normal)
        onceButton.setTitle("PlayOnce", for: .normal)

        playButton.addTarget(self, action: #selector(onPlay), for: .touchUpInside)
        pauseButton.addTarget(self, action: #selector(onPause), for: .touchUpInside)
        stopButton.addTarget(self, action: #selector(onStop), for: .touchUpInside)
        onceButton.addTarget(self, action: #selector(onPlayOnce), for: .touchUpInside)

        stack.addArrangedSubview(playButton)
        stack.addArrangedSubview(pauseButton)
        stack.addArrangedSubview(stopButton)
        stack.addArrangedSubview(onceButton)

        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 290),
            stack.heightAnchor.constraint(equalToConstant: 44)
        ])
    }

    private func loadAndPlay() {
        do {
            try playerView.load(from: a2dURL)
            playerView.play(loop: true)
        } catch {
            let alert = UIAlertController(
                title: "A2D Load Failed",
                message: error.localizedDescription,
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "OK", style: .default))
            present(alert, animated: true)
        }
    }

    @objc private func onPlay() {
        playerView.play(loop: true)
    }

    @objc private func onPause() {
        playerView.pause()
    }

    @objc private func onStop() {
        playerView.stop()
    }

    @objc private func onPlayOnce() {
        playerView.play(loop: false)
    }
}
