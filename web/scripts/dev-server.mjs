import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'

import { buildNextArgs, finalizeDevServerOptions, resolveDevServerOptions } from './dev-server-lib.mjs'

const require = createRequire(import.meta.url)

async function main() {
  const baseOptions = resolveDevServerOptions(process.argv.slice(2), process.env)
  const options = await finalizeDevServerOptions(baseOptions)
  const nextBin = require.resolve('next/dist/bin/next')

  if (options.fallbackMessage) {
    console.warn(`[dev-server] ${options.fallbackMessage}`)
  }

  const displayHost = options.host === '0.0.0.0' ? 'localhost' : options.host
  console.log(`[dev-server] Starting Next ${options.mode} on http://${displayHost}:${options.port}`)

  const child = spawn(process.execPath, [nextBin, ...buildNextArgs(options)], {
    stdio: 'inherit',
    env: process.env,
  })

  const forwardSignal = (signal) => {
    if (!child.killed) {
      child.kill(signal)
    }
  }

  process.on('SIGINT', forwardSignal)
  process.on('SIGTERM', forwardSignal)

  child.on('exit', (code, signal) => {
    process.off('SIGINT', forwardSignal)
    process.off('SIGTERM', forwardSignal)

    if (signal) {
      process.kill(process.pid, signal)
      return
    }

    process.exit(code ?? 0)
  })
}

main().catch((error) => {
  console.error('[dev-server] Failed to start Next.js', error)
  process.exit(1)
})
