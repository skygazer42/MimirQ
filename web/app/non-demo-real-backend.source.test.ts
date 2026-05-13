import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const WEB_ROOT = path.resolve(__dirname, '..')
const SOURCE_ROOTS = ['app', 'components', 'lib'] as const
const SOURCE_RE = /\.(ts|tsx)$/
const TEST_RE = /\.(test|source\.test)\.(ts|tsx)$/

const FORBIDDEN_SOURCE_PATTERNS: Array<[RegExp, string]> = [
  [/onClick=\{\(\) => \{\}\}/, 'empty onClick handler'],
  [/onClick=\{\(\) => undefined\}/, 'undefined onClick handler'],
  [/onClick=\{undefined\}/, 'undefined onClick prop'],
  [/href=["']#["']/, 'placeholder href'],
  [/downloadUrl \|\| ["']#["']/, 'download placeholder URL'],
  [/未接入后端|尚未接入|等待运行接口|尚未调用接口/, 'unwired backend copy'],
  [/模拟数据|假数据|mock data|Mock data/, 'mock/fake data copy'],
  [/toast\.(info|warning|error|success)\([^)]*(未实现|暂不支持|coming soon|待接入|开发中)/, 'placeholder toast action'],
]

const ALLOWED_FORBIDDEN_HITS: Array<{ relativePath: string; pattern: RegExp }> = [
  { relativePath: 'components/app-frame.tsx', pattern: /href=["']#["']/ },
]

const DEMO_GATED_FILES = [
  'app/knowledge/feedback/page.tsx',
  'app/knowledge/ingestion/page-client.tsx',
  'app/knowledge/quarantine/page.tsx',
] as const

function collectSourceFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.next') continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      collectSourceFiles(full, acc)
      continue
    }
    if (!SOURCE_RE.test(entry.name) || TEST_RE.test(entry.name)) continue
    acc.push(full)
  }
  return acc
}

function relative(file: string): string {
  return path.relative(WEB_ROOT, file)
}

function isAllowedForbiddenHit(relativePath: string, pattern: RegExp): boolean {
  return ALLOWED_FORBIDDEN_HITS.some((entry) => entry.relativePath === relativePath && String(entry.pattern) === String(pattern))
}

describe('non-demo real backend contract', () => {
  const files = SOURCE_ROOTS.flatMap((root) => collectSourceFiles(path.join(WEB_ROOT, root)))

  it('does not leave placeholder actions, mock copy, or unwired backend labels in production source', () => {
    const violations: string[] = []

    for (const file of files) {
      const rel = relative(file)
      const src = fs.readFileSync(file, 'utf8')
      for (const [pattern, reason] of FORBIDDEN_SOURCE_PATTERNS) {
        if (pattern.test(src) && !isAllowedForbiddenHit(rel, pattern)) {
          violations.push(`${rel}: ${reason}`)
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('keeps demo datasets gated behind explicit demo query mode and backend queries disabled only in that mode', () => {
    for (const rel of DEMO_GATED_FILES) {
      const src = fs.readFileSync(path.join(WEB_ROOT, rel), 'utf8')

      expect(src, rel).toMatch(/demoMode\s*=\s*[\s\S]*pathname[\s\S]*demo/)
      expect(src, rel).toContain("searchParams.get('demo') === '1'")
      expect(src, rel).toMatch(/enabled:[^\n]+!demoMode/)
      expect(src, rel).not.toContain('打开 Demo')
    }
  })

  it('does not expose demo launch affordances from real pages', () => {
    const launchers = files
      .map((file) => [relative(file), fs.readFileSync(file, 'utf8')] as const)
      .filter(([rel]) => !rel.includes('/demo') && !rel.endsWith('demo-documents.ts'))
      .filter(([, src]) => src.includes('打开 Demo') || src.includes('启动 Demo'))
      .map(([rel]) => rel)

    expect(launchers).toEqual([])
  })
})
