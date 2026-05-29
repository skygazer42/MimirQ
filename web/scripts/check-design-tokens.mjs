#!/usr/bin/env node
/**
 * Design token regression guard.
 *
 * Goal: prevent re-introducing hard-coded utility colors that bypass the design token system.
 *
 * This is intentionally conservative: it only blocks the most problematic patterns
 * we are actively migrating away from (e.g., white overlays and raw cyan utilities).
 */

import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Always scan from the web/ project root (not the caller's CWD).
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(SCRIPT_DIR, '..')

const IGNORE_DIRS = new Set([
  'node_modules',
  '.next',
  '.next_build',
  'dist',
  'build',
])

const IGNORE_FILES = new Set([
  path.join('types', 'openapi.ts'),
  'openapi.json',
  path.join('scripts', 'check-design-tokens.mjs'),
])

const IGNORE_FILE_SUFFIXES = [
  '.source.test.ts',
  '.source.test.tsx',
  '.test.ts',
  '.test.tsx',
  '.spec.ts',
  '.spec.tsx',
]

const INCLUDE_EXTENSIONS = new Set(['.ts', '.tsx', '.js', '.jsx', '.mjs', '.css'])

/**
 * Keep this list small and high-signal.
 * If you need to allow an exception, prefer fixing the UI to use tokens instead.
 */
const RULES = [
  {
    id: 'border-white',
    description: 'Avoid hard-coded white borders; use border-border or semantic tokens.',
    re: /\bborder-white(?:\/\d+)?\b/g,
  },
  {
    id: 'bg-white',
    description: 'Avoid hard-coded white backgrounds; use bg-card/bg-background and theme tokens.',
    re: /\bbg-white\b/g,
  },
  {
    id: 'text-white',
    description: 'Avoid hard-coded white text; use *-foreground tokens (e.g., text-primary-foreground).',
    re: /\btext-white\b/g,
  },
  {
    id: 'bg-white-opacity',
    description: 'Avoid bg-white/<alpha> overlays; use bg-card/bg-background with opacity or semantic tokens.',
    re: /\bbg-white\/\d+\b/g,
  },
  {
    id: 'hover-bg-white-opacity',
    description: 'Avoid hover:bg-white/<alpha>; use hover:bg-accent/… or token-based hover styles.',
    re: /\bhover:bg-white\/\d+\b/g,
  },
  {
    id: 'text-cyan-palette',
    description: 'Avoid Tailwind cyan palette utilities; use text-primary/text-info/etc.',
    re: /\btext-cyan-\d{2,3}\b/g,
  },
  {
    id: 'bg-cyan-palette',
    description: 'Avoid Tailwind cyan palette utilities; use bg-primary/bg-info/etc.',
    re: /\bbg-cyan-\d{2,3}(?:\/\d+)?\b/g,
  },
  {
    id: 'border-cyan-palette',
    description: 'Avoid Tailwind cyan palette utilities; use border-primary/border-info/etc.',
    re: /\bborder-cyan-\d{2,3}(?:\/\d+)?\b/g,
  },
  {
    id: 'tailwind-gradients',
    description: 'Avoid Tailwind gradient utilities; use token surfaces and borders instead.',
    re: /\bbg-gradient-[a-z-]+\b/g,
  },
  {
    id: 'tailwind-tracking',
    description: 'Avoid Tailwind letter-spacing utilities; use font weight/size instead.',
    re: /\btracking-(?:tighter|tight|normal|wide|wider|widest)\b/g,
  },
]

async function collectFiles(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true })
  const out = []
  for (const ent of entries) {
    if (ent.name.startsWith('.')) {
      // Skip dotfolders (handled explicitly above where needed).
      if (ent.name !== '.next' && ent.name !== '.next_build') continue
    }

    const abs = path.join(dir, ent.name)
    const rel = path.relative(WEB_ROOT, abs)

    if (ent.isDirectory()) {
      if (IGNORE_DIRS.has(ent.name)) continue
      out.push(...(await collectFiles(abs)))
      continue
    }

    if (!ent.isFile()) continue

    const ext = path.extname(ent.name)
    if (!INCLUDE_EXTENSIONS.has(ext)) continue
    if (IGNORE_FILES.has(rel)) continue
    if (IGNORE_FILE_SUFFIXES.some((suffix) => rel.endsWith(suffix))) continue

    out.push({ abs, rel })
  }
  return out
}

function lineNumberAt(text, index) {
  // 1-based.
  let line = 1
  for (let i = 0; i < index; i++) {
    if (text.charCodeAt(i) === 10) line++
  }
  return line
}

function excerptAt(text, index, length) {
  const start = Math.max(0, index - 20)
  const end = Math.min(text.length, index + length + 20)
  const raw = text.slice(start, end)
  return raw.replace(/\s+/g, ' ').trim()
}

async function main() {
  const files = await collectFiles(WEB_ROOT)
  const violations = []

  for (const { abs, rel } of files) {
    let text
    try {
      text = await fs.readFile(abs, 'utf8')
    } catch {
      continue
    }

    for (const rule of RULES) {
      rule.re.lastIndex = 0
      let m
      while ((m = rule.re.exec(text)) !== null) {
        const match = m[0]
        const line = lineNumberAt(text, m.index)
        violations.push({
          file: rel,
          line,
          rule: rule.id,
          match,
          excerpt: excerptAt(text, m.index, match.length),
        })
      }
    }
  }

  if (!violations.length) {
    process.stdout.write('ui-check: OK (no banned hard-coded classes found)\n')
    return
  }

  process.stderr.write(`ui-check: FAILED (${violations.length} violations)\n\n`)
  for (const v of violations.slice(0, 200)) {
    process.stderr.write(`${v.file}:${v.line}  [${v.rule}]  ${v.match}\n`)
    process.stderr.write(`  ${v.excerpt}\n`)
  }
  if (violations.length > 200) {
    process.stderr.write(`\n...and ${violations.length - 200} more\n`)
  }

  process.stderr.write('\nBanned patterns:\n')
  for (const rule of RULES) {
    process.stderr.write(`- ${rule.id}: ${rule.description}\n`)
  }
  process.stderr.write('\n')

  process.exit(1)
}

main().catch((err) => {
  process.stderr.write(`ui-check: ERROR ${String(err?.message || err)}\n`)
  process.exit(2)
})
