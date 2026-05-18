import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('settings LTR and runtime section styling', () => {
  it('keeps LTR registry compact and avoids repeated framed titles', () => {
    const src = read('./_sections/ltr-model-registry-section.tsx')

    expect(src).toContain('注册入口')
    expect(src).toContain('模型版本')
    expect(src).toContain('选择模型 JSON')
    expect(src).toContain('选择清单 JSON')
    expect(src).toContain("xl:grid-cols-[minmax(280px,0.85fr)_minmax(0,1.15fr)]")
    expect(src).not.toContain('LTR 模型注册表')
    expect(src).not.toContain('No file chosen')
    expect(src).not.toContain('已激活（ACTIVE）')
    expect(src).not.toContain('空闲（idle）')
  })

  it('uses compact runtime control cards instead of large stacked copy blocks', () => {
    const src = read('./_sections/runtime-controls-section.tsx')

    expect(src).toContain('function RuntimeCard')
    expect(src).toContain('function OptionRow')
    expect(src).toContain('className="grid gap-3 xl:grid-cols-2"')
    expect(src).toContain('h-7 w-7')
    expect(src).toContain('对话流式稳定性')
    expect(src).toContain('性能与缓存')
    expect(src).not.toContain('space-y-8 rounded-2xl border border-border bg-card p-6')
    expect(src).not.toContain('去重/缓存属于“尽力而为（best-effort）”')
    expect(src).not.toContain('心跳间隔（heartbeat，秒）')
    expect(src).not.toContain('最大值字节数（max_value_bytes）')
  })
})
