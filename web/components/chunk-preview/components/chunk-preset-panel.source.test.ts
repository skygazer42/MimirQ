import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk preset panel source', () => {
  it('avoids any-based payload helpers and error catches', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-preset-panel.tsx'), 'utf8')

    expect(src).not.toContain(': any')
    expect(src).not.toContain('as any')
    expect(src).not.toContain('Record<string, any>')
  })

  it('keeps presets as database records without local import or export controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-preset-panel.tsx'), 'utf8')

    expect(src).not.toContain("t('chunkPresetPanel.export')")
    expect(src).not.toContain("t('chunkPresetPanel.import')")
    expect(src).not.toContain('downloadTextFile')
    expect(src).not.toContain('type="file"')
  })
})
