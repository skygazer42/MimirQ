import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('api-client modular split source', () => {
  it('keeps api-client as a thin compatibility barrel over domain modules', () => {
    const apiClientSrc = read('api-client.ts')

    const compatExports = [
      ['auditApi', 'audit'],
      ['authApi', 'auth'],
      ['connectorApi', 'connectors'],
      ['chunkPresetApi', 'governance'],
      ['datasetApi', 'datasets'],
      ['datasetCategoryApi', 'datasets'],
      ['evidenceApi', 'evidence'],
      ['evaluationApi', 'evaluation'],
      ['feedbackApi', 'feedback'],
      ['groupApi', 'access'],
      ['healthApi', 'health'],
      ['ingestionRunApi', 'connectors'],
      ['kgApi', 'graph'],
      ['ltrApi', 'ltr'],
      ['metaApi', 'meta'],
      ['observabilityApi', 'observability'],
      ['parsingApi', 'parsing'],
      ['pipelineApi', 'pipeline'],
      ['promptTemplateApi', 'prompts'],
      ['ragConfigTemplateApi', 'rag'],
      ['reportApi', 'reports'],
      ['ragvizApi', 'rag'],
      ['rbacApi', 'access'],
      ['retrievalApi', 'rag'],
      ['scimApi', 'scim'],
      ['settingsApi', 'settings'],
      ['sseApi', 'streaming'],
      ['usageApi', 'usage'],
      ['governanceApi', 'governance'],
    ] as const

    for (const [exportName, moduleName] of compatExports) {
      expect(apiClientSrc, exportName).toContain(`export { ${exportName} } from '@/lib/api/${moduleName}'`)
      expect(apiClientSrc, exportName).not.toContain(`export const ${exportName} =`)
    }
  })
})
