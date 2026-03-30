import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge similarity page source', () => {
  it('lazy-loads the similarity workbench so expert tooling stays off the critical path', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import dynamic from 'next/dynamic'")
    expect(src).toContain("import { PageLoading } from '@/components/ui/page-loading'")
    expect(src).toContain("const RagvizSimilarityWorkbench = dynamic(() => import('@/components/ragviz/similarity-workbench').then((mod) => mod.RagvizSimilarityWorkbench), {")
    expect(src).toContain('ssr: false')
    expect(src).toContain('正在加载 Similarity Workbench...')
    expect(src).not.toContain("import { RagvizSimilarityWorkbench } from '@/components/ragviz/similarity-workbench'")
  })
})
