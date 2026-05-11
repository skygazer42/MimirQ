import { execSync } from 'node:child_process'

import { describe, expect, it } from 'vitest'

function countMatches(pattern: string): number {
  try {
    const output = execSync(
      `rg -n ${JSON.stringify(pattern)} web -g '*.{ts,tsx}' -g '!**/*.test.ts' -g '!**/*.source.test.ts'`,
      {
        cwd: process.cwd().replace(/\/web$/, ''),
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      }
    )
    return output.trim() ? output.trim().split('\n').length : 0
  } catch {
    return 0
  }
}

describe('type-safety budget', () => {
  it('keeps ts suppression comments out of the frontend source', () => {
    expect(countMatches('@ts-ignore|@ts-nocheck')).toBe(0)
  })

  it('keeps explicit any under the current cleanup budget', () => {
    expect(countMatches(': any\\b|<any>')).toBeLessThanOrEqual(500)
  })
})
