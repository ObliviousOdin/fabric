# Fabric desktop icons

The desktop package uses the purple Fabric mark checked into this directory.
`icon.png` is the canonical 1024×1024 source; the native formats and touch icon
are deterministic platform renditions of that same mark.

| Fabric asset | Rendition | SHA-256 |
| --- | --- | --- |
| `icon.icns` | macOS multi-resolution icon | `70c7a872086b0676eda9660efb7c02888ecc26019838aad17a4da30af15f6c34` |
| `icon.ico` | Windows 256×256 icon | `2c1e9d42f49f8448ab0fe29742ffa94aed479510ca762367e1ef9cdb3bcb99f2` |
| `icon.png` | Canonical 1024×1024 source | `17c9494ee2f22c936f22ca5ab1107904382a9dbd699c0b903a6134e51cb630e2` |
| `../public/apple-touch-icon.png` | 512×512 touch icon | `4016edb6894def96b39ba7e6558d88feaeaf61929040d08b1a3b9d8a17c7dc19` |

The canonical paths consumed by packaging are declared in
`../branding/fabric.json`. Keep the formats visually identical and update the
integrity contract whenever these assets intentionally change.
