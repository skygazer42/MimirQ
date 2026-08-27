import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('task center visual source', () => {
  it('uses the shared flat ruled boundary system', () => {
    const source = fs.readFileSync(path.resolve(__dirname, 'task-center.tsx'), 'utf8')

    expect(source).toContain('data-task-center-panel="true"')
    expect(source).toContain('data-task-center-boundary="ruled"')
    expect(source).toContain('border border-foreground/15 bg-background')
    expect(source).toContain('border-b border-foreground/10 bg-background')
    expect(source).not.toContain('backdrop-blur')
    expect(source).not.toContain('shadow-strong')
    expect(source).not.toContain('animate-ping')
  })
})
