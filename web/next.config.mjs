import { withSentryConfig } from '@sentry/nextjs'
import createNextIntlPlugin from 'next-intl/plugin'

const sentryEnabled = Boolean(
  process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN || process.env.SENTRY_AUTH_TOKEN
)
const withNextIntl = createNextIntlPlugin('./i18n/request.ts')

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
  images: {
    remotePatterns: [
      { protocol: 'http', hostname: 'localhost', port: '8000', pathname: '/**' },
      { protocol: 'http', hostname: '127.0.0.1', port: '8000', pathname: '/**' },
      { protocol: 'http', hostname: 'backend', port: '8000', pathname: '/**' },
    ],
  },
}

const nextIntlConfig = withNextIntl(nextConfig)

const sentryWrappedConfig = withSentryConfig(nextIntlConfig, {
  silent: true,
  disableLogger: true,
})

export default sentryEnabled ? sentryWrappedConfig : nextIntlConfig
