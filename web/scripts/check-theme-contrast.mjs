#!/usr/bin/env node
/**
 * Theme contrast guard.
 *
 * Ensures key semantic foreground/background token pairs meet WCAG AA.
 * This keeps future palette tweaks from silently regressing readability.
 */

import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import chroma from 'chroma-js'

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(SCRIPT_DIR, '..')
const GLOBALS_PATH = path.join(WEB_ROOT, 'app', 'globals.css')

const CHECKS = [
  { id: 'body', fg: 'foreground', bg: 'background', min: 4.5 },
  { id: 'card', fg: 'card-foreground', bg: 'card', min: 4.5 },
  { id: 'popover', fg: 'popover-foreground', bg: 'popover', min: 4.5 },
  { id: 'sidebar', fg: 'sidebar-foreground', bg: 'sidebar-background', min: 4.5 },
  { id: 'muted-copy', fg: 'muted-foreground', bg: 'background', min: 4.5 },
  { id: 'primary-control', fg: 'primary-foreground', bg: 'primary', min: 4.5 },
  { id: 'success-control', fg: 'success-foreground', bg: 'success', min: 4.5 },
  { id: 'warning-control', fg: 'warning-foreground', bg: 'warning', min: 4.5 },
  { id: 'info-control', fg: 'info-foreground', bg: 'info', min: 4.5 },
  { id: 'destructive-control', fg: 'destructive-foreground', bg: 'destructive', min: 4.5 },
]

function extractBlock(source, marker) {
  const markerIndex = source.indexOf(marker)
  if (markerIndex === -1) return null

  const braceStart = source.indexOf('{', markerIndex)
  if (braceStart === -1) return null

  let depth = 0
  for (let index = braceStart; index < source.length; index += 1) {
    const ch = source[index]
    if (ch === '{') depth += 1
    if (ch === '}') {
      depth -= 1
      if (depth === 0) {
        return source.slice(braceStart + 1, index)
      }
    }
  }

  return null
}

function parseCssVariables(block) {
  const vars = new Map()
  const regex = /--([a-z0-9-]+)\s*:\s*([^;]+);/gi
  let match
  while ((match = regex.exec(block)) !== null) {
    vars.set(match[1], match[2].trim())
  }
  return vars
}

function isHslTriplet(value) {
  return /^\d+(?:\.\d+)?\s+\d+(?:\.\d+)?%\s+\d+(?:\.\d+)?%$/u.test(value.trim())
}

function toColor(value) {
  return chroma(`hsl(${value.trim()})`)
}

function formatRatio(value) {
  return value.toFixed(2)
}

async function main() {
  const source = await fs.readFile(GLOBALS_PATH, 'utf8')
  const lightBlock = extractBlock(source, ':root')
  const darkBlock = extractBlock(source, 'html.dark {')

  if (!lightBlock || !darkBlock) {
    throw new Error('Could not locate :root/default html.dark token blocks in app/globals.css')
  }

  const themes = [
    { name: 'light', vars: parseCssVariables(lightBlock) },
    { name: 'dark', vars: parseCssVariables(darkBlock) },
  ]

  const failures = []
  const reports = []

  for (const theme of themes) {
    for (const check of CHECKS) {
      const fgValue = theme.vars.get(check.fg)
      const bgValue = theme.vars.get(check.bg)

      if (!fgValue || !bgValue) {
        failures.push({
          theme: theme.name,
          check: check.id,
          message: `missing token(s): ${check.fg}, ${check.bg}`,
        })
        continue
      }

      if (!isHslTriplet(fgValue) || !isHslTriplet(bgValue)) {
        failures.push({
          theme: theme.name,
          check: check.id,
          message: `non-HSL token value(s): ${check.fg}=${fgValue}, ${check.bg}=${bgValue}`,
        })
        continue
      }

      const ratio = chroma.contrast(toColor(fgValue), toColor(bgValue))
      reports.push(`${theme.name}:${check.id}=${formatRatio(ratio)}`)
      if (ratio < check.min) {
        failures.push({
          theme: theme.name,
          check: check.id,
          message: `${check.fg} on ${check.bg} is ${formatRatio(ratio)} (needs ${check.min.toFixed(1)})`,
        })
      }
    }
  }

  if (failures.length) {
    process.stderr.write(`ui-check(contrast): FAILED (${failures.length} violations)\n\n`)
    for (const failure of failures) {
      process.stderr.write(`${failure.theme}:${failure.check}  ${failure.message}\n`)
    }
    process.stderr.write('\nMeasured ratios:\n')
    for (const report of reports) {
      process.stderr.write(`- ${report}\n`)
    }
    process.stderr.write('\n')
    process.exit(1)
  }

  process.stdout.write(`ui-check(contrast): OK (${reports.join(', ')})\n`)
}

main().catch((err) => {
  process.stderr.write(`ui-check(contrast): ERROR ${String(err?.message || err)}\n`)
  process.exit(2)
})
