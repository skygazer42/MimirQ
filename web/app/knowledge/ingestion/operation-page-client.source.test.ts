import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readOperationSource() {
  return fs.readFileSync(path.resolve(__dirname, 'operation-page-client.tsx'), 'utf8')
}

describe('ingestion source integration', () => {
  it('keeps every real ingestion source and submit path available', () => {
    const src = readOperationSource()

    for (const source of ['local', 'folder', 'url', 'object', 'api']) {
      expect(src).toContain(`value: '${source}'`)
    }
    expect(src).toContain('SourceConfiguration source="folder"')
    expect(src).toContain('SourceConfiguration source="url"')
    expect(src).toContain('SourceConfiguration source="object"')
    expect(src).toContain('SourceConfiguration source="api"')
    expect(src).toContain("uploadFiles(draft.executionMode === 'upload_only' ? 'upload_only' : 'ingest')")
    expect(src).toContain('buildPipeline(draft)')
  })
})
