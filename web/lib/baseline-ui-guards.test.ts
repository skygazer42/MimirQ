import fs from 'node:fs/promises'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

type Violation = {
  file: string
  line: number
  match: string
}

const WEB_ROOT = path.resolve(__dirname, '..')

const IGNORE_DIRS = new Set([
  'node_modules',
  '.next',
  '.next_3101',
  '.next_build',
  'dist',
  'build',
  'coverage',
])

const IGNORE_FILES = new Set([
  path.join('types', 'openapi.ts'),
  'openapi.json',
  path.join('lib', 'baseline-ui-guards.test.ts'),
])

const INCLUDE_EXTENSIONS = new Set(['.ts', '.tsx', '.js', '.jsx', '.mjs', '.css'])

async function collectFiles(dirAbs: string): Promise<string[]> {
  const entries = await fs.readdir(dirAbs, { withFileTypes: true })
  const out: string[] = []
  for (const ent of entries) {
    const abs = path.join(dirAbs, ent.name)
    const rel = path.relative(WEB_ROOT, abs)

    if (ent.isDirectory()) {
      if (ent.name.startsWith('.next_')) continue
      if (IGNORE_DIRS.has(ent.name)) continue
      out.push(...(await collectFiles(abs)))
      continue
    }

    if (!ent.isFile()) continue
    if (IGNORE_FILES.has(rel)) continue

    const ext = path.extname(ent.name)
    if (!INCLUDE_EXTENSIONS.has(ext)) continue

    out.push(rel)
  }
  return out
}

function lineNumberAt(text: string, index: number): number {
  // 1-based.
  let line = 1
  for (let i = 0; i < index; i++) {
    if (text.charCodeAt(i) === 10) line++
  }
  return line
}

async function findViolations(rule: { id: string; re: RegExp }): Promise<Violation[]> {
  const files = await collectFiles(WEB_ROOT)
  const violations: Violation[] = []

  for (const rel of files) {
    const abs = path.join(WEB_ROOT, rel)
    let text: string
    try {
      text = await fs.readFile(abs, 'utf8')
    } catch {
      continue
    }

    rule.re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = rule.re.exec(text)) !== null) {
      violations.push({
        file: rel,
        line: lineNumberAt(text, m.index),
        match: m[0],
      })
    }
  }

  return violations
}

const GUARD_TIMEOUT_MS = 15000

describe('baseline ui guards', () => {
  it('does not use heavy Tailwind shadow classes (prefer shadow-soft/shadow-strong tokens)', async () => {
    const violations = await findViolations({
      id: 'heavy-shadows',
      re: /\bshadow-(?:xl|2xl|3xl)\b/g,
    })

    expect(
      violations,
      violations
        .slice(0, 25)
        .map((v) => `${v.file}:${v.line} ${v.match}`)
        .join('\n')
    ).toHaveLength(0)
  }, GUARD_TIMEOUT_MS)

  it('does not suppress focus rings (a11y): avoid focus-visible:ring-0 / focus:ring-0', async () => {
    const violations = await findViolations({
      id: 'focus-ring-suppression',
      re: /\bfocus(?:-visible)?:ring-0\b/g,
    })

    expect(
      violations,
      violations
        .slice(0, 25)
        .map((v) => `${v.file}:${v.line} ${v.match}`)
        .join('\n')
    ).toHaveLength(0)
  }, GUARD_TIMEOUT_MS)
})
