'use client'

/**
 * 已解析文件的共享状态管理
 * 用于在 /parsing 和 /chunk-preview 之间共享数据
 */
import { useState, useEffect, useCallback } from 'react'

export interface ParsedFileData {
  id: string
  filename: string
  fileType: string
  fileSize: number
  markdownContent: string
  parsedAt: string
  parser: string
}

const STORAGE_KEY = 'mimirq_parsed_files'

// 从 localStorage 读取
const loadFromStorage = (): ParsedFileData[] => {
  if (typeof window === 'undefined') return []
  try {
    const data = localStorage.getItem(STORAGE_KEY)
    return data ? JSON.parse(data) : []
  } catch {
    return []
  }
}

// 保存到 localStorage
const saveToStorage = (files: ParsedFileData[]) => {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(files))
  } catch (e) {
    console.error('Failed to save parsed files:', e)
  }
}

export function useParsedFiles() {
  const [files, setFiles] = useState<ParsedFileData[]>([])
  const [isLoaded, setIsLoaded] = useState(false)

  // 初始化时从 localStorage 加载
  useEffect(() => {
    setFiles(loadFromStorage())
    setIsLoaded(true)
  }, [])

  // 添加已解析的文件
  const addParsedFile = useCallback((file: Omit<ParsedFileData, 'id' | 'parsedAt'>) => {
    const newFile: ParsedFileData = {
      ...file,
      id: Math.random().toString(36).substring(2, 15),
      parsedAt: new Date().toISOString(),
    }

    setFiles((prev) => {
      const updated = [...prev, newFile]
      saveToStorage(updated)
      return updated
    })

    return newFile.id
  }, [])

  // 获取单个文件
  const getFile = useCallback((id: string) => {
    return files.find((f) => f.id === id) || null
  }, [files])

  // 删除文件
  const removeFile = useCallback((id: string) => {
    setFiles((prev) => {
      const updated = prev.filter((f) => f.id !== id)
      saveToStorage(updated)
      return updated
    })
  }, [])

  // 清空所有
  const clearAll = useCallback(() => {
    setFiles([])
    saveToStorage([])
  }, [])

  return {
    files,
    isLoaded,
    addParsedFile,
    getFile,
    removeFile,
    clearAll,
  }
}
