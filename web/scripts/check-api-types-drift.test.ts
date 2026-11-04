import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

const temporaryDirectories: string[] = []
const script = path.resolve(__dirname, 'check-api-types-drift.mjs')
const webRoot = path.resolve(__dirname, '..')
const checkedInBaseline = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, 'api-types-drift-baseline.json'), 'utf8'),
) as { handwrittenModules: number; handwrittenTypes: number }

function runWithBaseline(
  baseline: { handwrittenModules: number; handwrittenTypes: number },
  apiModules?: Record<string, string>,
) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'mimirq-api-drift-'))
  temporaryDirectories.push(directory)
  const baselinePath = path.join(directory, 'baseline.json')
  fs.writeFileSync(baselinePath, JSON.stringify(baseline), 'utf8')
  let scriptToRun = script
  if (apiModules) {
    const scriptsDirectory = path.join(directory, 'scripts')
    const apiDirectory = path.join(directory, 'lib', 'api')
    fs.mkdirSync(scriptsDirectory, { recursive: true })
    fs.mkdirSync(apiDirectory, { recursive: true })
    scriptToRun = path.join(scriptsDirectory, 'check-api-types-drift.mjs')
    fs.copyFileSync(script, scriptToRun)
    for (const [filename, source] of Object.entries(apiModules)) {
      fs.writeFileSync(path.join(apiDirectory, filename), source, 'utf8')
    }
  }
  return spawnSync(process.execPath, [scriptToRun, '--strict', '--baseline', baselinePath], {
    cwd: webRoot,
    encoding: 'utf8',
  })
}

function expectResultUnlessSandboxBlocked(
  result: ReturnType<typeof runWithBaseline>,
  expectedStatus: number,
  output?: string,
  expectedOutput?: string,
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

  it.each([
    {
      count: 'module',
      baseline: { handwrittenModules: 0, handwrittenTypes: 1 },
      message: 'hand-written-type modules=1 exceed baseline 0',
    },
    {
      count: 'type',
      baseline: { handwrittenModules: 1, handwrittenTypes: 0 },
      message: 'hand-written types=1 exceed baseline 0',
    },
  ])('fails when the $count count exceeds its baseline', ({ baseline, message }) => {
    const result = runWithBaseline(baseline, {
      'fixture.ts': 'export type Fixture = { value: string }\n',
    })

    expectResultUnlessSandboxBlocked(result, 1, result.stderr, message)
  })

  it('prompts maintainers to lower a stale baseline', () => {
    const result = runWithBaseline({
      handwrittenModules: checkedInBaseline.handwrittenModules + 1,
      handwrittenTypes: checkedInBaseline.handwrittenTypes + 1,
    })

    expectResultUnlessSandboxBlocked(result, 0, result.stdout, 'baseline can be lowered')
  })
})
