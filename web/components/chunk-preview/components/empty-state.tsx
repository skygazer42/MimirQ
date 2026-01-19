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
    <div className="relative min-h-full w-full bg-background text-foreground font-sans flex flex-col items-center justify-center p-6 overflow-hidden selection:bg-sky-500/20 selection:text-foreground">
      {/* 背景光晕 */}
      <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-gradient-to-br from-sky-500/15 to-sky-500/10 blur-[120px] pointer-events-none mix-blend-multiply" />
      <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-gradient-to-tl from-sky-500/15 to-blue-500/10 blur-[120px] pointer-events-none mix-blend-multiply" />
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808008_1px,transparent_1px),linear-gradient(to_bottom,#80808008_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] pointer-events-none" />

      <div className="relative w-full max-w-4xl flex flex-col items-center z-10">
        {/* Header Section */}
        <div className="text-center mb-12 animate-in slide-in-from-bottom-8 fade-in duration-700">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-card border border-border shadow-sm mb-6">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
            </span>
            <span className="text-xs font-semibold text-muted-foreground tracking-wide uppercase">MimirQ RAG Engine</span>
          </div>

          <h1 className="text-5xl md:text-6xl font-bold tracking-tight text-foreground mb-6 bg-clip-text text-transparent bg-gradient-to-r from-foreground via-foreground/70 to-foreground">
            构建您的专属
            <br className="hidden md:block" />
            <span className="text-sky-600 dark:text-sky-300">智能知识库</span>
          </h1>
          <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed font-light">
            上传文档，体验可视化的智能切片与语义分析。
            <br />
            让 AI 精准理解每一份知识。
          </p>
        </div>

        {/* Main Upload Area */}
        <div
          className={cn(
            'w-full max-w-3xl bg-card rounded-3xl p-2 shadow-2xl shadow-sky-500/10 dark:shadow-sky-500/5 border border-border transition-all duration-300 animate-in slide-in-from-bottom-10 fade-in duration-700 delay-100',
            isDragging ? 'scale-[1.01] ring-4 ring-sky-500/20 border-sky-300/60 dark:border-sky-500/40' : 'hover:border-sky-300/40'
          )}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <div
            className={cn(
              'relative w-full h-64 border-2 border-dashed rounded-2xl flex flex-col items-center justify-center transition-colors duration-200 cursor-pointer overflow-hidden group',
              isDragging ? 'border-sky-500 bg-sky-500/10 dark:bg-sky-500/20' : 'border-border hover:border-sky-300/60 dark:hover:border-sky-500/40 hover:bg-sky-500/10 dark:hover:bg-sky-500/20'
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

            <div className="w-16 h-16 bg-card rounded-2xl shadow-sm border border-border flex items-center justify-center mb-6 group-hover:scale-110 group-hover:shadow-md transition-all duration-300">
              <FileUp
                className={cn('w-8 h-8 transition-colors duration-300', isDragging ? 'text-sky-600 dark:text-sky-300' : 'text-muted-foreground group-hover:text-sky-600 dark:group-hover:text-sky-300')}
              />
            </div>

            <div className="text-center space-y-2 z-10">
              <h3 className="text-lg font-semibold text-foreground/80 group-hover:text-sky-600 dark:group-hover:text-sky-300 transition-colors">
                {isDragging ? '松开鼠标上传文件' : '点击或拖拽上传文档'}
              </h3>
              <p className="text-sm text-muted-foreground">支持 PDF, Markdown, TXT 文件夹批量上传</p>
            </div>

            {/* Decorative grid inside upload area */}
            <div className="absolute inset-0 opacity-[0.03] bg-[radial-gradient(#0ea5e9_1px,transparent_1px)] [background-size:16px_16px] pointer-events-none" />
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
            className="group bg-card p-5 rounded-2xl border border-border shadow-sm hover:shadow-md hover:border-sky-300/40 cursor-pointer transition-all duration-200 flex flex-col items-start gap-3"
          >
            <div className="p-2 rounded-lg bg-sky-500/10 dark:bg-sky-500/20 text-sky-600 dark:text-sky-300 group-hover:bg-sky-500/20 transition-colors">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-foreground text-sm">试用示例文档</h4>
              <p className="text-xs text-muted-foreground mt-1">无需上传，一键体验 RAG 流程</p>
            </div>
          </div>

          {/* Feature: Smart Chunking */}
          <div className="bg-card/60 p-5 rounded-2xl border border-border flex flex-col items-start gap-3">
            <div className="p-2 rounded-lg bg-sky-500/10 dark:bg-sky-500/20 text-sky-600 dark:text-sky-300">
              <ScanLine className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-foreground text-sm">智能切片</h4>
              <p className="text-xs text-muted-foreground mt-1">可视化调整 Chunk Size 与 Overlap</p>
            </div>
          </div>

          {/* Feature: Embedding */}
          <div className="bg-card/60 p-5 rounded-2xl border border-border flex flex-col items-start gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10 dark:bg-blue-500/20 text-blue-600 dark:text-blue-300">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <h4 className="font-semibold text-foreground text-sm">深度解析</h4>
              <p className="text-xs text-muted-foreground mt-1">支持多格式解析与语义向量化</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
