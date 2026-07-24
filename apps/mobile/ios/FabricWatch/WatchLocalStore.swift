import Foundation
import UIKit

/// One decoded, render-ready spritesheet: validated geometry plus the atlas
/// bitmap. Kept whole so views never juggle a manifest without its pixels.
struct WatchSpriteAtlas {
    let manifest: WatchSpriteManifest
    let image: UIImage
}

/// Watch-local persistence: the bounded note queue, the last relayed context,
/// the current sprite, and the widget snapshot. Everything lives in the app
/// container (or the shared app-group container for the widget snapshot);
/// nothing here is a credential.
@MainActor
final class WatchLocalStore {
    private let baseURL: URL

    init() {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory
        baseURL = base.appending(path: "FabricWatch", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: baseURL, withIntermediateDirectories: true)
    }

    // MARK: - Note queue

    private var notesURL: URL { baseURL.appending(path: "notes.json") }

    func loadNotes() -> [WatchQuickNote] {
        guard let data = try? Data(contentsOf: notesURL),
              let rows = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]]
        else { return [] }
        // Stored rows reuse the wire codec so one validation rule covers both.
        return rows.compactMap { WatchQuickNote(payload: $0) }
    }

    func saveNotes(_ notes: [WatchQuickNote]) {
        let rows = notes.map { $0.encoded() }
        guard let data = try? JSONSerialization.data(withJSONObject: rows) else { return }
        try? data.write(to: notesURL, options: .atomic)
    }

    // MARK: - Last context

    private var contextURL: URL { baseURL.appending(path: "context.json") }

    func loadContext() -> WatchRelayContext? {
        guard let data = try? Data(contentsOf: contextURL),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return WatchRelayContext(payload: payload)
    }

    func saveContext(_ context: WatchRelayContext) {
        guard let data = try? JSONSerialization.data(withJSONObject: context.encoded()) else { return }
        try? data.write(to: contextURL, options: .atomic)
    }

    // MARK: - Sprite library

    private var spriteDataURL: URL { baseURL.appending(path: "sprite.atlas") }
    private var spriteManifestURL: URL { baseURL.appending(path: "sprite.json") }

    /// Adopt one transferred atlas as the current sprite. The image is decoded
    /// before anything is persisted, so a corrupt transfer can't evict a
    /// working sprite.
    func installSprite(from fileURL: URL, manifest: WatchSpriteManifest) -> WatchSpriteAtlas? {
        defer { try? FileManager.default.removeItem(at: fileURL) }
        guard let data = try? Data(contentsOf: fileURL),
              let image = UIImage(data: data),
              let manifestData = try? JSONSerialization.data(withJSONObject: manifest.encoded())
        else { return nil }
        try? data.write(to: spriteDataURL, options: .atomic)
        try? manifestData.write(to: spriteManifestURL, options: .atomic)
        return WatchSpriteAtlas(manifest: manifest, image: image)
    }

    func loadSprite() -> WatchSpriteAtlas? {
        guard let manifestData = try? Data(contentsOf: spriteManifestURL),
              let payload = try? JSONSerialization.jsonObject(with: manifestData) as? [String: Any],
              let manifest = WatchSpriteManifest(payload: payload),
              let data = try? Data(contentsOf: spriteDataURL),
              let image = UIImage(data: data)
        else { return nil }
        return WatchSpriteAtlas(manifest: manifest, image: image)
    }

    // MARK: - Widget snapshot (shared app group)

    func saveWidgetSnapshot(_ snapshot: [String: Any]) {
        guard let groupID = Bundle.main.object(
            forInfoDictionaryKey: WatchWidgetSnapshot.appGroupInfoKey
        ) as? String,
              let defaults = UserDefaults(suiteName: groupID)
        else { return }
        defaults.set(snapshot, forKey: WatchWidgetSnapshot.defaultsKey)
    }
}
