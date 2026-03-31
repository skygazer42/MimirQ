#!/usr/bin/env node

import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(SCRIPT_DIR, '..')
const OUT_DIR = path.join(WEB_ROOT, 'public', 'monaco', 'vs')

async function main() {
  const monacoPackageJson = require.resolve('monaco-editor/package.json')
  const monacoRoot = path.dirname(monacoPackageJson)
  const sourceDir = path.join(monacoRoot, 'min', 'vs')

  await fs.rm(OUT_DIR, { recursive: true, force: true })
  await fs.mkdir(path.dirname(OUT_DIR), { recursive: true })
  await fs.cp(sourceDir, OUT_DIR, { recursive: true })

  process.stdout.write(`Synced Monaco assets to ${path.relative(WEB_ROOT, OUT_DIR)}\n`)
}

main().catch((err) => {
  process.stderr.write(`sync-monaco-assets: ERROR ${String(err?.message || err)}\n`)
  process.exit(1)
})
