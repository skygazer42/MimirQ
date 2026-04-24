import net from 'node:net'

const MAX_PORT_SEARCH = 20

function readStringFlag(argv, flag) {
  const index = argv.indexOf(flag)
  if (index === -1) return null
  const value = argv[index + 1]
  if (!value || value.startsWith('--')) return null
  return value
}

function parsePort(value, fallbackPort) {
  const numeric = Number(value)
  if (!Number.isInteger(numeric) || numeric <= 0 || numeric > 65_535) {
    return fallbackPort
  }
  return numeric
}

export function resolveDevServerOptions(argv = [], env = process.env) {
  const args = {
    public: argv.includes('--public'),
    start: argv.includes('--start'),
    turbopack: argv.includes('--turbopack'),
    host: readStringFlag(argv, '--host'),
    port: readStringFlag(argv, '--port'),
  }

  const defaultHost = args.public ? '0.0.0.0' : '127.0.0.1'
  const rawPort = env.PORT || env.NEXT_DEV_PORT || '3000'
  const host = args.host || env.HOST || env.NEXT_DEV_HOST || defaultHost
  const port = parsePort(args.port || rawPort, 3000)

  return {
    host,
    port,
    mode: args.start ? 'start' : 'dev',
    turbopack: args.turbopack,
    isPublic: args.public,
  }
}

export function isPortAvailable(port, host) {
  return new Promise((resolve) => {
    const server = net.createServer()

    const finish = (available) => {
      server.removeAllListeners()
      try {
        server.close(() => resolve(available))
      } catch {
        resolve(available)
      }
    }

    server.once('error', () => finish(false))
    server.once('listening', () => finish(true))
    server.listen(port, host)
  })
}

export async function findAvailablePort(preferredPort, host, probe = isPortAvailable) {
  for (let candidate = preferredPort; candidate < preferredPort + MAX_PORT_SEARCH; candidate += 1) {
    if (await probe(candidate, host)) {
      return candidate
    }
  }

  throw new Error(`No available port found between ${preferredPort} and ${preferredPort + MAX_PORT_SEARCH - 1}.`)
}

export async function finalizeDevServerOptions(options) {
  const resolvedPort = await findAvailablePort(options.port, options.host)

  return {
    ...options,
    port: resolvedPort,
    fallbackMessage:
      resolvedPort === options.port ? null : `Port ${options.port} is busy; using ${resolvedPort} instead.`,
  }
}

export function buildNextArgs(options) {
  if (options.mode === 'start') {
    return ['start', '-H', options.host, '-p', String(options.port)]
  }

  return [
    'dev',
    options.turbopack ? '--turbopack' : '--webpack',
    '-H',
    options.host,
    '-p',
    String(options.port),
  ]
}
