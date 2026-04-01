import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('monaco asset sync wiring', () => {
  it('keeps local Monaco asset sync wired into developer and build entrypoints', () => {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.predev).toBe('node scripts/sync-monaco-assets.mjs')
    expect(pkg.scripts?.prebuild).toBe('node scripts/sync-monaco-assets.mjs')
    expect(fs.existsSync(path.resolve(__dirname, 'sync-monaco-assets.mjs'))).toBe(true)
  })

  it('copies Monaco editor runtime files into the project-controlled public path', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sync-monaco-assets.mjs'), 'utf8')

    expect(src).toContain("require.resolve('monaco-editor/package.json')")
    expect(src).toContain("path.join(WEB_ROOT, 'public', 'monaco', 'vs')")
    expect(src).toContain("path.join(monacoRoot, 'min', 'vs')")
    expect(src).toContain('fs.cp(')
  })

  it('also copies pdf.js runtime assets into a project-controlled public path for native browser loading', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sync-monaco-assets.mjs'), 'utf8')

    expect(src).toContain("require.resolve('pdfjs-dist/package.json')")
    expect(src).toContain("path.join(WEB_ROOT, 'public', 'pdfjs')")
    expect(src).toContain("['build', 'cmaps', 'standard_fonts', 'wasm', 'iccs']")
    expect(src).toContain('path.join(pdfjsRoot, assetDir)')
    expect(src).toContain('path.join(PDFJS_OUT_DIR, assetDir)')
  })
})
