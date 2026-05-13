import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('tsconfig source', () => {
  it('targets a modern ECMAScript baseline for the Next 16 runtime', () => {
    const tsconfig = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, 'tsconfig.json'), 'utf8'),
    ) as { compilerOptions?: { target?: string } }

    expect(tsconfig.compilerOptions?.target).toBe('ES2022')
    expect(tsconfig.compilerOptions?.target).not.toBe('ES2017')
  })
})
