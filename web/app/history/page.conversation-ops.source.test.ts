import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history conversation operations', () => {
  it('mounts explicit conversation export and checkpoint operations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { ConversationOpsPanel } from '@/components/history/conversation-ops-panel'")
    expect(src).toContain('<ConversationOpsPanel')
  })
})
