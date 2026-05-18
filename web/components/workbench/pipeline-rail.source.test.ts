import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('PipelineRail', () => {
  it('wraps IngestionWorkflowStepper with consistent structure', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pipeline-rail.tsx'), 'utf8')

    expect(src).toContain('IngestionWorkflowStepper')
    expect(src).toContain('入库流程')
    expect(src).toContain('data-testid="pipeline-rail"')
    expect(src).toContain('compact = false')
    expect(src).toContain('rounded-full')
    expect(src).toContain('w-full max-w-full overflow-hidden')
    expect(src).toContain("compact ? 'min-w-max' : 'w-full min-w-[640px]'")
  })

  it('uses a full-row dashed connector in the non-compact workflow rail', () => {
    const stepperSrc = fs.readFileSync(
      path.resolve(__dirname, '../ui/ingestion-workflow-stepper.tsx'),
      'utf8'
    )

    expect(stepperSrc).toContain('flex-1 border-t border-dashed')
    expect(stepperSrc).toContain('aria-hidden="true"')
    expect(stepperSrc).not.toContain('mx-2 text-sm')
  })
})
