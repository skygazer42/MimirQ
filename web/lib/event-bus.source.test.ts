import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('global event bus source', () => {
  it('does not expose hidden demo-mode events outside demo pages', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'event-bus.ts'), 'utf8')

    expect(src).not.toContain('ingestion:toggle-demo-mode')
  })

  it('distinguishes chat prefill from backend-submitting chat actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'event-bus.ts'), 'utf8')

    expect(src).toContain("'chat:send': string")
    expect(src).toContain("'chat:submit': string")
  })

  it('reports whether an emitted event had an active listener', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'event-bus.ts'), 'utf8')

    expect(src).toContain('emit<K extends keyof EventMap>(event: K, payload: EventMap[K]): number')
    expect(src).toContain('return listeners.size')
  })
})
