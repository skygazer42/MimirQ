import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl dataset detail routing source', () => {
  it('uses locale-aware navigation helpers across dataset detail entry points', () => {
    const datasetHealthPage = read('app/datasets/[id]/health/page-client.tsx')
    const datasetProfilePage = read('app/datasets/[id]/profile/page-client.tsx')
    const datasetDbCatalogPage = read('app/datasets/[id]/db-catalog/page.tsx')
    const datasetEvidencePage = read('app/datasets/[id]/evidence/page.tsx')
    const datasetIngestionPage = read('app/datasets/[id]/ingestion/page.tsx')
    const datasetPrecheckPage = read('app/datasets/[id]/precheck/page-client.tsx')
    const datasetTablesPage = read('app/datasets/[id]/tables/page.tsx')
    const datasetWorkflowPage = read('app/datasets/[id]/workflow/page.tsx')
    const datasetKgWorkbenchPage = read('components/datasets/dataset-kg-workbench-page.tsx')

    expect(datasetHealthPage).toContain('@/i18n/navigation')
    expect(datasetHealthPage).not.toContain("import { useParams, useRouter } from 'next/navigation'")

    expect(datasetProfilePage).toContain('@/i18n/navigation')
    expect(datasetProfilePage).not.toContain("import { useParams, useRouter } from 'next/navigation'")

    expect(datasetDbCatalogPage).toContain('@/i18n/navigation')
    expect(datasetDbCatalogPage).not.toContain("import { useParams, useRouter } from 'next/navigation'")

    expect(datasetEvidencePage).toContain('@/i18n/navigation')
    expect(datasetEvidencePage).toContain("import { useParams, useSearchParams } from 'next/navigation'")
    expect(datasetEvidencePage).not.toContain("import { useParams, useRouter, useSearchParams } from 'next/navigation'")

    expect(datasetIngestionPage).toContain('@/i18n/navigation')
    expect(datasetIngestionPage).not.toContain("import { useParams, useRouter } from 'next/navigation'")

    expect(datasetPrecheckPage).toContain('@/i18n/navigation')
    expect(datasetPrecheckPage).not.toContain("import { useParams, useRouter } from 'next/navigation'")

    expect(datasetTablesPage).toContain('@/i18n/navigation')
    expect(datasetTablesPage).not.toContain("import { useParams, useRouter } from 'next/navigation'")

    expect(datasetWorkflowPage).toContain('@/i18n/navigation')
    expect(datasetWorkflowPage).not.toContain("import { useParams, useRouter } from 'next/navigation'")

    expect(datasetKgWorkbenchPage).toContain('@/i18n/navigation')
    expect(datasetKgWorkbenchPage).not.toContain("import { useParams, useRouter } from 'next/navigation'")
  })

  it('adds locale wrappers for dataset detail subpages', () => {
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/db-catalog/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/evidence/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/health/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/ingestion/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/kg/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/precheck/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/tables/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/workflow/page.tsx'))).toBe(true)
  })
})
