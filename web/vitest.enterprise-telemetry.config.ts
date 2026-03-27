import path from 'node:path'

const config = {
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  test: {
    environment: 'node',
    pool: 'threads',
    include: [
      'components/providers/service-worker-registrar.test.ts',
      'components/providers/web-vitals-reporter.test.ts',
      'lib/api-client-observability.test.ts',
      'lib/fetch-errors.test.ts',
      'lib/preferred-language.test.ts',
      'lib/request-id.test.ts',
      'lib/auth-headers.test.ts',
    ],
    reporters: ['default'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary', 'lcov', 'html'],
      reportsDirectory: './coverage/enterprise-telemetry',
      include: [
        'components/providers/service-worker-registrar.tsx',
        'components/providers/web-vitals-reporter.tsx',
        'lib/fetch-errors.ts',
        'lib/auth-headers.ts',
        'lib/preferred-language.ts',
        'lib/request-id.ts',
      ],
      exclude: [
        '**/*.test.{ts,tsx}',
        '**/*.source.test.{ts,tsx}',
        '**/node_modules/**',
        '**/.next/**',
        '**/coverage/**',
      ],
      thresholds: {
        statements: 70,
        branches: 50,
        functions: 70,
        lines: 70,
      },
    },
  },
}

export default config
