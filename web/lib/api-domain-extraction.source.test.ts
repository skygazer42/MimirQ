import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('api domain extraction source', () => {
  it('keeps chat and rag implementations in dedicated domain files', () => {
    const apiClientSrc = fs.readFileSync(path.resolve(__dirname, 'api-client.ts'), 'utf8')
    const apiIndexSrc = fs.readFileSync(path.resolve(__dirname, 'api/index.ts'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'api/chat.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'api/rag.ts'))).toBe(true)
    expect(apiClientSrc).toContain("export { chatApi } from '@/lib/api/chat'")
    expect(apiClientSrc).toContain("export { ragApi } from '@/lib/api/rag'")
    expect(apiClientSrc).not.toContain('export const chatApi =')
    expect(apiClientSrc).not.toContain('export const ragApi =')
    expect(apiIndexSrc).toContain("export { chatApi } from './chat'")
    expect(apiIndexSrc).toContain("export { ragApi } from './rag'")
  })

  it('keeps the main remaining domains on real api modules without api-client re-export cycles', () => {
    const apiIndexSrc = fs.readFileSync(path.resolve(__dirname, 'api/index.ts'), 'utf8')
    const domains = [
      ['auth.ts', 'authApi'],
      ['connectors.ts', 'connectorApi'],
      ['datasets.ts', 'datasetApi'],
      ['evaluation.ts', 'evaluationApi'],
      ['graph.ts', 'kgApi'],
      ['observability.ts', 'observabilityApi'],
      ['pipeline.ts', 'pipelineApi'],
      ['reports.ts', 'reportApi'],
      ['settings.ts', 'settingsApi'],
    ] as const

    expect(apiIndexSrc).not.toContain("export * from '@/lib/api-client'")

    for (const [fileName, exportName] of domains) {
      const src = fs.readFileSync(path.resolve(__dirname, 'api', fileName), 'utf8')

      expect(src, fileName).not.toContain("from '@/lib/api-client'")
      expect(src, fileName).toContain(`export const ${exportName} =`)
      expect(apiIndexSrc, exportName).toContain(`export { ${exportName} } from './${fileName.replace(/\.ts$/, '')}'`)
    }
  })
})
