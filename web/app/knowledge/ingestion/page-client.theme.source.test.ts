import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('knowledge ingestion execution monitor theme tokens', () => {
  it('uses theme variables for the execution monitor page background', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expectSourceToContain(src, 'hsl(var(--primary)/0.08)')
    expectSourceToContain(src, 'linear-gradient(180deg,hsl(var(--background))')
    expectSourceNotToContain(src, 'rgba(248,250,252,0.98)')
    expectSourceNotToContain(src, 'rgba(241,245,249,0.92)')
  })
})
