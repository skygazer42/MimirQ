// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge evidence page source', () => {
  it('lazy-loads the expert evidence workbench behind a branded loading shell', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import dynamic from 'next/dynamic'")
    expect(src).toContain("import { PageLoading } from '@/components/ui/page-loading'")
    expect(src).toContain("const EvidenceWorkbench = dynamic(() => import('@/components/ragviz/evidence-workbench').then((mod) => mod.EvidenceWorkbench), {")
    expect(src).toContain('ssr: false')
    expect(src).toContain('正在加载 Evidence Workbench...')
    expect(src).not.toContain("import { EvidenceWorkbench } from '@/components/ragviz/evidence-workbench'")
  })
})
