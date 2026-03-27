import { withSentryConfig } from '@sentry/nextjs'

const isProduction = process.env.NODE_ENV === 'production'
const sentryEnabled = Boolean(
  process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN || process.env.SENTRY_AUTH_TOKEN
)

function buildCspValue() {
  const directives = [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "script-src 'self' 'wasm-unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: http: https:",
    "font-src 'self' data:",
    "connect-src 'self' http: https: ws: wss:",
    "worker-src 'self' blob:",
    "frame-src 'self' http: https:",
    "form-action 'self'",
    "manifest-src 'self'",
  ]

  if (isProduction) directives.push('upgrade-insecure-requests')

  return directives.join('; ')
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
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
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            // Next.js App Router still emits inline runtime scripts.
            // Keep the strict policy in report-only mode until nonce wiring lands.
            key: 'Content-Security-Policy-Report-Only',
            value: buildCspValue(),
          },
        ],
      },
    ]
  },
  images: {
    remotePatterns: [
      { protocol: 'http', hostname: 'localhost', port: '8000', pathname: '/**' },
      { protocol: 'http', hostname: '127.0.0.1', port: '8000', pathname: '/**' },
      { protocol: 'http', hostname: 'backend', port: '8000', pathname: '/**' },
    ],
  },
}

const sentryWrappedConfig = withSentryConfig(nextConfig, {
  silent: true,
  disableLogger: true,
})

export default sentryEnabled ? sentryWrappedConfig : nextConfig
