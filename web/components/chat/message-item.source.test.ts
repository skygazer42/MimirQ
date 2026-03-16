import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('message item source', () => {
  it('uses semantic citation buttons and avoids deprecated clipboard fallbacks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).not.toContain('document.execCommand(')
    expect(src).not.toContain('document.body.removeChild(')
    expect(src).not.toContain('role="button"')
    expect(src).toContain("toast.error('复制失败，请检查浏览器剪贴板权限')")
  })
})
