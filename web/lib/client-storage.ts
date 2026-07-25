export type ClientStorageKind = 'local' | 'session'

export function getClientStorage(kind: ClientStorageKind = 'local'): Storage | null {
  if (globalThis.window === undefined) return null

  try {
    return kind === 'local' ? globalThis.window.localStorage : globalThis.window.sessionStorage
  } catch {
    return null
  }
}

export function readClientStorage(key: string, kind: ClientStorageKind = 'local'): string | null {
  try {
    const storage = getClientStorage(kind)
    if (!storage) return null
    return storage.getItem(key)
  } catch {
    return null
  }
}

export function writeClientStorage(key: string, value: string, kind: ClientStorageKind = 'local'): boolean {
  try {
    const storage = getClientStorage(kind)
    if (!storage) return false
    storage.setItem(key, value)
    return true
  } catch {
    return false
  }
}

export function removeClientStorage(key: string, kind: ClientStorageKind = 'local'): boolean {
  try {
    const storage = getClientStorage(kind)
    if (!storage) return false
    storage.removeItem(key)
    return true
  } catch {
    return false
  }
}
