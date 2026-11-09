// @vitest-environment happy-dom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import type { NodeChange, EdgeChange } from '@xyflow/react'

const flow = vi.hoisted(() => ({ props: {} as { nodes: Array<{ measured?: { width?: number } }>; onNodesChange: (changes: NodeChange[]) => void; onEdgesChange: (changes: EdgeChange[]) => void } }))
vi.mock('@xyflow/react', async importOriginal => ({
  ...await importOriginal<typeof import('@xyflow/react')>(),
  ReactFlow: (props: typeof flow.props) => { flow.props = props; return null },
  Background: () => null,
  Controls: () => null,
}))
import { WorkflowEditor } from './workflow-editor'

it('keeps measurement, selection and an unchanged position out of the saved layout', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const container = document.createElement('div'), root = createRoot(container), publish = vi.fn()
  try {
    await act(async () => root.render(<WorkflowEditor graph={{ nodes: [{ id: 'bundle', label: '配置' }], links: [] }} onWorkflowLayoutChange={publish} />))
    await act(async () => {
      flow.props.onNodesChange([{ type: 'dimensions', id: 'bundle', dimensions: { width: 208, height: 56 } }])
      flow.props.onNodesChange([{ type: 'select', id: 'bundle', selected: true }])
      flow.props.onNodesChange([{ type: 'position', id: 'bundle', position: { x: 48, y: 48 } }])
      flow.props.onEdgesChange([{ type: 'select', id: 'edge', selected: true }])
    })
    expect(publish).not.toHaveBeenCalled()
    expect(flow.props.nodes[0].measured?.width).toBe(208)
    await act(async () => flow.props.onNodesChange([{ type: 'position', id: 'bundle', position: { x: 120, y: 80 } }]))
    expect(publish).toHaveBeenCalledOnce()
    expect(publish.mock.calls[0][0].nodes[0].position).toEqual({ x: 120, y: 80 })
  } finally { await act(async () => root.unmount()) }
})
