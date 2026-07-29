import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptsDir = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.resolve(scriptsDir, '..')
const appRoot = path.join(webRoot, 'app')
const ignoredDirectories = new Set([
  '.next',
  '.next_build',
  'coverage',
  'node_modules',
  'test-results',
])

function walk(directory, predicate) {
  const files = []
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) continue
    const absolutePath = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...walk(absolutePath, predicate))
    else if (entry.isFile() && predicate(absolutePath)) files.push(absolutePath)
  }
  return files
}

function routePatternForPage(pagePath) {
  let relativePath = path.relative(appRoot, path.dirname(pagePath)).split(path.sep).join('/')
  relativePath = relativePath.replace(/^\[locale\](?:\/|$)/, '')
  const segments = relativePath.split('/').filter(Boolean)
  const pattern = segments
    .map((segment) => {
      if (/^\[\[\.\.\.[^\]]+\]\]$/.test(segment)) return '(?:.+)?'
      if (/^\[\.\.\.[^\]]+\]$/.test(segment)) return '.+'
      if (/^\[[^\]]+\]$/.test(segment)) return '[^/]+'
      return segment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    })
    .join('/')
  return new RegExp(`^/${pattern}/?$`)
}

const pagePatterns = walk(appRoot, (filePath) => filePath.endsWith(`${path.sep}page.tsx`))
  .map(routePatternForPage)

const sourceFiles = walk(
  webRoot,
  (filePath) =>
    /\.(?:ts|tsx)$/.test(filePath) &&
    !/\.(?:test|spec)\.(?:ts|tsx)$/.test(filePath) &&
    !filePath.endsWith('.d.ts')
)

const navigationPatterns = [
  /\bhref\s*[:=]\s*["']([^"']+)["']/g,
  /\b(?:router\.(?:push|replace)|redirect|permanentRedirect)\(\s*["']([^"']+)["']/g,
  /\b(?:globalThis\.)?window\.location\.href\s*=\s*["']([^"']+)["']/g,
]
const failures = []

for (const sourcePath of sourceFiles) {
  const source = fs.readFileSync(sourcePath, 'utf8')
  for (const expression of navigationPatterns) {
    let match
    while ((match = expression.exec(source))) {
      const target = match[1]
      if (!target.startsWith('/') || target.startsWith('//') || target.startsWith('/api/')) continue
      const pathname = target.split(/[?#]/, 1)[0].replace(/\/$/, '') || '/'
      if (pagePatterns.some((pattern) => pattern.test(pathname))) continue

      const line = source.slice(0, match.index).split('\n').length
      failures.push(`${path.relative(webRoot, sourcePath)}:${line} -> ${target}`)
    }
  }
}

if (failures.length > 0) {
  console.error('[internal-routes] FAIL: internal navigation targets without a Next.js page:')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log('[internal-routes] OK: all literal internal navigation targets resolve to a page')
}
