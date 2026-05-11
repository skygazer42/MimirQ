import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const messagesRoot = path.resolve(__dirname, 'zh-CN.ts')
const moduleDir = path.resolve(__dirname, 'zh-CN')

describe('zh-CN message catalog split', () => {
  it('keeps the root locale file as a small module aggregator', () => {
    const src = fs.readFileSync(messagesRoot, 'utf8')

    expect(src.split('\n').length).toBeLessThanOrEqual(80)
    expect(src).toContain("import commonMessages from './zh-CN/common'")
    expect(src).toContain('const zhCNMessages = {')
    expect(src).toContain('...commonMessages')
    expect(src).toContain('export default zhCNMessages')
    expect(src).not.toContain('ChunkPreview: {')
  })

  it('stores domain message namespaces in split module files', () => {
    const modules = fs.readdirSync(moduleDir).filter((name) => name.endsWith('.ts'))

    expect(modules.length).toBeGreaterThanOrEqual(10)
    expect(modules).toContain('chunk-preview.ts')
    expect(modules).toContain('knowledge.ts')
    expect(modules).toContain('governance.ts')
  })
})
