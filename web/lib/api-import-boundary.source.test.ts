import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const ROOTS = ['../app', '../components', '../contexts', '../hooks', '../services', '../store', '../workers'] as const

function walk(dir: string, out: string[] = []): string[] {
  if (!fs.existsSync(dir)) return out
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const next = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      walk(next, out)
      continue
    }
    if (!/\.(ts|tsx)$/.test(entry.name)) continue
    if (/\.test\.(ts|tsx)$/.test(entry.name)) continue
    out.push(next)
  }
  return out
}

describe('api import boundary', () => {
  it('keeps production code off the legacy api-client entrypoint', () => {
    const files = ROOTS.flatMap((relativeRoot) => walk(path.resolve(__dirname, relativeRoot)))

    const offenders = files.filter((file) => {
      const src = fs.readFileSync(file, 'utf8')
      return src.includes("@/lib/api-client")
    })

    expect(offenders).toEqual([])
  })
})
