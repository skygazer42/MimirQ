type ExtractedZipFile = {
  file: File
  path: string
}

export function isZipFile(file: File): boolean {
  return file.name.toLowerCase().endsWith('.zip') || file.type === 'application/zip'
}

export async function extractZipFiles(zipFile: File): Promise<ExtractedZipFile[]> {
  const { default: JSZip } = await import('jszip')

  const zip = await JSZip.loadAsync(zipFile)
  const entries = Object.values(zip.files)

  const extracted: ExtractedZipFile[] = []
  for (const entry of entries) {
    if (entry.dir) continue
    const path = entry.name.replaceAll('\\', '/')
    if (path.startsWith('__MACOSX/')) continue
    if (path.endsWith('.DS_Store')) continue
    const baseName = path.split('/').findLast((segment) => segment !== '')
    if (baseName === undefined) continue

    const blob = await entry.async('blob')
    extracted.push({
      file: new File([blob], baseName, { type: blob.type }),
      path,
    })
  }

  return extracted
}
