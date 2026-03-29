import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('types index source', () => {
  it('re-exports extracted connector and observability domains instead of inlining them', () => {
    const indexSrc = fs.readFileSync(path.resolve(__dirname, 'index.ts'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'connectors.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'observability.ts'))).toBe(true)
    expect(indexSrc).toContain("export * from './connectors'")
    expect(indexSrc).toContain("export * from './observability'")
    expect(indexSrc).not.toContain('export interface ConnectorInfo')
    expect(indexSrc).not.toContain('export interface RagMetricsSummaryResponse')
  })

  it('re-exports additional domain modules instead of keeping major interfaces inline', () => {
    const indexSrc = fs.readFileSync(path.resolve(__dirname, 'index.ts'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'processing.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'datasets.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'chat.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'knowledge-graph.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'evaluation.ts'))).toBe(true)

    expect(indexSrc).toContain("export * from './processing'")
    expect(indexSrc).toContain("export * from './datasets'")
    expect(indexSrc).toContain("export * from './chat'")
    expect(indexSrc).toContain("export * from './knowledge-graph'")
    expect(indexSrc).toContain("export * from './evaluation'")

    expect(indexSrc).not.toContain('export interface ChunkPreviewResponse')
    expect(indexSrc).not.toContain('export interface DatasetProfileSummary')
    expect(indexSrc).not.toContain('export interface RagTrace')
    expect(indexSrc).not.toContain('export interface KGGraphNode')
    expect(indexSrc).not.toContain('export interface RegressionRunDetail')
  })
})
