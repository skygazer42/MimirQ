'use client'

/**
 * 切块预览页面
 * 使用后端 RecursiveCharacterTextSplitter 进行真实切块预览
 */

import { Navbar } from '@/components/navbar'
import { ChunkPreview } from '@/components/chunk-preview'
import { Scissors } from 'lucide-react'

export default function ChunkPreviewPage() {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />
      <main className="flex-1 overflow-hidden flex flex-col">
        {/* 头部 */}
        <div className="bg-white border-b px-8 py-6 flex-shrink-0">
          <div className="max-w-7xl mx-auto">
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
              <Scissors className="h-7 w-7 text-blue-600" />
              切块预览
            </h1>
            <p className="text-gray-600 mt-1">
              上传文档并调整切块参数，实时预览切块效果。使用与入库相同的 RecursiveCharacterTextSplitter 算法。
            </p>
          </div>
        </div>

        {/* 切块预览组件 */}
        <div className="flex-1 overflow-hidden">
          <ChunkPreview
            onConfirm={(params) => {
              console.log('用户确认参数:', params)
              // 可以跳转到上传页面或保存配置
            }}
          />
        </div>
      </main>
    </div>
  )
}
