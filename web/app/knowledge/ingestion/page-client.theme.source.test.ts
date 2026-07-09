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

    expectSourceToContain(src, 'bg-white bg-[radial-gradient(circle_at_top,hsl(var(--info)/0.10),transparent_34rem)] dark:bg-background')
    expectSourceToContain(src, 'rgba(248,253,255,0.92)')
    expectSourceToContain(src, 'rgba(229,245,255,0.72)')
    expectSourceToContain(src, 'rgba(255,255,255,0.82)')
    expectSourceNotToContain(src, 'hsl(var(--primary)/0.08),transparent_42%')
    expectSourceNotToContain(src, 'rounded-[1.35rem] border border-border/60 bg-[linear-gradient(135deg,hsl(var(--background)/0.92),hsl(var(--muted)/0.36))]')
  })
})
