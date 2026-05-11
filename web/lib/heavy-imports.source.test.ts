import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const RECHARTS_ENTRY_FILES = [
  '../app/datasets/[id]/profile/page.tsx',
  '../app/datasets/[id]/health/page.tsx',
  '../app/datasets/[id]/precheck/page.tsx',
  '../app/knowledge/ingestion/page.tsx',
  '../app/reports/page.tsx',
  '../app/observability/page.tsx',
  '../app/diagnostics/page.tsx',
  '../components/evaluation/holographic-radar.tsx',
  '../components/evaluation/queryset-health-tab.tsx',
  '../components/chunk-preview/components/workbench/sidebar.tsx',
]

describe('heavy import guards', () => {
  it('keeps direct recharts imports out of route entry files and shared shells', () => {
    for (const relPath of RECHARTS_ENTRY_FILES) {
      const src = fs.readFileSync(path.resolve(__dirname, relPath), 'utf8')
      expect(src, relPath).not.toMatch(/from ['"]recharts['"]/)
    }
  })

  it('removes the unused sandpack dependency', () => {
    const pkg = fs.readFileSync(path.resolve(__dirname, '../package.json'), 'utf8')
    expect(pkg).not.toContain('"@codesandbox/sandpack-react"')
  })

  it('keeps decorative Lottie runtime out of the frontend bundle', () => {
    const pkg = fs.readFileSync(path.resolve(__dirname, '../package.json'), 'utf8')
    const sidebar = fs.readFileSync(path.resolve(__dirname, '../components/sidebar.tsx'), 'utf8')

    expect(pkg).not.toContain('"lottie-react"')
    expect(sidebar).not.toContain('@/components/ui/lottie-animation')
    expect(sidebar).not.toContain('<LottieAnimation')
  })
})
