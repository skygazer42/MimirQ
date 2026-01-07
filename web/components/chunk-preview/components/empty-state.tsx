/**
 * EmptyState - 空状态上传页面
 */
'use client'

import {
  Upload,
  BookOpen,
  ScanLine,
  Cpu,
  FileUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'

export function EmptyState() {
  const { isDragging, handleDragOver, handleDragLeave, handleDrop, addFiles, loadExample } = useChunkPreview()

  return (
    <div className="relative min-h-full w-full bg-[#FAFAFA] text-slate-900 font-sans flex flex-col items-center justify-center p-6 overflow-hidden selection:bg-indigo-100 selection:text-indigo-900">
      {/* 背景光晕 */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-gradient-to-br from-blue-100/40 to-indigo-100/40 blur-[120px] pointer-events-none mix-blend-multiply" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-gradient-to-tl from-purple-100/40 to-pink-100/40 blur-[120px] pointer-events-none mix-blend-multiply" />
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808008_1px,transparent_1px),linear-gradient(to_bottom,#80808008_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] pointer-events-none" />

      <div className="relative w-full max-w-4xl flex flex-col items-center z-10">
        {/* Header Section */}
        <div className="text-center mb-12 animate-in slide-in-from-bottom-8 fade-in duration-700">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 shadow-sm mb-6">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
            </span>
            <span className="text-xs font-semibold text-slate-600 tracking-wide uppercase">MimirQ RAG Engine</span>
          </div>

          <h1 className="text-5xl md:text-6xl font-bold tracking-tight text-slate-900 mb-6 bg-clip-text text-transparent bg-gradient-to-r from-slate-900 via-slate-700 to-slate-900">
            构建您的专属
            <br className="hidden md:block" />
            <span className="text-indigo-600">智能知识库</span>
          </h1>
          <p className="text-lg md:text-xl text-slate-500 max-w-2xl mx-auto leading-relaxed font-light">
            上传文档，体验可视化的智能切片与语义分析。
            <br />
            让 AI 精准理解每一份知识。
          </p>
        </div>

        {/* Main Upload Area */}
        <div
          className={cn(
            'w-full max-w-3xl bg-white rounded-3xl p-2 shadow-2xl shadow-indigo-100/50 border border-slate-100 transition-all duration-300 animate-in slide-in-from-bottom-10 fade-in duration-700 delay-100',
            isDragging ? 'scale-[1.01] ring-4 ring-indigo-100 border-indigo-300' : 'hover:border-indigo-200'
          )}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <div
            className={cn(
              'relative w-full h-64 border-2 border-dashed rounded-2xl flex flex-col items-center justify-center transition-colors duration-200 cursor-pointer overflow-hidden group',
              isDragging ? 'border-indigo-500 bg-indigo-50/30' : 'border-slate-200 hover:border-indigo-300 hover:bg-slate-50/50'
            )}
            onClick={() => document.getElementById('chunk-file-input')?.click()}
          >
            <input
              id="chunk-file-input"
              type="file"
              accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json"
              multiple
              className="hidden"
              onChange={(e) => {
                const files = e.target.files ? Array.from(e.target.files) : []
                if (files.length > 0) addFiles(files)
                e.target.value = ''
              }}
            />

            <div className="w-16 h-16 bg-white rounded-2xl shadow-sm border border-slate-100 flex items-center justify-center mb-6 group-hover:scale-110 group-hover:shadow-md transition-all duration-300">
              <FileUp
                className={cn('w-8 h-8 transition-colors duration-300', isDragging ? 'text-indigo-600' : 'text-slate-400 group-hover:text-indigo-500')}
              />
            </div>

            <div className="text-center space-y-2 z-10">
              <h3 className="text-lg font-semibold text-slate-700 group-hover:text-indigo-700 transition-colors">
                {isDragging ? '松开鼠标上传文件' : '点击或拖拽上传文档'}
              </h3>
              <p className="text-sm text-slate-400">支持 PDF, Markdown, TXT 文件夹批量上传</p>
            </div>

            {/* Decorative grid inside upload area */}
            <div className="absolute inset-0 opacity-[0.03] bg-[radial-gradient(#4f46e5_1px,transparent_1px)] [background-size:16px_16px] pointer-events-none" />
          </div>
        </div>

        {/* Quick Actions & Features */}
        <div className="w-full max-w-3xl mt-8 grid grid-cols-1 md:grid-cols-3 gap-4 animate-in slide-in-from-bottom-12 fade-in duration-700 delay-200">
          {/* Action Card: Example */}
          <div
            onClick={(e) => {
              e.stopPropagation()
              loadExample()
            }}
            className="group bg-white p-5 rounded-2xl border border-slate-100 shadow-sm hover:shadow-md hover:border-indigo-100 cursor-pointer transition-all duration-200 flex flex-col items-start gap-3"
          >
            <div className="p-2 rounded-lg bg-orange-50 text-orange-600 group-hover:bg-orange-100 transition-colors">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-slate-800 text-sm">试用示例文档</h4>
              <p className="text-xs text-slate-500 mt-1">无需上传，一键体验 RAG 流程</p>
            </div>
          </div>

          {/* Feature: Smart Chunking */}
          <div className="bg-white/60 p-5 rounded-2xl border border-slate-100 flex flex-col items-start gap-3">
            <div className="p-2 rounded-lg bg-blue-50 text-blue-600">
              <ScanLine className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-slate-800 text-sm">智能切片</h4>
              <p className="text-xs text-slate-500 mt-1">可视化调整 Chunk Size 与 Overlap</p>
            </div>
          </div>

          {/* Feature: Embedding */}
          <div className="bg-white/60 p-5 rounded-2xl border border-slate-100 flex flex-col items-start gap-3">
            <div className="p-2 rounded-lg bg-purple-50 text-purple-600">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-slate-800 text-sm">深度解析</h4>
              <p className="text-xs text-slate-500 mt-1">支持多格式解析与语义向量化</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
