import { describe, expect, it } from 'vitest'

import { buildSimilarityDiagnostics } from './similarity-diagnostics'

const SAMPLE_INPUT = {
  matrix: [
    [0.94, 0.18, 0.12],
    [0.21, 0.91, 0.28],
    [0.15, 0.33, 0.89],
  ],
  xItems: [
    { id: 'x-1', text: 'payment terms for invoice disputes', document: 'payments-playbook' },
    { id: 'x-2', text: 'refund policy for annual subscription cancellations', document: 'billing-faq' },
    { id: 'x-3', text: 'security SLA and incident response commitments', document: 'security-handbook' },
  ],
  yItems: [
    { id: 'y-1', text: 'invoice disputes and payment terms escalation path', document: 'finance-guide' },
    { id: 'y-2', text: 'gpu kernel launch occupancy profiling and cuda registers', document: 'cuda-notes' },
    { id: 'y-3', text: 'incident response commitments and security SLA process', document: 'security-runbook' },
  ],
  xLabels: ['Payment Terms', 'Refund Policy', 'Security SLA'],
  yLabels: ['Payment Terms Guide', 'GPU Kernel Profiling', 'Security SLA Runbook'],
}

describe('buildSimilarityDiagnostics', () => {
  it('flags lexically unsupported high-similarity pairs as outliers', () => {
    const diagnostics = buildSimilarityDiagnostics(SAMPLE_INPUT)

    expect(diagnostics.nodes).toHaveLength(6)
    expect(diagnostics.summary.activeOutlierCount).toBe(1)
    expect(diagnostics.outliers).toHaveLength(1)
    expect(diagnostics.outliers[0]).toMatchObject({
      id: 'x-2::y-2',
      xLabel: 'Refund Policy',
      yLabel: 'GPU Kernel Profiling',
      decision: null,
    })
    expect(diagnostics.outliers[0].reason).toContain('词面重叠')
    expect(diagnostics.links.find((link) => link.id === diagnostics.outliers[0].id)?.isOutlier).toBe(true)
    expect(
      diagnostics.nodes
        .filter((node) => node.isOutlier)
        .map((node) => node.id)
        .sort((a, b) => a.localeCompare(b))
    ).toEqual(['x:x-2', 'y:y-2'])
  })

  it('applies local mark and disable decisions without requiring new backend payloads', () => {
    const base = buildSimilarityDiagnostics(SAMPLE_INPUT)
    const target = base.outliers[0]

    const marked = buildSimilarityDiagnostics({
      ...SAMPLE_INPUT,
      decisions: { [target.id]: 'marked' },
    })

    expect(marked.summary.markedCount).toBe(1)
    expect(marked.outliers[0]?.decision).toBe('marked')

    const disabled = buildSimilarityDiagnostics({
      ...SAMPLE_INPUT,
      decisions: { [target.id]: 'disabled' },
    })

    expect(disabled.summary.disabledCount).toBe(1)
    expect(disabled.summary.activeOutlierCount).toBe(0)
    expect(disabled.outliers[0]?.decision).toBe('disabled')
    expect(disabled.links.some((link) => link.id === target.id)).toBe(false)
  })
})
