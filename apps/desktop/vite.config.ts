import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import fs from 'fs'

import { loadDesktopBrand, toPublicDesktopBrand } from './scripts/desktop-brand.mjs'

const desktopBrand = toPublicDesktopBrand(loadDesktopBrand())
const escapeHtml = (value: string): string =>
  value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')

// `hgui` symlinks a worktree's node_modules to the main checkout. Vite realpaths
// those before enforcing server.fs.allow, so codicon/font assets resolve outside
// the worktree root and 404. Whitelist the real node_modules locations.
const real = (p: string): string | null => {
  try {
    return fs.realpathSync(p)
  } catch {
    return null
  }
}

const fsAllow = [
  ...new Set(
    [
      path.resolve(__dirname, '../..'),
      real(path.resolve(__dirname, 'node_modules')),
      real(path.resolve(__dirname, '../../node_modules'))
    ].filter((p): p is string => p !== null)
  )
]

export default defineConfig({
  base: './',
  define: {
    __FABRIC_DESKTOP_BRAND__: JSON.stringify(desktopBrand)
  },
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'fabric-desktop-brand-title',
      transformIndexHtml: html =>
        html.replace(/<title>[^<]*<\/title>/, `<title>${escapeHtml(desktopBrand.desktopName)}</title>`)
    }
  ],
  css: {
    // Pin an explicit (empty) PostCSS config. Tailwind is handled entirely by
    // `@tailwindcss/vite`, so the renderer needs no PostCSS plugins — and
    // without this, Vite's `postcss-load-config` walks UP the filesystem
    // looking for a stray `postcss.config.*` / `tailwind.config.*`. The desktop
    // build runs from inside the user's home tree (e.g.
    // `C:\Users\<name>\AppData\Local\fabric\fabric-agent\apps\desktop`), so an
    // unrelated Tailwind v3 config higher up the tree gets picked up and
    // reprocesses our v4 stylesheet, failing the build with
    // "`@layer base` is used but no matching `@tailwind base` directive is
    // present." Pinning the config makes the build hermetic.
    postcss: { plugins: [] }
  },
  build: {
    // Shiki ships many dynamic language chunks. A constrained vendor split
    // keeps the packaged asset count manageable without inlining dynamic
    // imports: Rolldown's single-chunk mode can emit an undeclared
    // `__reExport` helper for Shiki, leaving Electron with a white window.
    // Keep the warning ceiling above the vendor bundle while retaining a
    // useful regression alarm for unexpected growth.
    chunkSizeWarningLimit: 25000,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'vendor',
              test: /[\\/]node_modules[\\/]/,
              priority: 10,
              includeDependenciesRecursively: true,
              minSize: 0,
              minShareCount: 1
            }
          ]
        }
      }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@fabric/shared': path.resolve(__dirname, '../shared/src'),
      react: path.resolve(__dirname, '../../node_modules/react'),
      'react-dom': path.resolve(__dirname, '../../node_modules/react-dom'),
      'react/jsx-dev-runtime': path.resolve(__dirname, '../../node_modules/react/jsx-dev-runtime.js'),
      'react/jsx-runtime': path.resolve(__dirname, '../../node_modules/react/jsx-runtime.js')
    },
    dedupe: ['react', 'react-dom']
  },
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    fs: {
      allow: fsAllow
    }
  },
  preview: {
    host: '127.0.0.1',
    port: 4174
  }
})
