import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('workflow editor source', () => {
  it('uses React Flow editor primitives for editable workflow layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workflow-editor.tsx'), 'utf8')
    expect(src).toContain('@xyflow/react')
    expect(src).toContain('ReactFlow')
    expect(src).toContain('onNodesChange')
    expect(src).toContain('onEdgesChange')
  })

  it('wires the dataset workflow page to WorkflowEditor', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, '../../app/datasets/[id]/workflow/page.tsx'), 'utf8')
    expect(pageSrc).toContain('WorkflowEditor')
  })
})
