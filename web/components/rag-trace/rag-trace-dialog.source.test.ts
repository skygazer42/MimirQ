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
    expect(src).not.toContain("import { RagTracePanel } from '@/components/rag-trace/rag-trace-panel'")
  })

  it('moves dialog title and loading copy into next-intl lookups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-dialog.tsx'), 'utf8')

    expect(src).toContain("useTranslations('RagTrace')")
    expect(src).toContain('t("dialog.title")')
    expect(src).toContain('t("dialog.loadingMessage")')
    expect(src).toContain('t("dialog.loadingSrMessage")')
  })

  it('keeps the trace body scrollable so lower timeline sections remain reachable', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'rag-trace-dialog.tsx'), 'utf8')

    expect(src).toContain('flex max-h-[90vh] max-w-6xl flex-col gap-0 overflow-hidden p-0')
    expect(src).toContain('shrink-0 border-b border-border/60 px-6 py-4 pr-12')
    expect(src).toContain('min-h-0 overflow-y-auto px-6 py-4')
    expect(src).not.toContain('className="min-h-0 overflow-hidden"')
  })
})
