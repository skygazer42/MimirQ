#!/usr/bin/env node
/**
 * Baseline UI guard: ban native browser dialogs in app code.
 *
 * Why:
 * - `confirm()` / `prompt()` are blocking, inconsistent, and hard to style/accessibilize.
 * - Use Radix/shadcn primitives instead: AlertDialog/Dialog.
 */

import fs from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"

// Always scan from the web/ project root (not the caller's CWD).
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(SCRIPT_DIR, "..")

const IGNORE_DIRS = new Set([
  "node_modules",
  ".next",
  ".next_build",
  "dist",
  "build",
])

const IGNORE_FILES = new Set([
  path.join("types", "openapi.ts"),
  "openapi.json",
  path.join("scripts", "check-native-dialogs.mjs"),
  path.join("scripts", "check-design-tokens.mjs"),
])

const IGNORE_PATH_PREFIXES = new Set([
  path.join("public", "monaco"),
])

const INCLUDE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs"])

const RULES = [
  {
    id: "confirm",
    description: "Avoid native confirm dialogs; use AlertDialog/ConfirmDialog.",
    re: /\b(?:window\.)?confirm\s*\(/g,
  },
  {
    id: "prompt",
    description: "Avoid native prompt dialogs; use Dialog with Input/Textarea.",
    re: /\b(?:window\.)?prompt\s*\(/g,
  },
]

function isIgnoredPath(rel) {
  for (const prefix of IGNORE_PATH_PREFIXES) {
    if (rel === prefix || rel.startsWith(`${prefix}${path.sep}`)) {
      return true
    }
  }
  return false
}

async function collectFiles(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true })
  const out = []
  for (const ent of entries) {
    if (ent.name.startsWith(".")) {
      // Skip dotfolders (handled explicitly above where needed).
      if (ent.name !== ".next" && ent.name !== ".next_build") continue
    }

    const abs = path.join(dir, ent.name)
    const rel = path.relative(WEB_ROOT, abs)

    if (ent.isDirectory()) {
      if (IGNORE_DIRS.has(ent.name) || isIgnoredPath(rel)) continue
      out.push(...(await collectFiles(abs)))
      continue
    }

    if (!ent.isFile()) continue

    const ext = path.extname(ent.name)
    if (!INCLUDE_EXTENSIONS.has(ext)) continue
    if (IGNORE_FILES.has(rel) || isIgnoredPath(rel)) continue

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
  return raw.replace(/\s+/g, " ").trim()
}

async function main() {
  const files = await collectFiles(WEB_ROOT)
  const violations = []

  for (const { abs, rel } of files) {
    let text
    try {
      text = await fs.readFile(abs, "utf8")
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
    process.stdout.write("ui-check(native-dialogs): OK (no confirm()/prompt() found)\n")
    return
  }

  process.stderr.write(`ui-check(native-dialogs): FAILED (${violations.length} violations)\n\n`)
  for (const v of violations.slice(0, 200)) {
    process.stderr.write(`${v.file}:${v.line}  [${v.rule}]  ${v.match}\n`)
    process.stderr.write(`  ${v.excerpt}\n`)
  }
  if (violations.length > 200) {
    process.stderr.write(`\n...and ${violations.length - 200} more\n`)
  }

  process.stderr.write("\nBanned patterns:\n")
  for (const rule of RULES) {
    process.stderr.write(`- ${rule.id}: ${rule.description}\n`)
  }
  process.stderr.write("\n")

  process.exit(1)
}

main().catch((err) => {
  process.stderr.write(`ui-check(native-dialogs): ERROR ${String(err?.message || err)}\n`)
  process.exit(2)
})
