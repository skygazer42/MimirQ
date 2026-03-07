import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeJiraProjectDialog', () => {
  it('includes jira connector controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-jira-project-dialog.tsx'), 'utf8')

    expect(src).toContain('Jira Project (Connector)')
    expect(src).toContain('Project Key')
    expect(src).toContain("connector_id: 'jira_project'")
    expect(src).toContain('jira_ticket')
    expect(src).toContain('PipelineOptionsPanel')
  })
})
