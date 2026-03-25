import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8')
}

describe('type safety hotspots', () => {
  it('keeps chat formatting and chat area metadata filters on unknown-safe objects', () => {
    const formatter = read('hooks/use-chat-formatter.ts')
    const chatArea = read('components/chat-area.tsx')

    expect(formatter).not.toContain('metadata_filter?: Record<string, any> | null')
    expect(chatArea).not.toContain('metadata_filter?: Record<string, any> | null')
    expect(chatArea).not.toContain('icon: any')
  })

  it('keeps auth proxy routes free of any-based JSON helpers and error catches', () => {
    const exchangeRoute = read('app/api/oidc/exchange/route.ts')
    const logoutRoute = read('app/api/oidc/logout/route.ts')
    const refreshRoute = read('app/api/oidc/refresh/route.ts')
    const samlRoute = read('app/api/saml/acs/route.ts')

    expect(exchangeRoute).not.toContain('function jsonNoStore(data: any')
    expect(exchangeRoute).not.toContain('catch (e: any)')
    expect(logoutRoute).not.toContain('function jsonNoStore(data: any')
    expect(refreshRoute).not.toContain('function jsonNoStore(data: any')
    expect(refreshRoute).not.toContain('catch (e: any)')
    expect(samlRoute).not.toContain('function jsonNoStore(data: any')
  })

  it('keeps core chat types on unknown-safe payloads', () => {
    const types = read('types/index.ts')

    expect(types).not.toContain('data: any')
    expect(types).not.toContain('structured_data?: any')
    expect(types).not.toContain('next?: any')
    expect(types).not.toContain('metadata_filter?: Record<string, any>')
    expect(types).not.toContain('metrics: Record<string, any>')
  })

  it('keeps ragviz similarity result payloads on unknown-safe objects', () => {
    const types = read('types/index.ts')
    const start = types.indexOf('export interface RagvizSimilarityMatrixResult {')
    const end = types.indexOf('export interface RagvizSimilarityCalculateResponse {')
    const ragvizBlock = start >= 0 && end > start ? types.slice(start, end) : types

    expect(ragvizBlock).not.toContain('x_data: Record<string, any>[]')
    expect(ragvizBlock).not.toContain('y_data: Record<string, any>[]')
    expect(ragvizBlock).not.toContain('metadata: Record<string, any>')
  })

  it('keeps chunk preview payload types on unknown-safe objects', () => {
    const types = read('types/index.ts')
    const start = types.indexOf('export interface ParsedSegment {')
    const end = types.indexOf('export interface ChunkPreviewResponse {')
    const chunkPreviewBlock = start >= 0 && end > start ? types.slice(start, end) : types

    expect(chunkPreviewBlock).not.toContain('metadata?: Record<string, any>')
    expect(chunkPreviewBlock).not.toContain('payload: Record<string, any>')
    expect(chunkPreviewBlock).not.toContain('strategy_params?: Record<string, any>')
    expect(chunkPreviewBlock).not.toContain('meta?: Record<string, any>')
    expect(chunkPreviewBlock).not.toContain('patch?: Record<string, any>')
  })

  it('keeps connector and ingestion run payloads on unknown-safe objects', () => {
    const types = read('types/index.ts')
    const start = types.indexOf('export interface ConnectorRunOut {')
    const end = types.indexOf('export interface ConnectorConfigCreateRequest {')
    const connectorRunBlock = start >= 0 && end > start ? types.slice(start, end) : types

    expect(connectorRunBlock).not.toContain('config?: Record<string, any>')
    expect(connectorRunBlock).not.toContain('stats?: Record<string, any>')
    expect(connectorRunBlock).not.toContain('diff: Record<string, any>')
  })

  it('keeps regression payload types on unknown-safe objects', () => {
    const types = read('types/index.ts')
    const start = types.indexOf('export interface RegressionRun {')
    const end = types.indexOf('// ==================== RAGViz（相似度热力图） ====================')
    const regressionBlock = start >= 0 && end > start ? types.slice(start, end) : types

    expect(regressionBlock).not.toContain('params: Record<string, any>')
    expect(regressionBlock).not.toContain('summary: Record<string, any>')
    expect(regressionBlock).not.toContain('citations: any[]')
    expect(regressionBlock).not.toContain('scores: Record<string, any>')
    expect(regressionBlock).not.toContain('meta?: Record<string, any>')
    expect(regressionBlock).not.toContain('before?: any')
    expect(regressionBlock).not.toContain('after?: any')
    expect(regressionBlock).not.toContain('base_params: Record<string, any>')
    expect(regressionBlock).not.toContain('target_params: Record<string, any>')
  })

  it('keeps ragviz evidence workbench free of any-casts', () => {
    const src = read('components/ragviz/evidence-workbench.tsx')

    expect(src).not.toContain('data: any')
    expect(src).not.toContain('as any')
    expect(src).not.toContain(': any')
    expect(src).not.toContain('Record<string, any>')
  })
})
