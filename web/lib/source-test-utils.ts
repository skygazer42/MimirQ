import fs from 'node:fs'
import path from 'node:path'

import { expect } from 'vitest'

export function normalizeSourceSnippet(value: string): string {
  let normalized = ''
  let previousWasSpace = false
  for (const char of value) {
    const next = char === "'" || char === '"' ? '"' : char
    if (/\s/u.test(next)) {
      if (!previousWasSpace) normalized += ' '
      previousWasSpace = true
    } else {
      normalized += next
      previousWasSpace = false
    }
  }
  return normalized
    .trim()
    .replaceAll(' .', '.')
    .replaceAll(', }', '}')
    .replaceAll(', ]', ']')
    .replaceAll(', )', ')')
    .replaceAll('( ', '(')
    .replaceAll(' )', ')')
    .replaceAll('[ ', '[')
    .replaceAll(' ]', ']')
    .replaceAll('{ ', '{')
    .replaceAll(' }', '}')
    .replaceAll('< ', '<')
    .replaceAll(' >', '>')
    .replaceAll('> ', '>')
    .replaceAll(' </', '</')
}

export function expectSourceToContain(source: string, snippet: string): void {
  expect(normalizeSourceSnippet(source)).toContain(normalizeSourceSnippet(snippet))
}

export function expectSourceNotToContain(source: string, snippet: string): void {
  expect(normalizeSourceSnippet(source)).not.toContain(normalizeSourceSnippet(snippet))
}

export function readMessageCatalogSource(webRoot: string): string {
  const rootPath = path.resolve(webRoot, 'i18n/messages/zh-CN.ts')
  const moduleDir = path.resolve(webRoot, 'i18n/messages/zh-CN')
  const parts = [fs.readFileSync(rootPath, 'utf8')]

  if (fs.existsSync(moduleDir)) {
    for (const fileName of fs.readdirSync(moduleDir).sort((a, b) => a.localeCompare(b))) {
      if (fileName.endsWith('.ts')) {
        parts.push(fs.readFileSync(path.join(moduleDir, fileName), 'utf8'))
      }
    }
  }

  return parts.join('\n')
}
