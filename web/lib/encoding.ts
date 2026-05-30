export function encodeUtf8(value: string): Uint8Array {
  return new TextEncoder().encode(value)
}

export function decodeUtf8(value: Uint8Array): string {
  return new TextDecoder().decode(value)
}

function bytesToBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(bytes).toString('base64')
  }

  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCodePoint(byte)
  }
  return btoa(binary)
}

function base64ToBytes(base64: string): Uint8Array {
  if (typeof Buffer !== 'undefined') {
    return Uint8Array.from(Buffer.from(base64, 'base64'))
  }

  const binary = atob(base64)
  const out = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    out[i] = binary.codePointAt(i) ?? 0
  }
  return out
}

export function base64UrlEncode(bytes: Uint8Array): string {
  let encoded = bytesToBase64(bytes).replaceAll('+', '-').replaceAll('/', '_')
  while (encoded.endsWith('=')) {
    encoded = encoded.slice(0, -1)
  }
  return encoded
}

export function base64UrlDecodeToBytes(base64Url: string): Uint8Array {
  const raw = String(base64Url || '').trim()
  if (!raw) return new Uint8Array()

  let base64 = raw.replaceAll('-', '+').replaceAll('_', '/')
  const pad = base64.length % 4
  if (pad) base64 += '='.repeat(4 - pad)

  return base64ToBytes(base64)
}
