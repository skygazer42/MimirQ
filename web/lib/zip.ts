export interface ExtractedZipFile {
  file: File
  path: string
}

const isZipPath = (name: string) => name.toLowerCase().endsWith('.zip')

export const isZipFile = (file: File) => isZipPath(file.name) || file.type === 'application/zip'

export async function extractZipFiles(zipFile: File): Promise<ExtractedZipFile[]> {
  const { default: JSZip } = await import('jszip')

  const zip = await JSZip.loadAsync(zipFile)
  const entries = Object.values(zip.files)

  const extracted: ExtractedZipFile[] = []
  for (const entry of entries) {
    if (!entry || entry.dir) continue
    const path = entry.name.replaceAll("\\", '/')
    if (!path || path.startsWith('__MACOSX/')) continue
    if (path.endsWith('.DS_Store')) continue

    const blob = await entry.async('blob')
    const baseName = path.split('/').findLast(Boolean) || path
    extracted.push({
      file: new File([blob], baseName, { type: blob.type }),
      path,
    })
  }

  return extracted
}
