import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

const temporaryDirectories: string[] = []
const script = path.resolve(__dirname, 'check-api-types-drift.mjs')
const webRoot = path.resolve(__dirname, '..')

function runWithBaseline(baseline: { handwrittenModules: number; handwrittenTypes: number }) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'mimirq-api-drift-'))
  temporaryDirectories.push(directory)
  const baselinePath = path.join(directory, 'baseline.json')
  fs.writeFileSync(baselinePath, JSON.stringify(baseline), 'utf8')
  return spawnSync(process.execPath, [script, '--strict', '--baseline', baselinePath], {
    cwd: webRoot,
    encoding: 'utf8',
  })
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    fs.rmSync(directory, { force: true, recursive: true })
  }
})

describe('API type drift ratchet', () => {
  it('passes at the checked-in module and type baseline', () => {
    const result = runWithBaseline({ handwrittenModules: 15, handwrittenTypes: 87 })

    expect(result.status).toBe(0)
  })

  it('fails when either drift count exceeds its baseline', () => {
    const result = runWithBaseline({ handwrittenModules: 15, handwrittenTypes: 86 })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('hand-written types=87 exceed baseline 86')
  })

  it('prompts maintainers to lower a stale baseline', () => {
    const result = runWithBaseline({ handwrittenModules: 16, handwrittenTypes: 88 })

    expect(result.status).toBe(0)
    expect(result.stdout).toContain('baseline can be lowered')
  })
})
