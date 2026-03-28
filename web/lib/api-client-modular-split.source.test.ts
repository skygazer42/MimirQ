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
      ['authApi', 'auth'],
      ['connectorApi', 'connectors'],
      ['datasetApi', 'datasets'],
      ['datasetCategoryApi', 'datasets'],
      ['evaluationApi', 'evaluation'],
      ['kgApi', 'graph'],
      ['observabilityApi', 'observability'],
      ['pipelineApi', 'pipeline'],
      ['reportApi', 'reports'],
      ['settingsApi', 'settings'],
    ] as const

    for (const [exportName, moduleName] of compatExports) {
      expect(apiClientSrc, exportName).toContain(`export { ${exportName} } from '@/lib/api/${moduleName}'`)
      expect(apiClientSrc, exportName).not.toContain(`export const ${exportName} =`)
    }
  })
})
