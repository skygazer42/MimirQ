import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const WEB_ROOT = path.resolve(__dirname, '../..')

describe('knowledge non-demo pages', () => {
  it('do not expose demo launch buttons outside direct demo routes', () => {
    for (const relativePath of [
      'app/knowledge/ingestion/page-client.tsx',
      'app/knowledge/feedback/page.tsx',
      'app/knowledge/quarantine/page.tsx',
    ]) {
      const src = fs.readFileSync(path.resolve(WEB_ROOT, relativePath), 'utf8')

      expect(src, relativePath).not.toContain('打开 Demo')
    }
  })
})
