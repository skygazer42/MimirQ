export async function scanFiles(items: DataTransferItemList): Promise<File[]> {
  const sources = Array.from(items, (item) => item.webkitGetAsEntry?.() ?? item.getAsFile())
  const files: File[] = []

  async function readEntry(entry: FileSystemEntry) {
    if (entry.isFile) {
      const fileEntry = entry as FileSystemFileEntry
      const file = await new Promise<File>((resolve, reject) => {
        fileEntry.file(resolve, reject)
      })
      files.push(file)
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader()
      for (;;) {
        const children = await new Promise<FileSystemEntry[]>((resolve, reject) => {
          reader.readEntries(resolve, reject)
        })
        if (children.length === 0) break
        for (const child of children) {
          await readEntry(child)
        }
      }
    }
  }

  for (const source of sources) {
    if (source === null) continue
    if (source instanceof File) files.push(source)
    else await readEntry(source)
  }

  return files
}
