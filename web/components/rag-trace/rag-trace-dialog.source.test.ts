import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('rag trace dialog source', () => {
  it('lazy-loads the heavy trace panel only when the dialog is used', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-dialog.tsx'), 'utf8')

    expect(src).toContain("import dynamic from 'next/dynamic'")
    expect(src).toContain("import { PageLoading } from '@/components/ui/page-loading'")
    expect(src).toContain("const RagTracePanel = dynamic(() => import('@/components/rag-trace/rag-trace-panel').then((mod) => mod.RagTracePanel), {")
    expect(src).toContain('ssr: false')
    expect(src).toContain('正在加载 RAG Trace...')
    expect(src).not.toContain("import { RagTracePanel } from '@/components/rag-trace/rag-trace-panel'")
  })
})
