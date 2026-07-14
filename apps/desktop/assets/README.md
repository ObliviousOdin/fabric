# Fabric desktop icons

The desktop package consumes the deterministic Fabric bundle generated under
`apps/design-system/dist/brand`. The app/touch assets place the compact mark on
the neutral product tile; the Windows container uses the transparent compact
mark. The bracket belongs only to full wordmark assets and is never used here.

| Fabric asset | Rendition | SHA-256 |
| --- | --- | --- |
| `icon.icns` | macOS multi-resolution app icon | `e42ecf7a919ba0875fcf84b6fd8c7ea3698071dd528bba9b5a49bf42343b415d` |
| `icon.ico` | Windows multi-resolution compact mark | `d051bc76c855d330562b24776b9e02c72a45c9867913323dd62be82d7629eaed` |
| `icon.png` | Canonical 1024×1024 app icon | `863c6c788dcea5f0e2e96ed1c0fa6b487b0333396521970003fcd0e7f227f895` |
| `../public/apple-touch-icon.png` | 512×512 app/touch icon | `2a40fe90fd2f9fdbe8194487779d85208e095cd2a9378acf4df720d9336f3dff` |

The canonical paths consumed by packaging are declared in
`../branding/fabric.json`. Keep the formats visually identical and update the
integrity contract whenever these assets intentionally change.
