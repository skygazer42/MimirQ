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
      reporter: ['text', 'text-summary', 'lcov', 'html'],
      reportsDirectory: './coverage',
      include: ['components/**/*.{ts,tsx}', 'app/**/*.{ts,tsx}', 'hooks/**/*.{ts,tsx}', 'lib/**/*.{ts,tsx}'],
      exclude: [
        '**/*.test.{ts,tsx}',
        '**/*.source.test.{ts,tsx}',
        '**/node_modules/**',
        '**/.next/**',
        '**/coverage/**',
      ],
      thresholds: {
        statements: 40,
        branches: 30,
        functions: 35,
        lines: 40,
      },
    },
  },
}

export default config
