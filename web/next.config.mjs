/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
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

export default nextConfig
