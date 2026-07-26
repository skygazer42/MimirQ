#!/usr/bin/env node
/**
 * Build budget guard.
 *
 * Keeps key app-route entry bundles within predictable budgets so heavy
 * dependencies do not silently spill into the primary surfaces.
 */

import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(SCRIPT_DIR, '..')

async function resolveDistDir() {
  if (process.env.NEXT_DIST_DIR) return process.env.NEXT_DIST_DIR

  for (const candidate of ['.next_build', '.next']) {
    try {
      await fs.access(path.join(WEB_ROOT, candidate, 'static', 'chunks'))
      return candidate
    } catch {
      // try next candidate
    }
  }

  return process.env.NODE_ENV === 'production' ? '.next_build' : '.next'
}

const BUDGETS = [
  { id: 'main-app-shell', re: /^main-app-.*\.js$/, maxBytes: 90 * 1024 },
  { id: 'main-runtime', re: /^main-(?!app-).+\.js$/, maxBytes: 170 * 1024 },
  { id: 'framework', re: /^framework-.*\.js$/, maxBytes: 220 * 1024 },
  { id: 'polyfills', re: /^polyfills-.*\.js$/, maxBytes: 130 * 1024 },
  { id: 'home-route', re: /^app\/page-.*\.js$/, maxBytes: 80 * 1024 },
  { id: 'graph-route', re: /^app\/graph\/page-.*\.js$/, maxBytes: 121 * 1024 },
  { id: 'knowledge-route', re: /^app\/knowledge\/page-.*\.js$/, maxBytes: 220 * 1024 },
  // These surfaces are expected to keep Monaco and ECharts behind lazy boundaries.
  { id: 'chunk-preview-route', re: /^app\/chunk-preview\/page-.*\.js$/, maxBytes: 20 * 1024 },
  { id: 'knowledge-similarity-route', re: /^app\/knowledge\/similarity\/page-.*\.js$/, maxBytes: 20 * 1024 },
  { id: 'settings-route', re: /^app\/settings\/page-.*\.js$/, maxBytes: 120 * 1024 },
  // Locale-route wrappers add a bit more app-entry manifest overhead to this route.
  { id: 'parsing-route', re: /^app\/parsing\/page-.*\.js$/, maxBytes: 120 * 1024 },
  { id: 'evaluations-route', re: /^app\/evaluations\/page-.*\.js$/, maxBytes: 90 * 1024 },
]

async function collectFiles(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const absolutePath = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...(await collectFiles(absolutePath)))
      continue
    }
    if (entry.isFile() && entry.name.endsWith('.js')) {
      files.push(absolutePath)
    }
  }
  return files
}

function formatKiB(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`
}

async function main() {
  const distDir = await resolveDistDir()
  const chunksDir = path.join(WEB_ROOT, distDir, 'static', 'chunks')

  try {
    await fs.access(chunksDir)
  } catch {
    throw new Error(`build output not found at ${path.relative(WEB_ROOT, chunksDir)}; run build first`)
  }

  const files = await collectFiles(chunksDir)
  const byRelativePath = files.map((absolutePath) => ({
    absolutePath,
    relativePath: path.relative(chunksDir, absolutePath).replaceAll(path.sep, '/'),
  }))

  const failures = []
  const reports = []

  for (const budget of BUDGETS) {
    const matches = byRelativePath.filter((file) => budget.re.test(file.relativePath))
    if (matches.length !== 1) {
      failures.push({
        id: budget.id,
        message: `expected exactly 1 chunk, found ${matches.length}`,
      })
      continue
    }

    const [{ absolutePath, relativePath }] = matches
    const size = (await fs.stat(absolutePath)).size
    reports.push(`${budget.id}=${formatKiB(size)}`)

    if (size > budget.maxBytes) {
      failures.push({
        id: budget.id,
        message: `${relativePath} is ${formatKiB(size)} (budget ${formatKiB(budget.maxBytes)})`,
      })
    }
  }

  if (failures.length) {
    process.stderr.write(`bundle-check: FAILED (${failures.length} violations)\n\n`)
    for (const failure of failures) {
      process.stderr.write(`${failure.id}  ${failure.message}\n`)
    }
    process.stderr.write('\nMeasured bundle sizes:\n')
    for (const report of reports) {
      process.stderr.write(`- ${report}\n`)
    }
    process.stderr.write('\n')
    process.exit(1)
  }

  process.stdout.write(`bundle-check: OK (${reports.join(', ')})\n`)
}

main().catch((err) => {
  process.stderr.write(`bundle-check: ERROR ${String(err?.message || err)}\n`)
  process.exit(2)
})
