#!/usr/bin/env node

import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(SCRIPT_DIR, '..')
const MONACO_OUT_DIR = path.join(WEB_ROOT, 'public', 'monaco', 'vs')
const PDFJS_OUT_DIR = path.join(WEB_ROOT, 'public', 'pdfjs')

async function syncDirectory(sourceDir, outDir) {
  await fs.rm(outDir, { recursive: true, force: true })
  await fs.mkdir(path.dirname(outDir), { recursive: true })
  await fs.cp(sourceDir, outDir, { recursive: true })
}

async function main() {
  const monacoPackageJson = require.resolve('monaco-editor/package.json')
  const monacoRoot = path.dirname(monacoPackageJson)
  await syncDirectory(path.join(monacoRoot, 'min', 'vs'), MONACO_OUT_DIR)

  const pdfjsPackageJson = require.resolve('pdfjs-dist/package.json')
  const pdfjsRoot = path.dirname(pdfjsPackageJson)
  await fs.rm(PDFJS_OUT_DIR, { recursive: true, force: true })
  await fs.mkdir(PDFJS_OUT_DIR, { recursive: true })
  for (const assetDir of ['build', 'cmaps', 'standard_fonts', 'wasm', 'iccs']) {
    await fs.cp(path.join(pdfjsRoot, assetDir), path.join(PDFJS_OUT_DIR, assetDir), { recursive: true })
  }

  process.stdout.write(`Synced Monaco assets to ${path.relative(WEB_ROOT, MONACO_OUT_DIR)}\n`)
  process.stdout.write(`Synced pdf.js assets to ${path.relative(WEB_ROOT, PDFJS_OUT_DIR)}\n`)
}

main().catch((err) => {
  process.stderr.write(`sync-monaco-assets: ERROR ${String(err?.message || err)}\n`)
  process.exit(1)
})
