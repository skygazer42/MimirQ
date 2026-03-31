import { spawnSync } from 'node:child_process'

const args = process.argv.slice(2)
const forwardedArgs = args[0] === '--' ? args.slice(1) : args
const env = {
  ...process.env,
  PLAYWRIGHT_LIVE_STACK: '1',
}

const result = spawnSync(
  process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm',
  ['exec', 'playwright', 'test', '-c', 'playwright.live.config.ts', ...forwardedArgs],
  {
    stdio: 'inherit',
    env,
  }
)

process.exit(result.status ?? 1)
