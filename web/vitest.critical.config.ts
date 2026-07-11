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
    include: ['**/*.test.{ts,tsx}'],
    reporters: ['default'],
    testTimeout: 15000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary', 'lcov'],
      reportsDirectory: './coverage/critical',
      include: [
        'lib/auth-headers.ts',
        'lib/client-storage.ts',
        'lib/navigation-visibility.ts',
        'lib/openapi-request.ts',
        'lib/request-id.ts',
        'lib/sse-reader.ts',
        'lib/sse.ts',
        'lib/tenant-permissions.ts',
      ],
      thresholds: {
        statements: 55,
        branches: 35,
        functions: 50,
        lines: 55,
      },
    },
  },
}

export default config
