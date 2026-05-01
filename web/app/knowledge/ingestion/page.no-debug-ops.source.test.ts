import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion debug operations', () => {
  it('does not mount connector or precheck debug operation panels in the product page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain("import { ConnectorOpsPanel } from '@/components/connectors/connector-ops-panel'")
    expect(src).not.toContain("import { PrecheckStreamPanel } from '@/components/ingestion/precheck-stream-panel'")
    expect(src).not.toContain('<ConnectorOpsPanel')
    expect(src).not.toContain('<PrecheckStreamPanel')
    expect(src).not.toContain('高级运维与联调')
    expect(src).not.toContain('opsConsoleOpen')
  })
})
