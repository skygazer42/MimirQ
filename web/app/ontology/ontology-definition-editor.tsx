'use client'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { OntologyController } from './use-ontology-workspace'
import styles from './ontology.module.css'

export function OntologyDefinitionEditor({ controller: c }: { controller: OntologyController }) {
  return (
    <section className={styles.definitionEditor} aria-label="高级定义编辑器">
      <label className={styles.field}>
        <span className={styles.sectionTitle}>本体行为与高级定义</span>
        <Textarea
          aria-describedby="ontology-definition-help"
          spellCheck={false}
          value={
            c.definitionText ??
            JSON.stringify(
              {
                relation_bindings: {},
                metrics: {},
                rules: {},
                functions: {},
                actions: {},
                action_workflows: {},
                document_metadata: {},
                document_templates: {},
                ...c.definition,
              },
              null,
              2,
            )
          }
          disabled={Boolean(c.busy)}
          onChange={(event) => {
            c.setDefinitionText(event.target.value)
            c.setIssue('')
          }}
        />
      </label>
      <p id="ontology-definition-help" className={styles.help}>
        编辑完整 JSON 或 YAML：关系键、指标、规则、函数、动作、动作流程、知识概念、文档元数据与文书模板。{' '}
        概念来源用于定位适用原文，不代替计算或动作。指标的 <code>dimensions</code>{' '}
        声明可分组的单值属性。校验并应用后，再保存草稿。
      </p>
      <div className={styles.actions}>
        <Button
          variant="outline"
          disabled={Boolean(c.busy) || !c.definitionText?.trim()}
          onClick={() => {
            if (c.definitionText) void c.run('校验高级定义', () => c.applyDefinition(c.definitionText!))
          }}
        >
          校验并应用定义
        </Button>
        <Button
          variant="ghost"
          disabled={Boolean(c.busy) || !c.unappliedDefinition}
          onClick={() => {
            c.setDefinitionText(null)
            c.setIssue('')
          }}
        >
          还原编辑区内容
        </Button>
      </div>
    </section>
  )
}
