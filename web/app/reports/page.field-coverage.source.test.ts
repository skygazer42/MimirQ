import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports field coverage panel', () => {
  it('falls back to backend profile coverage when governance audit has no samples', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('const hasGovernanceCoverage =')
    expect(src).toContain('const baseCoverageRows =')
    expect(src).toContain('状态字段覆盖')
    expect(src).toContain('文件类型覆盖')
    expect(src).toContain('目录字段覆盖')
    expect(src).toContain('解析来源覆盖')
    expect(src).toContain('分块统计覆盖')
    expect(src).toContain("hasGovernanceCoverage ? '治理审计' : '基础画像'")
    expect(src).not.toContain('后端治理审计</Badge>')
  })
})
