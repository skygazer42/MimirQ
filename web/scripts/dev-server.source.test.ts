import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('dev server script wiring', () => {
  it('routes local dev and start commands through a configurable wrapper', () => {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.dev).toBe('node scripts/dev-server.mjs')
    expect(pkg.scripts?.['dev:turbo']).toBe('node scripts/dev-server.mjs --turbopack')
    expect(pkg.scripts?.['dev:public']).toBe('node scripts/dev-server.mjs --public')
    expect(pkg.scripts?.['dev:turbo:public']).toBe('node scripts/dev-server.mjs --turbopack --public')
    expect(pkg.scripts?.start).toBe('node scripts/dev-server.mjs --start')
    expect(pkg.scripts?.['start:public']).toBe('node scripts/dev-server.mjs --start --public')
    expect(fs.existsSync(path.resolve(__dirname, 'dev-server.mjs'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'dev-server-lib.mjs'))).toBe(true)
  })

  it('keeps localhost defaults, public override support, and automatic port fallback in the wrapper', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'dev-server.mjs'), 'utf8')
    const helperSrc = fs.readFileSync(path.resolve(__dirname, 'dev-server-lib.mjs'), 'utf8')

    expect(src).toContain("createRequire(import.meta.url)")
    expect(src).toContain("require.resolve('next/dist/bin/next')")
    expect(helperSrc).toContain("const defaultHost = args.public ? '0.0.0.0' : '127.0.0.1'")
    expect(helperSrc).toContain("const rawPort = env.PORT || env.NEXT_DEV_PORT || '3000'")
    expect(helperSrc).toContain("await findAvailablePort(options.port, options.host)")
    expect(helperSrc).toContain('Port ${options.port} is busy; using ${resolvedPort} instead.')
  })
})
