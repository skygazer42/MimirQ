import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import { expect, it } from 'vitest'

it('loads the Tailwind configuration in the ESM context used by the development server', () => {
  const configUrl = pathToFileURL(path.resolve(__dirname, 'tailwind.config.ts')).href
  const result = spawnSync(
    process.execPath,
    ['--input-type=module', '--eval', 'await import(' + JSON.stringify(configUrl) + ')'],
    {
      encoding: 'utf8',
    },
  )
  expect(result.status, result.stderr).toBe(0)
})
