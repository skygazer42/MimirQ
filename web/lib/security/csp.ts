type BuildCspHeaderValueOptions = {
  isDevelopment: boolean
  nonce: string
}

export function createCspNonce(): string {
  return Buffer.from(crypto.randomUUID()).toString('base64')
}

export function buildCspHeaderValue({
  isDevelopment,
  nonce,
}: BuildCspHeaderValueOptions): string {
  const directives = [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    [
      "script-src 'self'",
      `'nonce-${nonce}'`,
      "'strict-dynamic'",
      "'wasm-unsafe-eval'",
      isDevelopment ? "'unsafe-eval'" : null,
    ]
      .filter(Boolean)
      .join(' '),
    [
      "style-src 'self'",
      // NOTE:
      // - Inline `style=""` attributes cannot carry a nonce, so including a nonce here
      //   would cause browsers to ignore `'unsafe-inline'` and block those attributes.
      // - The app still relies on React inline styles in virtualized views and a few
      //   dynamic UI controls; keep `'unsafe-inline'` enabled until that is retired.
      "'unsafe-inline'",
    ]
      .filter(Boolean)
      .join(' '),
    "img-src 'self' data: blob: http: https:",
    "font-src 'self' data:",
    "connect-src 'self' http: https: ws: wss:",
    "worker-src 'self' blob:",
    "frame-src 'self' http: https:",
    "form-action 'self'",
    "manifest-src 'self'",
  ]

  if (!isDevelopment) directives.push('upgrade-insecure-requests')

  return directives.join('; ')
}
