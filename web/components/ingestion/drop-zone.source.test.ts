import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion drop zone source', () => {
  it('uses a forward-ref handle and counter-based drag tracking', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'drop-zone.tsx'), 'utf8')

    expect(src).toContain('React.forwardRef')
    expect(src).toContain('triggerFilePicker: (options?: { precheckOnly?: boolean }) => void')
    expect(src).toContain('uploadFiles: (files: File[]) => Promise<void>')
    expect(src).toContain('dragCounterRef')
    expect(src).toContain("datasetApi.list({ limit: 200 })")
    expect(src).toContain('aria-live="polite"')
  })

  it('can upload assessment samples without starting the formal ingest pipeline', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'drop-zone.tsx'), 'utf8')

    expect(src).toContain('precheckOnly?: boolean')
    expect(src).toContain('precheck_only: precheckOnly')
    expect(src).toContain('uploadModeRef.current = options?.precheckOnly ?? defaultPrecheckOnly')
    expect(src).toContain('上传样本评估')
    expect(src).toContain('只生成入库前摸底和文件布局难度分析')
    expect(src).toContain('开始评估')
    expect(src).toContain('开始入库')
  })
})
