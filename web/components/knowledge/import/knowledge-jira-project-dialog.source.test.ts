import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeJiraProjectDialog', () => {
  it('includes jira connector controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-jira-project-dialog.tsx'), 'utf8')

    expect(src).toContain('Jira Project (Connector)')
    expect(src).toContain('Project Key')
    expect(src).toContain('buildJiraProjectRunPayload')
    expect(src).toContain('connectorApi.createRun')
    expect(src).toContain('jira_ticket')
    expect(src).toContain('PipelineOptionsPanel')
    expect(src).toContain('Source ACL（高级）')
    expect(src).toContain('继承 Jira 可见性')
    expect(src).toContain('未映射 Jira ACL 时')
    expect(src).toContain('tenant_groups.external_id')
    expect(src).toContain('sourceAclEnabled')
    expect(src).toContain('sourceAclFallbackMode')
  })
})
