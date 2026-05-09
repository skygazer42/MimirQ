import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('usage page route compile guards', () => {
  it('uses PageScaffold supported props and defines window presets locally', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('const WINDOW_PRESETS = [')
    expect(src).toContain('bodyClassName=')
    expect(src).toContain('pointer-events-none fixed inset-0 z-0 overflow-hidden')
    expect(src).toContain('items-center justify-center')
    expect(src).toContain("const dataStatus = summary ? '已就绪' : (loading ? '同步中' : '未连接')")
    expect(src).toContain("if (value == null || value === '') return '0'")
    expect(src).toContain("if (sec == null || !Number.isFinite(sec)) return '0ms'")
    expect(src).toContain('label="数据状态"')
    expect(src).not.toContain('className="bg-[#F8FAFC] relative overflow-hidden"')
    expect(src).not.toContain('className="bg-slate-50/50"')
  })
})
