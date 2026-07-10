import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieval ablations page source', () => {
  it('avoids any-based diff score helpers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieval-ablations-page.tsx'), 'utf8')

    expect(src).not.toContain(': any')
    expect(src).not.toContain('as any')
    expect(src).not.toContain('Record<string, any>')
  })

  it('uses clearer evaluation-language entry points for the ablations lab', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieval-ablations-page.tsx'), 'utf8')

    expect(src).toContain('title="检索调参对比"')
    expect(src).toContain('检索消融实验')
    expect(src).toContain('返回评测中心')
    expect(src).toContain('href="/evaluations"')
    expect(src).toContain('hover:text-slate-900')
  })

  it('explains empty diff state in terms of cases and run count instead of a generic blank state', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieval-ablations-page.tsx'), 'utf8')

    expect(src).toContain('已有 Golden 样本，但还没有实验运行')
    expect(src).toContain('已有 Golden 样本，但还差 1 条实验运行')
    expect(src).toContain('Golden 样本 {caseCount}')
    expect(src).toContain('实验运行 {runCount}')
    expect(src).toContain('点击左下角“运行消融实验”')
  })

  it('offers an auto-bootstrap path before enough comparison runs exist', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieval-ablations-page.tsx'), 'utf8')

    expect(src).toContain('function pickAutoCandidateTopK')
    expect(src).toContain('async function runAutoBootstrap()')
    expect(src).toContain('自动生成第 1 轮对比')
    expect(src).toContain('自动补齐第 1 轮对比')
    expect(src).toContain('系统会先比较 top_k：')
    expect(src).toContain("ablation_label_prefix: 'auto-bootstrap-top-k'")
    expect(src).toContain('自动生成第 2 轮对比')
    expect(src).toContain('reranker ON/OFF 对比')
    expect(src).toContain('自动生成第 3 轮对比')
    expect(src).toContain('hybrid vs vector 对比')
  })
})
