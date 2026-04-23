'use client'

import Link from 'next/link'
import { BarChart3, Search, Shapes, Sparkles, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'

export function EmptyState({
  mode,
  onClearFilters,
}: Readonly<{
  mode: 'truly-empty' | 'filter-empty'
  onClearFilters?: () => void
}>) {
  if (mode === 'filter-empty') {
    return (
      <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/60 bg-background/75 px-6 py-16 text-center dark:bg-background/30">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-muted/50">
          <Search className="h-6 w-6 text-muted-foreground/60" />
        </div>
        <p className="text-sm font-semibold text-foreground">没有找到匹配的入库任务</p>
        <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">
          可以尝试调整搜索、状态或错误原因过滤条件。
        </p>
        <Button className="mt-4" variant="outline" onClick={onClearFilters}>
          清除过滤器
        </Button>
      </div>
    )
  }

  return (
    <div className="rounded-[2rem] border border-border/60 bg-[radial-gradient(circle_at_top,rgba(56,189,248,0.12),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.7),rgba(255,255,255,0.9))] px-6 py-10 text-left shadow-soft dark:bg-[radial-gradient(circle_at_top,rgba(14,165,233,0.16),transparent_32%),linear-gradient(180deg,rgba(14,14,16,0.92),rgba(12,12,15,0.96))]">
      <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-sky-500/20 bg-card/80 shadow-soft">
        <Shapes className="h-7 w-7 text-sky-500" />
      </div>
      <div className="mx-auto max-w-4xl text-center">
        <p className="text-lg font-semibold text-foreground">还没有生成数据盘点结果</p>
        <p className="mt-2 text-sm text-muted-foreground">这个页面的职责是做入库前摸底：看格式分布、文件大小分布、风险与待确认样本，而不是展示入库流程介绍。</p>
      </div>
      <div className="mx-auto mt-8 grid max-w-3xl gap-3 rounded-[1.5rem] border border-border/60 bg-card/70 p-4 md:grid-cols-3">
        {[
          ['01', '上传', '收集候选文件并锁定目标数据集'],
          ['02', '扫描', '生成处理效率、风险与敏感线索概览'],
          ['03', '结论', '输出可入库结论与人工复核清单'],
        ].map(([step, title, description]) => (
          <div key={String(title)} className="rounded-[1.25rem] border border-border/60 bg-background/75 px-4 py-4">
            <div className="font-code text-[11px] uppercase tracking-[0.2em] text-muted-foreground">{step}</div>
            <div className="mt-2 text-base font-semibold text-foreground">{title}</div>
            <div className="mt-2 text-xs leading-5 text-muted-foreground">{description}</div>
          </div>
        ))}
      </div>
      <div className="mt-8 grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,1fr)]">
        <div className="overflow-hidden rounded-[1.75rem] border border-border/60 bg-card/75 p-4 shadow-subtle">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">处理效率线框预览</div>
              <div className="mt-1 text-sm font-semibold text-foreground">数据盘点后将在此展示处理效率曲线</div>
            </div>
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/60 bg-background/80">
              <BarChart3 className="h-4 w-4 text-sky-500" />
            </div>
          </div>
          <div className="relative overflow-hidden rounded-[1.25rem] border border-border/50 bg-background/80 p-3">
            <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,transparent_0%,rgba(56,189,248,0.08)_50%,transparent_100%)] animate-pulse" />
            <svg viewBox="0 0 640 220" className="h-[220px] w-full" aria-hidden="true">
              <path d="M20 182 H620" fill="none" stroke="currentColor" strokeWidth="1" className="text-border/70" />
              <path d="M20 134 H620" fill="none" stroke="currentColor" strokeWidth="1" className="text-border/40" />
              <path d="M20 86 H620" fill="none" stroke="currentColor" strokeWidth="1" className="text-border/40" />
              <path d="M20 38 H620" fill="none" stroke="currentColor" strokeWidth="1" className="text-border/40" />
              <path
                d="M20 160 C84 150 96 118 148 108 C196 98 232 134 270 126 C318 116 354 54 398 66 C438 78 480 102 516 90 C554 78 586 36 620 46"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeDasharray="6 6"
                className="text-sky-500/85"
              />
              <path
                d="M20 172 C92 166 130 158 188 142 C246 126 302 120 354 112 C412 102 456 92 512 84 C562 77 592 70 620 66"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="text-emerald-500/70"
                opacity="0.5"
              />
            </svg>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-[1.75rem] border border-border/60 bg-card/75 p-4 shadow-subtle">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">预检盘点入口</div>
                <div className="mt-1 text-sm font-semibold text-foreground">先做盘点，再决定是否正式入库</div>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/60 bg-background/80">
                <ShieldCheck className="h-4 w-4 text-foreground" />
              </div>
            </div>
            <div className="space-y-3 rounded-[1.25rem] border border-dashed border-border/60 bg-background/70 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/60 bg-card/80">
                  <Sparkles className="h-4 w-4 text-foreground" />
                </div>
                <div>
                  <div className="font-code text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Audit First</div>
                  <div className="mt-1 text-sm font-semibold text-foreground">审计 OCR 候选、异常格式和敏感线索</div>
                </div>
              </div>
              <div className="text-xs leading-5 text-muted-foreground">
                拿到报告后，再决定哪些文件需要人工清洗或特殊处理。
              </div>
            </div>
          </div>

          <div className="rounded-[1.75rem] border border-border/60 bg-card/75 p-4 shadow-subtle">
            <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">风险热力图预留区</div>
            <div className="mt-3 grid h-[124px] grid-cols-3 gap-2 rounded-[1.25rem] border border-dashed border-border/60 bg-background/70 p-3">
              <div className="rounded-2xl border border-red-500/10 bg-red-500/5" />
              <div className="rounded-2xl border border-red-500/10 bg-red-500/5" />
              <div className="rounded-2xl border border-red-500/10 bg-red-500/5" />
              <div className="rounded-2xl border border-red-500/10 bg-red-500/5" />
              <div className="rounded-2xl border border-red-500/10 bg-red-500/5" />
              <div className="rounded-2xl border border-red-500/10 bg-red-500/5" />
            </div>
          </div>
        </div>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Button variant="outline" asChild>
            <Link href="/knowledge/ingestion?demo=1">加载虚拟数据</Link>
          </Button>
          <Button asChild>
            <Link href="/datasets">入库预检</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
