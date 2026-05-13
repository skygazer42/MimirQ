import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const SOURCE_EXTENSIONS = new Set(['.ts', '.tsx'])
const SKIP_DIRS = new Set(['.next', '.next_build', 'node_modules', 'playwright-report', 'test-results'])
const INDEX_KEY_PATTERN = /key=\{\s*index\s*\}/g

function collectSourceFiles(root: string): string[] {
  const files: string[] = []

  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue
      files.push(...collectSourceFiles(path.join(root, entry.name)))
      continue
    }

    if (entry.isFile() && SOURCE_EXTENSIONS.has(path.extname(entry.name))) {
      files.push(path.join(root, entry.name))
    }
  }

  return files
}

describe('React key source guards', () => {
  it('does not use bare array indexes as React keys', () => {
    const offenders: string[] = []

    for (const sourcePath of collectSourceFiles(__dirname)) {
      const source = fs.readFileSync(sourcePath, 'utf8')
      for (const match of source.matchAll(INDEX_KEY_PATTERN)) {
        const line = source.slice(0, match.index).split('\n').length
        offenders.push(`${path.relative(__dirname, sourcePath)}:${line}`)
      }
    }

    expect(offenders).toEqual([])
  })
})
