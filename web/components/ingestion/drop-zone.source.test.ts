import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion drop zone source', () => {
  it('uses a forward-ref handle and counter-based drag tracking', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'drop-zone.tsx'), 'utf8')

    expect(src).toContain('React.forwardRef')
    expect(src).toContain('triggerFilePicker: () => void')
    expect(src).toContain('uploadFiles: (files: File[]) => Promise<void>')
    expect(src).toContain('dragCounterRef')
    expect(src).toContain("datasetApi.list({ limit: 200 })")
    expect(src).toContain('aria-live="polite"')
  })
})
