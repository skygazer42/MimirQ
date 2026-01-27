export function generateRequestId(): string {
  const cryptoLike = (globalThis as any)?.crypto
  if (cryptoLike && typeof cryptoLike.randomUUID === 'function') {
    return cryptoLike.randomUUID()
  }
  // Fallback: not globally unique, but good enough for correlation in logs.
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`
}

