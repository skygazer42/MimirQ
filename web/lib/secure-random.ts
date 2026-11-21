export function randomBase36Id(length: number): string {
  const size = Math.max(1, Math.ceil(length))
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(size))
  return Array.from(bytes, (byte) => (byte % 36).toString(36)).join('')
}

export function randomIntInclusive(minValue: number, maxValue: number): number {
  const min = Math.max(0, Math.floor(minValue))
  const max = Math.max(min, Math.floor(maxValue))
  const range = max - min + 1
  const [value] = globalThis.crypto.getRandomValues(new Uint32Array(1))
  return min + (value % range)
}
