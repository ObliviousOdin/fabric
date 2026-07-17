# Fabric desktop icons

The desktop package consumes the deterministic Fabric bundle generated under
`apps/design-system/dist/brand`. The app/touch assets place the compact mark on
the neutral product tile; the Windows container uses the transparent compact
mark. The bracket belongs only to full wordmark assets and is never used here.

| Fabric asset | Rendition | SHA-256 |
| --- | --- | --- |
| `icon.icns` | macOS multi-resolution app icon | `a96f68ea0dfc250906f52b078b2b5d07b63a999c858e30dc3721d56fc72cb684` |
| `icon.ico` | Windows multi-resolution compact mark | `5c00b2f71862baeb2e84f8ea8e1c92bce71ae4cb7cc9b2ba1fe4e0b9ac4ff5db` |
| `icon.png` | Canonical 1024×1024 app icon | `1a514b79784db3179b2f924dd81bd318cf4cd2605cc24d3fb9d9a43ff6abcfc6` |
| `../public/apple-touch-icon.png` | 512×512 app/touch icon | `f7f37fdca4e39a731c7e58cfb694b7cc60cb434160a0fc84b9de37532465a8be` |

The canonical paths consumed by packaging are declared in
`../branding/fabric.json`. Keep the formats visually identical and update the
integrity contract whenever these assets intentionally change.
