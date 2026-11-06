/**
 * ESLint v9 flat config.
 *
 * Next.js 16 + eslint-config-next@16 exports flat-config arrays.
 * Compose them here so `pnpm -C web lint` works in fresh installs.
 */

const nextCoreWebVitals = require('eslint-config-next/core-web-vitals')
const prettier = require('eslint-config-prettier/flat')

module.exports = [
  // Ignore generated/build artifacts.
  {
    ignores: [
      '.next/**',
      '.next_*/**',
      '.next_build/**',
      'out/**',
      'dist/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      'node_modules/**',
      // Static/bundled assets (not source code).
      'public/**',
      // Generated OpenAPI artifacts (large; linting adds noise and slows CI/dev).
      'openapi.json',
      'types/openapi.ts',
    ],
  },
  ...nextCoreWebVitals,
  // Existing codebase uses state sync in effects in multiple places; keep lint signal focused.
  {
    rules: {
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/immutability': 'error',
      'react-hooks/preserve-manual-memoization': 'off',
      'react/function-component-definition': [
        'error',
        { namedComponents: 'function-declaration', unnamedComponents: 'arrow-function' },
      ],
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/consistent-type-definitions': ['error', 'type'],
    },
  },
  {
    files: ['**/*.d.ts'],
    rules: {
      // Ambient interfaces augment library declarations.
      '@typescript-eslint/consistent-type-definitions': 'off',
    },
  },
  prettier,
]
