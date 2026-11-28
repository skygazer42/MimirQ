import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('prompt workspace ownership', () => {
  it('keeps enterprise ontology state and imports out of prompt management', () => {
    for (const name of ['page.tsx', 'prompt-dialogs.tsx', 'prompt-table.tsx', 'use-prompt-templates.ts']) {
      const source = fs.readFileSync(path.resolve(__dirname, name), 'utf8')
      expect(source, name).not.toMatch(/enterprise-ontology|EnterpriseOntologySettings|openOntology|data-prompt-ontology/)
    }
    const dialogs = fs.readFileSync(path.resolve(__dirname, 'prompt-dialogs.tsx'), 'utf8')
    expect(dialogs).toContain('<TabsTrigger value="templates">场景模板</TabsTrigger>')
    expect(dialogs).toContain('<TabsTrigger value="predicates">关系词表</TabsTrigger>')
  })
})
