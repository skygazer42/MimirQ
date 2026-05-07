import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('EvaluationDataOpsPanel source', () => {
  it('surfaces regression import/export, synthetic hardcases and purge APIs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evaluation-data-ops-panel.tsx'), 'utf8')

    expect(src).toContain('evaluationApi.exportRegressionCases')
    expect(src).toContain('evaluationApi.importRegressionCases')
    expect(src).toContain('evaluationApi.generateSyntheticHardcases')
    expect(src).toContain('evaluationApi.purgeRegressionRuns')
  })

  it('matches the advanced data operations layout contract', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evaluation-data-ops-panel.tsx'), 'utf8')

    expect(src).toContain('评测数据运维')
    expect(src).toContain('高级参数（可选）')
    expect(src).toContain('导入数据（JSON）')
    expect(src).toContain('请输入或粘贴 JSON 数据...')
    expect(src).toContain('评测数据操作结果')
    expect(src).toContain('开始执行')
    expect(src).toContain('展开原始响应')
    expect(src).toContain('接口已返回真实数据')
    expect(src).not.toContain('OperationResultPanel')
  })
})
