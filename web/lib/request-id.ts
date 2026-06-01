let fallbackCounter = 0

function toHex(value: number): string {
  return value.toString(16).padStart(8, '0')
}

export function generateRequestId(): string {
  const cryptoLike = globalThis.crypto
  if (cryptoLike && typeof cryptoLike.randomUUID === 'function') {
    return cryptoLike.randomUUID()
  }
  if (cryptoLike && typeof cryptoLike.getRandomValues === 'function') {
    const values = new Uint32Array(2)
    cryptoLike.getRandomValues(values)
    return `${toHex(values[0])}-${toHex(values[1])}`
  }

  // Final fallback: deterministic monotonic correlation id when Web Crypto is unavailable.
  fallbackCounter = (fallbackCounter + 1) >>> 0
  return `${Date.now().toString(16)}-${toHex(fallbackCounter)}`
}
