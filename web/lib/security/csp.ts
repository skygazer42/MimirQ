type BuildCspHeaderValueOptions = {
  isDevelopment: boolean
  nonce: string
  upgradeInsecureRequests?: boolean
}

export function createCspNonce(): string {
  return Buffer.from(crypto.randomUUID()).toString('base64')
}

export function buildCspHeaderValue({
  isDevelopment,
  nonce,
  upgradeInsecureRequests,
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
    // Virtualized views use inline style attributes, which cannot carry a nonce.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: http: https:",
    "font-src 'self' data:",
    "connect-src 'self' http: https: ws: wss:",
    "worker-src 'self' blob:",
    "frame-src 'self' http: https:",
    "form-action 'self'",
    "manifest-src 'self'",
  ]

  if (upgradeInsecureRequests ?? !isDevelopment) {
    directives.push('upgrade-insecure-requests')
  }

  return directives.join('; ')
}
