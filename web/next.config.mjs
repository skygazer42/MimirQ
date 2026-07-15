import { withSentryConfig } from '@sentry/nextjs'
import { networkInterfaces } from 'node:os'
import createNextIntlPlugin from 'next-intl/plugin'

const sentryEnabled = Boolean(
  process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN || process.env.SENTRY_AUTH_TOKEN
)
const localDevHostnames = new Set(['localhost', '127.0.0.1', '0.0.0.0', 'web', 'mimirq-api'])
const hstsDisabled =
  String(process.env.NEXT_DISABLE_HSTS || '').trim().toLowerCase() === '1' ||
  String(process.env.NEXT_DISABLE_HSTS || '').trim().toLowerCase() === 'true'

function isLocalDevOrigin(value) {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' && localDevHostnames.has((parsed.hostname || '').toLowerCase())
  } catch {
    return false
  }
}

const shouldSendHsts =
  process.env.NODE_ENV === 'production' &&
  !hstsDisabled &&
  !isLocalDevOrigin(process.env.NEXT_PUBLIC_API_URL || '')
const withNextIntl = createNextIntlPlugin('./i18n/request.ts')
const sharedSecurityHeaders = [
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
]

if (shouldSendHsts) {
  sharedSecurityHeaders.push({
    key: 'Strict-Transport-Security',
    value: 'max-age=63072000; includeSubDomains; preload',
  })
}

function isPrivateLanAddress(value) {
  const text = String(value || '').trim()
  if (!text) return false
  if (text === '127.0.0.1' || text === '0.0.0.0') return true
  if (text.startsWith('10.')) return true
  if (text.startsWith('192.168.')) return true

  const match = /^172\.(\d{1,3})\./.exec(text)
  if (!match) return false

  const secondOctet = Number(match[1])
  return Number.isFinite(secondOctet) && secondOctet >= 16 && secondOctet <= 31
}

function collectLanInterfaceOrigins(interfaces) {
  const out = []

  for (const items of Object.values(interfaces || {})) {
    for (const item of items || []) {
      if (!item || item.family !== 'IPv4') continue
      if (item.internal) continue
      if (!isPrivateLanAddress(item.address)) continue
      out.push(String(item.address))
    }
  }

  return out
}

function trimConfigUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

export function resolveAllowedDevOrigins(
  env = process.env,
  interfaces = networkInterfaces()
) {
  const extra = String(env.NEXT_ALLOWED_DEV_ORIGINS || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

  return Array.from(
    new Set([
      '127.0.0.1',
      'localhost',
      '0.0.0.0',
      ...collectLanInterfaceOrigins(interfaces),
      ...extra,
    ])
  )
}

export function resolveBackendProxyBase(env = process.env) {
  const candidates = [
    trimConfigUrl(env.API_INTERNAL_URL),
    trimConfigUrl(env.NEXT_PUBLIC_API_URL),
    'http://127.0.0.1:8000',
  ]

  for (const candidate of candidates) {
    if (candidate.startsWith('http://') || candidate.startsWith('https://')) {
      return candidate
    }
  }

  return 'http://127.0.0.1:8000'
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  allowedDevOrigins: resolveAllowedDevOrigins(),
  distDir:
    process.env.NEXT_DIST_DIR ||
    (process.env.NODE_ENV === 'production' ? '.next_build' : '.next'),
  webpack: (config, { webpack }) => {
    config.plugins.push({
      apply: (compiler) => {
        compiler.hooks.compilation.tap('MimirQPdfjsWorkerMinifyFix', (compilation) => {
          compilation.hooks.processAssets.tap(
            {
              name: 'MimirQPdfjsWorkerMinifyFix',
              stage: webpack.Compilation.PROCESS_ASSETS_STAGE_OPTIMIZE,
            },
            () => {
              for (const asset of compilation.getAssets()) {
                if (/static\/media\/pdf\.worker(\.min)?\..*\.mjs$/i.test(asset.name)) {
                  compilation.updateAsset(asset.name, asset.source, {
                    ...asset.info,
                    minimized: true,
                    javascriptModule: true,
                  })
                }
              }
            }
          )
        })
      },
    })
    return config
  },
  images: {
    remotePatterns: [
      { protocol: 'http', hostname: 'localhost', port: '8000', pathname: '/**' },
      { protocol: 'http', hostname: '127.0.0.1', port: '8000', pathname: '/**' },
      { protocol: 'http', hostname: 'backend', port: '8000', pathname: '/**' },
    ],
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: sharedSecurityHeaders,
      },
    ]
  },
  async rewrites() {
    const backendBase = resolveBackendProxyBase()
    return [
      {
        source: '/api/v1/documents',
        destination: `${backendBase}/api/v1/documents/`,
      },
      {
        source: '/api/v1/datasets',
        destination: `${backendBase}/api/v1/datasets/`,
      },
      {
        source: '/api/v1/groups',
        destination: `${backendBase}/api/v1/groups/`,
      },
      {
        source: '/api/v1/:path*',
        destination: `${backendBase}/api/v1/:path*`,
      },
    ]
  },
}

const nextIntlConfig = withNextIntl(nextConfig)

const sentryWrappedConfig = withSentryConfig(nextIntlConfig, {
  silent: true,
  disableLogger: true,
})

export default sentryEnabled ? sentryWrappedConfig : nextIntlConfig
