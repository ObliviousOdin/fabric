# Fabric desktop icons

The desktop package consumes the deterministic Fabric bundle generated under
`apps/design-system/dist/brand`. The app/touch assets place the compact mark on
the neutral product tile; the Windows container uses the transparent compact
mark. The bracket belongs only to full wordmark assets and is never used here.

| Fabric asset | Rendition | SHA-256 |
| --- | --- | --- |
| `icon.icns` | macOS multi-resolution app icon | `65cb2e27be3495eaa650f7b1d5eb6f52df1ab40dc82f04ab510d98cc06900e6a` |
| `icon.ico` | Windows multi-resolution compact mark | `e4e50da48100bf0250da499e4511c13759457a6bdd8454a629d1e1413578a00d` |
| `icon.png` | Canonical 1024×1024 app icon | `e51a099027364620e2758172128ad42dc0a498fee52ab3ec4b2c5197681a39de` |
| `../public/apple-touch-icon.png` | 512×512 app/touch icon | `5cf6929b5b0b6670595d502e2c67f14e6ac5a8e7cea0f5d3de1390646034b230` |

The canonical paths consumed by packaging are declared in
`../branding/fabric.json`. Keep the formats visually identical and update the
integrity contract whenever these assets intentionally change.
