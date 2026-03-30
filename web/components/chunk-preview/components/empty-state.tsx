/**
 * EmptyState - 空状态上传页面
 */
'use client'

import { useState } from 'react'
import {
  Upload,
  BookOpen,
  HelpCircle,
  ScanLine,
  Cpu,
  FileUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { useTranslations } from 'next-intl'

export function EmptyState() {
  const { isDragging, handleDragOver, handleDragLeave, handleDrop, addFiles, loadExample } = useChunkPreview()
  const [helpOpen, setHelpOpen] = useState(false)
  const t = useTranslations('ChunkPreview')

  return (
    <div className="min-h-full w-full text-foreground font-sans flex items-center justify-center p-6 selection:bg-primary/20 selection:text-foreground">
      <div className="w-full max-w-4xl">
        <div className="mb-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-card border border-border/70 shadow-sm">
            <Upload className="w-3.5 h-3.5 text-primary" />
            <span className="text-xs font-semibold text-muted-foreground">{t('emptyState.badge')}</span>
          </div>
          <h1 className="mt-4 text-2xl font-bold  text-foreground">{t('emptyState.title')}</h1>
          <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
            {t('emptyState.description')}
          </p>
          <div className="mt-4 flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" className="h-8 px-3 text-[11px]" onClick={() => setHelpOpen(true)}>
              <HelpCircle className="w-3.5 h-3.5 mr-1.5" />
              {t('emptyState.help')}
            </Button>
          </div>
        </div>

        <div
          className={cn(
            'w-full bg-card rounded-3xl p-2 shadow-strong border border-border/70 transition-colors transition-shadow duration-200 motion-reduce:transition-none',
            isDragging ? 'ring-4 ring-primary/15 border-primary/25' : 'hover:border-primary/25'
          )}
          role="button"
          tabIndex={0}
          onClick={() => document.getElementById('chunk-file-input')?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              document.getElementById('chunk-file-input')?.click()
            }
          }}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <div
            className={cn(
              'relative w-full h-60 border-2 border-dashed rounded-2xl flex flex-col items-center justify-center transition-colors duration-200 motion-reduce:transition-none cursor-pointer overflow-hidden',
              isDragging ? 'border-primary bg-primary/10' : 'border-border hover:border-primary/40 hover:bg-primary/5'
            )}
          >
            <input
              id="chunk-file-input"
              type="file"
              accept={UPLOAD_ACCEPT}
              multiple
              className="hidden"
              onChange={(e) => {
                const files = e.target.files ? Array.from(e.target.files) : []
                if (files.length > 0) addFiles(files)
                e.target.value = ''
              }}
            />

            <div className="w-14 h-14 bg-card rounded-2xl shadow-sm border border-border flex items-center justify-center mb-5">
              <FileUp className={cn('w-7 h-7', isDragging ? 'text-primary' : 'text-muted-foreground')} />
            </div>

            <div className="text-center space-y-1.5">
              <h3 className="text-base font-semibold text-foreground/90">
                {isDragging ? t('emptyState.draggingTitle') : t('emptyState.idleTitle')}
              </h3>
              <p className="text-xs text-muted-foreground">{t('emptyState.uploadHint')}</p>
            </div>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-4">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              loadExample()
            }}
            className="group text-left bg-card p-5 rounded-2xl border border-border/70 shadow-sm hover:shadow-md hover:border-primary/25 cursor-pointer transition-colors transition-shadow duration-200 motion-reduce:transition-none focus-ring"
          >
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                <BookOpen className="w-5 h-5" />
              </div>
              <div>
                <div className="font-semibold text-foreground text-sm">{t('emptyState.exampleTitle')}</div>
                <div className="text-xs text-muted-foreground mt-1">{t('emptyState.exampleDescription')}</div>
              </div>
            </div>
          </button>

          <div className="bg-card p-5 rounded-2xl border border-border/70">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                <ScanLine className="w-5 h-5" />
              </div>
              <div>
                <div className="font-semibold text-foreground text-sm">{t('emptyState.previewTitle')}</div>
                <div className="text-xs text-muted-foreground mt-1">{t('emptyState.previewDescription')}</div>
              </div>
            </div>
          </div>

          <div className="bg-card p-5 rounded-2xl border border-border/70">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-lg bg-info/10 text-info">
                <Cpu className="w-5 h-5" />
              </div>
              <div>
                <div className="font-semibold text-foreground text-sm">{t('emptyState.tipsTitle')}</div>
                <div className="text-xs text-muted-foreground mt-1">{t('emptyState.tipsDescription')}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <ChunkingHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </div>
  )
}
