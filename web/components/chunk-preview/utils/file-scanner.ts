/**
 * 文件扫描工具
 * 递归扫描拖放的文件和文件夹
 */

/**
 * 递归扫描 DataTransferItemList 中的所有文件（包括文件夹内的文件）
 * @param items DataTransferItemList from drag event
 * @returns Promise<File[]> 扫描到的所有文件
 */
export async function scanFiles(items: DataTransferItemList): Promise<File[]> {
  const files: File[] = []

  // 获取所有入口（文件或文件夹）
  const entries: FileSystemEntry[] = []
  for (const item of Array.from(items)) {
    const entry = item.webkitGetAsEntry()
    if (entry) entries.push(entry)
  }

  // 递归遍历函数
  const traverse = async (entry: FileSystemEntry) => {
    if (entry.isFile) {
      // 如果是文件，直接添加到结果
      const file = await new Promise<File>((resolve, reject) => {
        (entry as FileSystemFileEntry).file(resolve, reject)
      })
      files.push(file)
    } else if (entry.isDirectory) {
      // 如果是文件夹，递归读取子项
      const dirReader = (entry as FileSystemDirectoryEntry).createReader()
      const entries = await new Promise<FileSystemEntry[]>((resolve, reject) => {
        dirReader.readEntries(resolve, reject)
      })
      for (const child of entries) {
        await traverse(child)
      }
    }
  }

  // 遍历所有入口
  for (const entry of entries) {
    await traverse(entry)
  }

  return files
}
