/**
 * ChunkingHelpDialog - 切块预览帮助（参数建议 / 策略速查 / 快捷键）
 */
'use client'

import { ExternalLink, Keyboard, Scissors, Settings2, Sparkles } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'

export function ChunkingHelpDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Scissors className="w-5 h-5 text-primary" />
            切块指南
          </DialogTitle>
          <DialogDescription>快速理解“怎么切、怎么调、怎么验”。</DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[70vh] pr-4">
          <div className="space-y-6 text-sm">
            <section className="rounded-xl border border-border/60 bg-card/60 p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase ">
                <Sparkles className="w-3.5 h-3.5" />
                推荐工作流
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-muted-foreground">
                <div>1) 解析（/parsing）：先确认 PDF/Office 的结构提取质量</div>
                <div>2) 治理（/data-governance）：清洗去噪、去页眉页脚、规范化文本</div>
                <div>3) 切块预览（/chunk-preview）：调策略/参数，检查数量分布与原文定位</div>
                <div>4) 入库后：回到对话页做检索/引用验证（必要时配合评测）</div>
              </div>
            </section>

            <section className="rounded-xl border border-border/60 bg-card/60 p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase ">
                <Settings2 className="w-3.5 h-3.5" />
                参数建议（经验值）
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-muted-foreground">
                <div>
                  <span className="font-mono text-foreground/90">chunk_size</span>：
                  文本模式常见 600-1500 chars；token 模式常见 256-1024 tokens（视模型上下文与检索预算）。
                </div>
                <div>
                  <span className="font-mono text-foreground/90">chunk_overlap</span>：
                  常见为 chunk_size 的 10-25%（过小易断语义；过大浪费向量与检索预算）。
                </div>
                <div>
                  建议优先保证“结构正确”（标题/问答/条款不被拆散），再调长度分布与 overlap。
                </div>
              </div>
            </section>

            <section className="rounded-xl border border-border/60 bg-card/60 p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase ">
                <Scissors className="w-3.5 h-3.5" />
                策略速查
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-muted-foreground">
                <div>
                  <span className="font-mono text-foreground/90">auto / langchain_recursive</span>：通用长文、说明文、制度。
                </div>
                <div>
                  <span className="font-mono text-foreground/90">qa_pairs / qa_markdown</span>：FAQ/Q&A，目标是不拆散问答对。
                </div>
                <div>
                  <span className="font-mono text-foreground/90">laws_structured</span>：合同/条款类文本，尽量按条款结构切分。
                </div>
                <div>
                  <span className="font-mono text-foreground/90">smart_code / diff_patch</span>：代码/配置/变更，尽量沿语法/块边界切分。
                </div>
                <div>
                  <span className="font-mono text-foreground/90">separator</span>：按段落/标题/--- 等结构边界切分（不使用 overlap）。
                </div>
                <div>
                  <span className="font-mono text-foreground/90">langchain_token</span>：严格按 token 预算切块（仍建议做预览检查）。
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild variant="outline" size="sm" className="h-8 px-3 text-[11px]">
                  <a
                    href="https://github.com/skygazer42/MimirQ/blob/main/docs/guides/chunk_preview.md"
                    target="_blank"
                    rel="noreferrer"
                  >
                    查看详细文档：切块预览 <ExternalLink className="w-3.5 h-3.5 ml-1" />
                  </a>
                </Button>
                <Button asChild variant="outline" size="sm" className="h-8 px-3 text-[11px]">
                  <a
                    href="https://github.com/skygazer42/MimirQ/blob/main/docs/guides/chunk_strategies.md"
                    target="_blank"
                    rel="noreferrer"
                  >
                    查看详细文档：策略速查 <ExternalLink className="w-3.5 h-3.5 ml-1" />
                  </a>
                </Button>
              </div>
            </section>

            <section className="rounded-xl border border-border/60 bg-card/60 p-4">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase ">
                <Keyboard className="w-3.5 h-3.5" />
                快捷键
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-muted-foreground">
                <div>
                  <span className="font-mono text-foreground/90">Ctrl/Cmd + Enter</span>：强制重新生成预览（忽略缓存）
                </div>
                <div>
                  <span className="font-mono text-foreground/90">Ctrl/Cmd + S</span>：确认入库（提交 chunks）
                </div>
                <div>
                  <span className="font-mono text-foreground/90">↑/↓ 或 J/K</span>：切片列表上一条/下一条（点击锁定后生效）
                </div>
                <div>
                  <span className="font-mono text-foreground/90">/</span>：在列表区域快速聚焦搜索
                </div>
                <div>
                  <span className="font-mono text-foreground/90">Esc</span>：取消锁定
                </div>
                <div>
                  <span className="font-mono text-foreground/90">G / Shift+G（或 Home/End）</span>：跳转首/尾
                </div>
              </div>
            </section>
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}

