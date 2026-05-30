let fallbackCounter = 0

function fillRandomBytes(bytes: Uint8Array): Uint8Array {
  if (globalThis.crypto?.getRandomValues) {
    return globalThis.crypto.getRandomValues(bytes)
  }

  fallbackCounter = (fallbackCounter + 1) >>> 0
  const seed = `${Date.now()}:${fallbackCounter}:${globalThis.performance?.now?.() ?? 0}`
  for (let index = 0; index < bytes.length; index += 1) {
    const code = seed.charCodeAt(index % seed.length) || 0
    bytes[index] = (code + index * 31 + fallbackCounter) & 0xff
  }
  return bytes
}

function randomUint32(): number {
  if (globalThis.crypto?.getRandomValues) {
    return globalThis.crypto.getRandomValues(new Uint32Array(1))[0] ?? 0
  }
  const bytes = fillRandomBytes(new Uint8Array(4))
  return new DataView(bytes.buffer).getUint32(0)
}

export function randomBase36Id(length: number): string {
  const size = Math.max(1, Math.ceil(length))
  const bytes = fillRandomBytes(new Uint8Array(size))
  return Array.from(bytes, (byte) => (byte % 36).toString(36)).join('')
}

export function randomIntInclusive(minValue: number, maxValue: number): number {
  const min = Math.max(0, Math.floor(minValue))
  const max = Math.max(min, Math.floor(maxValue))
  const range = max - min + 1
  return min + (randomUint32() % range)
}
