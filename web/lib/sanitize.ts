export function sanitizeFilename(name: string): string {
  return String(name || '')
    .trim()
    .replace(/[^a-zA-Z0-9_\-.\u4e00-\u9fff]/g, '_')
    .replace(/_{2,}/g, '_')
}
