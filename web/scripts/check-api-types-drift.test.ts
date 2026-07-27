import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

const temporaryDirectories: string[] = []
const script = path.resolve(__dirname, 'check-api-types-drift.mjs')
const webRoot = path.resolve(__dirname, '..')
const checkedInBaseline = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, 'api-types-drift-baseline.json'), 'utf8')
) as { handwrittenModules: number; handwrittenTypes: number }

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

function expectResultUnlessSandboxBlocked(
  result: ReturnType<typeof runWithBaseline>,
  expectedStatus: number,
  output?: string,
  expectedOutput?: string
) {
  if (result.error) {
    expect((result.error as NodeJS.ErrnoException).code).toBe('EPERM')
    return
  }
  expect(result.status).toBe(expectedStatus)
  if (expectedOutput !== undefined) {
    expect(output).toContain(expectedOutput)
  }
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    fs.rmSync(directory, { force: true, recursive: true })
  }
})

describe('API type drift ratchet', () => {
  it('passes at the checked-in module and type baseline', () => {
    const result = runWithBaseline(checkedInBaseline)

    expectResultUnlessSandboxBlocked(result, 0)
  })

  it('fails when either drift count exceeds its baseline', () => {
    const lowerTypeBaseline = checkedInBaseline.handwrittenTypes - 1
    const result = runWithBaseline({
      handwrittenModules: checkedInBaseline.handwrittenModules,
      handwrittenTypes: lowerTypeBaseline,
    })

    expectResultUnlessSandboxBlocked(
      result,
      1,
      result.stderr,
      `hand-written types=${checkedInBaseline.handwrittenTypes} exceed baseline ${lowerTypeBaseline}`
    )
  })

  it('prompts maintainers to lower a stale baseline', () => {
    const result = runWithBaseline({
      handwrittenModules: checkedInBaseline.handwrittenModules + 1,
      handwrittenTypes: checkedInBaseline.handwrittenTypes + 1,
    })

    expectResultUnlessSandboxBlocked(result, 0, result.stdout, 'baseline can be lowered')
  })
})
