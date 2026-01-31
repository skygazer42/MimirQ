export function toSourcePathPrefix(folderPath: string | null | undefined): string | undefined {
  const raw = String(folderPath || '').trim()
  if (!raw) return undefined

  // Normalize to a directory prefix so `startswith` doesn't match sibling folders
  // (e.g. "foo/" should not match "foobar/").
  return raw.endsWith('/') ? raw : `${raw}/`
}

