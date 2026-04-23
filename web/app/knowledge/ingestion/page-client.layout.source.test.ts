import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion precheck page layout', () => {
  it('focuses on objective precheck outputs instead of execution cockpit controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('title="项目数据审计"')
    expect(src).toContain('格式分布与文件大小分布')
    expect(src).toContain('标签分流清单')
    expect(src).toContain('待确认清单')
    expect(src).toContain('代表样本')
    expect(src).toContain('输出客观事实，不做主观评分')
    expect(src).toContain('routeBucketFilter')
    expect(src).toContain('buildSizeBuckets')
    expect(src).not.toContain('phaseMode')
    expect(src).not.toContain('canvasMode')
    expect(src).not.toContain('处理效率与剩余预测')
    expect(src).not.toContain('当前引擎负载')
    expect(src).not.toContain('WorkerPool_Alpha_4')
  })
})
