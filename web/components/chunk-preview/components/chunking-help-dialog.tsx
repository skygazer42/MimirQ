/**
 * ChunkingHelpDialog - 切块预览帮助（参数建议 / 策略速查 / 快捷键）
 */
'use client'

import { ExternalLink, Keyboard, Scissors, Settings2, Sparkles } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'

export function ChunkingHelpDialog({
  open,
  onOpenChange,
}: Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
}>) {
  const t = useTranslations('ChunkPreview')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Scissors className="w-5 h-5 text-primary" />
            {t("help.title")}
          </DialogTitle>
          <DialogDescription>{t("help.description")}</DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[70vh] pr-4">
          <div className="space-y-6 text-sm">
            <section className="rounded-xl border border-border/60 bg-card/60 p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase ">
                <Sparkles className="w-3.5 h-3.5" />
                {t("help.workflow.title")}
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-muted-foreground">
                <div>{t("help.workflow.steps.parsing")}</div>
                <div>{t("help.workflow.steps.governance")}</div>
                <div>{t("help.workflow.steps.preview")}</div>
                <div>{t("help.workflow.steps.afterIngest")}</div>
              </div>
            </section>

            <section className="rounded-xl border border-border/60 bg-card/60 p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase ">
                <Settings2 className="w-3.5 h-3.5" />
                {t("help.parameters.title")}
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-muted-foreground">
                <div>
                  <span className="font-mono text-foreground/90">chunk_size</span>：{t("help.parameters.chunkSize")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">chunk_overlap</span>：{t("help.parameters.chunkOverlap")}
                </div>
                <div>{t("help.parameters.tip")}</div>
              </div>
            </section>

            <section className="rounded-xl border border-border/60 bg-card/60 p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase ">
                <Scissors className="w-3.5 h-3.5" />
                {t("help.strategies.title")}
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-muted-foreground">
                <div>
                  <span className="font-mono text-foreground/90">auto / langchain_recursive</span>：{t("help.strategies.auto")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">qa_pairs / qa_markdown</span>：{t("help.strategies.qa")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">laws_structured</span>：{t("help.strategies.laws")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">smart_code / diff_patch</span>：{t("help.strategies.code")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">separator</span>：{t("help.strategies.separator")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">langchain_token</span>：{t("help.strategies.token")}
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild variant="outline" size="sm" className="h-8 px-3 text-[11px]">
                  <a
                    href="https://github.com/skygazer42/MimirQ/blob/main/docs/guides/chunk_preview.md"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t("help.links.previewDocs")} <ExternalLink className="w-3.5 h-3.5 ml-1" />
                  </a>
                </Button>
                <Button asChild variant="outline" size="sm" className="h-8 px-3 text-[11px]">
                  <a
                    href="https://github.com/skygazer42/MimirQ/blob/main/docs/guides/chunk_strategies.md"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t("help.links.strategiesDocs")} <ExternalLink className="w-3.5 h-3.5 ml-1" />
                  </a>
                </Button>
              </div>
            </section>

            <section className="rounded-xl border border-border/60 bg-card/60 p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase ">
                <Keyboard className="w-3.5 h-3.5" />
                {t("help.shortcuts.title")}
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-muted-foreground">
                <div>
                  <span className="font-mono text-foreground/90">Ctrl/Cmd + Enter</span>：{t("help.shortcuts.forceRegenerate")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">Ctrl/Cmd + S</span>：{t("help.shortcuts.confirmIngest")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">↑/↓ 或 J/K</span>：{t("help.shortcuts.navigateList")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">/</span>：{t("help.shortcuts.focusSearch")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">Esc</span>：{t("help.shortcuts.clearLock")}
                </div>
                <div>
                  <span className="font-mono text-foreground/90">G / Shift+G（或 Home/End）</span>：{t("help.shortcuts.jumpEdges")}
                </div>
              </div>
            </section>
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
