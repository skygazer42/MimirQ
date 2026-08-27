import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readWorkspaceFile(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '../..', relativePath), 'utf8')
}

describe('global page title baseline', () => {
  it('keeps the shared PageHeader aligned with the flat knowledge title bar', () => {
    const src = readWorkspaceFile('components/ui/page-header.tsx')

    expect(src).toContain('min-h-14')
    expect(src).toContain('text-[19px]')
    expect(src).toContain('size-7 rounded-md')
    expect(src).toContain('left-1 h-px w-12 bg-info/70')
    expect(src).not.toContain('min-h-[95px]')
    expect(src).not.toContain('text-4xl')
    expect(src).not.toContain('text-5xl')
    expect(src).not.toContain('blur-3xl')
    expect(src).not.toContain('bg-[linear-gradient(90deg,hsl(var(--foreground))')
  })

  it('keeps management and knowledge-ops title surfaces flat', () => {
    const src = readWorkspaceFile('components/ui/knowledge-ops-hero.tsx')

    expect(src).toContain('rounded-none border-x-0 border-t-0 border-b')
    expect(src).toContain('min-h-14')
    expect(src).toContain('text-[19px]')
    expect(src).not.toContain('rounded-[28px]')
    expect(src).not.toContain('blur-3xl')
    expect(src).not.toContain('text-transparent')
  })

  it('removes copied 95px hero shells from primary workbench routes', () => {
    const routeFiles = [
      'app/evaluations/page.tsx',
      'app/knowledge/feedback/page-client.tsx',
      'app/knowledge/quarantine/page.tsx',
    ]

    for (const routeFile of routeFiles) {
      expect(readWorkspaceFile(routeFile), routeFile).not.toContain(
        'min-h-[95px]'
      )
    }
  })

  it('removes local rounded hero-card surfaces from dataset detail routes', () => {
    const routeFiles = [
      'app/datasets/[id]/health/page-client.tsx',
      'app/datasets/[id]/profile/page-client.tsx',
      'app/datasets/[id]/tables/page.tsx',
      'app/datasets/[id]/ingestion/page.tsx',
      'app/datasets/[id]/precheck/page-client.tsx',
      'app/datasets/[id]/workflow/page.tsx',
      'app/datasets/[id]/db-catalog/page.tsx',
    ]

    for (const routeFile of routeFiles) {
      const src = readWorkspaceFile(routeFile)
      expect(src, routeFile).not.toMatch(
        /const \w+HeroCard = '[^']*(?:rounded-(?:2xl|\[26px\])|radial-gradient|shadow-\[0_)/
      )
    }
  })

  it('keeps ingestion and graph private title implementations on the same baseline', () => {
    const routeFiles = [
      'components/knowledge/ingestion/ingestion-hero-panel.tsx',
      'app/knowledge/ingestion/page-client.tsx',
      'app/knowledge/ingestion/operation-page-client.tsx',
      'app/graph/_components/graph-page-header.tsx',
    ]

    for (const routeFile of routeFiles) {
      const src = readWorkspaceFile(routeFile)
      expect(src, routeFile).not.toContain('PageTitleIcon name="ingestion-monitor" className="size-9"')
      expect(src, routeFile).not.toContain('PageTitleIcon name="ingestion-operation" className="size-9"')
      expect(src, routeFile).not.toContain('text-transparent')
    }

    expect(
      readWorkspaceFile('app/knowledge/ingestion/page-client.tsx')
    ).not.toMatch(/const INGESTION_HERO_PANEL_CLASS =\s*'[^']*rounded-\[28px\]/)
    expect(
      readWorkspaceFile('app/knowledge/ingestion/operation-page-client.tsx')
    ).not.toMatch(/const OPERATION_HERO_PANEL_CLASS =\s*'[^']*rounded-\[28px\]/)
  })
})
