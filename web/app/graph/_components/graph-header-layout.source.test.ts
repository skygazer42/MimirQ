import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(file: string): string {
  return fs.readFileSync(path.resolve(__dirname, file), 'utf8')
}

describe('graph page header layout', () => {
  it('keeps dense graph controls from overlapping the title and search row', () => {
    const header = read('graph-page-header.tsx')
    const canvas = read('graph-canvas.tsx')

    expect(header).toContain('flex h-16 items-center gap-3')
    expect(header).toContain('pointer-events-auto flex min-w-[300px] flex-1 justify-center')
    expect(header).toContain('PopoverContent align="end" className="w-[390px] p-3"')
    expect(header).toContain('图谱工具')
    expect(header).toContain('KG JSON/JSONL 是唯一外部图谱导入方式')
    expect(header).toContain('导入 KG JSON / JSONL')
    expect(header).toContain("href=\"/graph/diagnostics\"")
    expect(header).toContain("href=\"/graph/snapshots\"")
    expect(header).toContain('Diagnostics')
    expect(header).toContain('Snapshots')
    expect(header).toContain('shrink-0')
    expect(header).not.toContain('title="共现阈值（点击循环）"')
    expect(header).not.toContain('flex min-h-16 flex-col gap-2')
    expect(header).not.toContain('flex h-16 items-center justify-between')
    expect(canvas).toContain('top-16')
  })
})
