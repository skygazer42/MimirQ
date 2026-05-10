import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const ROOTS = ['app', 'components']
const TSX_RE = /\.(ts|tsx)$/

function collectSourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.next') continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      collectSourceFiles(full, acc)
      continue
    }
    if (!TSX_RE.test(entry.name)) continue
    if (entry.name.endsWith('.test.ts') || entry.name.endsWith('.test.tsx') || entry.name.endsWith('.source.test.ts')) continue
    acc.push(full)
  }
  return acc
}

describe('SafeResponsiveChart usage', () => {
  it('avoids Recharts ResponsiveContainer in route/component source', () => {
    const webRoot = path.resolve(__dirname, '../..')
    const offenders = ROOTS.flatMap((root) => collectSourceFiles(path.join(webRoot, root)))
      .filter((file) => fs.readFileSync(file, 'utf8').includes('ResponsiveContainer'))
      .map((file) => path.relative(webRoot, file))

    expect(offenders).toEqual([])
  })
})
