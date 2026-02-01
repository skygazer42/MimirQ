#!/usr/bin/env node
/**
 * Sync selected LobeHub provider icons into `web/public/logos/lobehub/`.
 *
 * We fetch from UNPKG to avoid adding a runtime dependency in the frontend bundle.
 *
 * Usage:
 *   node web/scripts/sync-lobehub-icons.mjs
 *   node web/scripts/sync-lobehub-icons.mjs --version 1.77.0
 */

import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(SCRIPT_DIR, '..')
const OUT_DIR = path.join(WEB_ROOT, 'public', 'logos', 'lobehub')

const PACKAGE = '@lobehub/icons-static-svg'

function parseArgs(argv) {
  const out = {
    version: 'latest',
  }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--version') {
      out.version = argv[i + 1] || out.version
      i += 1
      continue
    }
    if (a === '-h' || a === '--help') {
      out.help = true
      continue
    }
  }
  return out
}

function unpkgUrl(version, filename) {
  // Note: UNPKG always serves a single file at a stable URL.
  return `https://unpkg.com/${PACKAGE}@${version}/icons/${filename}`
}

async function fetchBytes(url) {
  const res = await fetch(url, { headers: { Accept: 'image/svg+xml,*/*' } })
  if (res.status === 404) return null
  if (!res.ok) {
    throw new Error(`fetch failed: ${res.status} ${res.statusText} (${url})`)
  }
  const buf = Buffer.from(await res.arrayBuffer())
  return buf
}

async function syncOne(version, iconName) {
  // Prefer "*-color.svg" when available, fallback to plain SVG.
  const color = await fetchBytes(unpkgUrl(version, `${iconName}-color.svg`))
  if (color) return { bytes: color, source: `${iconName}-color.svg`, out: `${iconName}.svg` }

  const plain = await fetchBytes(unpkgUrl(version, `${iconName}.svg`))
  if (plain) return { bytes: plain, source: `${iconName}.svg`, out: `${iconName}.svg` }

  throw new Error(`icon not found on unpkg: ${iconName}`)
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  if (args.help) {
    process.stdout.write(
      [
        'sync-lobehub-icons',
        '',
        'Sync selected LobeHub icons into web/public/logos/lobehub/',
        '',
        'Usage:',
        '  node web/scripts/sync-lobehub-icons.mjs',
        '  node web/scripts/sync-lobehub-icons.mjs --version 1.77.0',
        '',
      ].join('\n')
    )
    return
  }

  const version = String(args.version || 'latest')

  // Keep this list small and aligned with MODEL_PROVIDERS.
  const ICONS = [
    'openai',
    'anthropic',
    'deepseek',
    'qwen',
    'zhipu',
    'moonshot',
    'ollama',
    'openrouter',
    'together',
    'cohere',
    'jina',
    // Product/provider aliases used by MimirQ:
    'doubao', // ByteDance Ark
    'wenxin', // Baidu Qianfan / ERNIE
    'siliconcloud', // SiliconFlow
    'yi', // LingYiWanWu
  ]

  await fs.mkdir(OUT_DIR, { recursive: true })

  const results = []
  for (const name of ICONS) {
    const r = await syncOne(version, name)
    const outPath = path.join(OUT_DIR, r.out)
    await fs.writeFile(outPath, r.bytes)
    results.push({ name, ...r })
  }

  process.stdout.write(`Synced ${results.length} icons to ${path.relative(WEB_ROOT, OUT_DIR)} (version=${version})\n`)
  for (const r of results) {
    process.stdout.write(`- ${r.name}: ${r.source} -> ${r.out}\n`)
  }
}

main().catch((err) => {
  process.stderr.write(`sync-lobehub-icons: ERROR ${String(err?.message || err)}\n`)
  process.exit(1)
})

