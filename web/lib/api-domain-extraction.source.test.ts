import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('api domain extraction source', () => {
  it('keeps chat and rag implementations in dedicated domain files', () => {
    const apiClientSrc = fs.readFileSync(path.resolve(__dirname, 'api-client.ts'), 'utf8')
    const apiIndexSrc = fs.readFileSync(path.resolve(__dirname, 'api/index.ts'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'api/chat.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'api/rag.ts'))).toBe(true)
    expect(apiClientSrc).toContain("export { chatApi } from '@/lib/api/chat'")
    expect(apiClientSrc).toContain("export { ragApi } from '@/lib/api/rag'")
    expect(apiClientSrc).not.toContain('export const chatApi =')
    expect(apiClientSrc).not.toContain('export const ragApi =')
    expect(apiIndexSrc).toContain("export { chatApi } from './chat'")
    expect(apiIndexSrc).toContain("export { ragApi } from './rag'")
  })
})
