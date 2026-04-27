import { describe, expect, it } from 'vitest'

import { buildNextArgs, findAvailablePort, resolveDevServerOptions } from './dev-server-lib.mjs'

describe('dev server helpers', () => {
  it('defaults local development to localhost:3000 with webpack', () => {
    const options = resolveDevServerOptions([], { NODE_ENV: 'test' })

    expect(options).toEqual({
      host: '127.0.0.1',
      port: 3000,
      mode: 'dev',
      turbopack: false,
      isPublic: false,
    })
  })

  it('supports public binding, custom host/port env, and start mode', () => {
    const options = resolveDevServerOptions(['--start', '--public'], {
      NODE_ENV: 'test',
      HOST: '192.0.2.20',
      PORT: '4010',
      NEXT_DEV_HOST: '127.0.0.1',
      NEXT_DEV_PORT: '3000',
    })

    expect(options).toEqual({
      host: '192.0.2.20',
      port: 4010,
      mode: 'start',
      turbopack: false,
      isPublic: true,
    })
  })

  it('builds next cli args from the resolved mode', () => {
    expect(buildNextArgs({ mode: 'dev', host: '127.0.0.1', port: 3000, turbopack: false, isPublic: false })).toEqual([
      'dev',
      '--webpack',
      '-H',
      '127.0.0.1',
      '-p',
      '3000',
    ])

    expect(buildNextArgs({ mode: 'dev', host: '0.0.0.0', port: 3100, turbopack: true, isPublic: true })).toEqual([
      'dev',
      '--turbopack',
      '-H',
      '0.0.0.0',
      '-p',
      '3100',
    ])

    expect(buildNextArgs({ mode: 'start', host: '127.0.0.1', port: 4100, turbopack: false, isPublic: false })).toEqual([
      'start',
      '-H',
      '127.0.0.1',
      '-p',
      '4100',
    ])
  })

  it('returns the requested port when it is available', async () => {
    const port = await findAvailablePort(3187, '127.0.0.1', async (candidate) => candidate === 3187)
    expect(port).toBe(3187)
  })

  it('falls forward when the requested port is already occupied', async () => {
    const port = await findAvailablePort(3188, '127.0.0.1', async (candidate) => candidate >= 3190)

    expect(port).toBe(3190)
  })
})
