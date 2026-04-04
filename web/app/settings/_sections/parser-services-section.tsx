'use client'

import { Input } from '@/components/ui/input'
import type { Etl4LlmConfig, MagicPDFConfig, MarkerConfig, PaddleVLConfig } from '@/lib/api'
import { cn } from '@/lib/utils'
import { FileCode, LayoutGrid, ScanLine, Wand2 } from 'lucide-react'

type ParserServicesSectionProps = {
  etl4llm: Etl4LlmConfig
  marker: MarkerConfig
  paddleVl: PaddleVLConfig
  magicPdf: MagicPDFConfig
  updateEtl4Llm: (patch: Partial<Etl4LlmConfig>) => void
  updateMarker: (patch: Partial<MarkerConfig>) => void
  updatePaddleVL: (patch: Partial<PaddleVLConfig>) => void
  updateMagicPDF: (patch: Partial<MagicPDFConfig>) => void
}

function TogglePill({
  enabled,
  onClick,
  accentClassName,
}: Readonly<{
  enabled: boolean
  onClick: () => void
  accentClassName: string
}>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-full border px-3 py-1.5 text-xs font-medium',
        enabled ? accentClassName : 'border-border bg-muted text-muted-foreground'
      )}
    >
      {enabled ? '已开启' : '已关闭'}
    </button>
  )
}

export function ParserServicesSection({
  etl4llm,
  marker,
  paddleVl,
  magicPdf,
  updateEtl4Llm,
  updateMarker,
  updatePaddleVL,
  updateMagicPDF,
}: Readonly<ParserServicesSectionProps>) {
  return (
    <>
      <section>
        <h2 className="mb-6 flex items-center gap-2 text-lg font-semibold text-foreground">
          <LayoutGrid className="h-5 w-5 text-success" />
          ETL4LLM 配置
        </h2>

        <div className="space-y-4 rounded-2xl border border-border bg-card p-6 shadow-sm">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2 lg:col-span-2">
              <div className="text-sm font-medium text-foreground/80">API URL</div>
              <Input
                value={etl4llm.api_url}
                onChange={(event) => updateEtl4Llm({ api_url: event.target.value })}
                placeholder="http://localhost:10001/v1/etl4llm/predict"
              />
              <div className="text-xs text-muted-foreground">
                启用后会写入 `ETL4LLM_API_URL`，并用于解析器 `etl4llm`。
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">模式</div>
              <select
                value={etl4llm.mode}
                onChange={(event) => updateEtl4Llm({ mode: event.target.value })}
                className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm"
              >
                <option value="partition">partition（版面/结构）</option>
                <option value="text">text（纯文本）</option>
              </select>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">超时（秒）</div>
              <Input
                type="number"
                min={10}
                value={etl4llm.timeout_sec}
                onChange={(event) =>
                  updateEtl4Llm({
                    timeout_sec: Number.parseInt(event.target.value || '0', 10) || 120,
                  })
                }
              />
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-border pt-4">
            <div>
              <div className="text-sm font-medium text-foreground/80">强制 OCR</div>
              <div className="mt-0.5 text-xs text-muted-foreground">扫描件/图片型 PDF 建议开启</div>
            </div>
            <TogglePill
              enabled={etl4llm.force_ocr}
              onClick={() => updateEtl4Llm({ force_ocr: !etl4llm.force_ocr })}
              accentClassName="border-success/20 bg-success/10 text-success"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border pt-4">
            <div>
              <div className="text-sm font-medium text-foreground/80">提取图片</div>
              <div className="mt-0.5 text-xs text-muted-foreground">输出图片引用用于预览/入库</div>
            </div>
            <TogglePill
              enabled={etl4llm.extract_images}
              onClick={() => updateEtl4Llm({ extract_images: !etl4llm.extract_images })}
              accentClassName="border-success/20 bg-success/10 text-success"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border pt-4">
            <div>
              <div className="text-sm font-medium text-foreground/80">公式识别</div>
              <div className="mt-0.5 text-xs text-muted-foreground">尽量保留公式/LaTeX 输出</div>
            </div>
            <TogglePill
              enabled={etl4llm.enable_formula}
              onClick={() => updateEtl4Llm({ enable_formula: !etl4llm.enable_formula })}
              accentClassName="border-success/20 bg-success/10 text-success"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border pt-4">
            <div>
              <div className="text-sm font-medium text-foreground/80">过滤页眉页脚</div>
              <div className="mt-0.5 text-xs text-muted-foreground">减少检索噪音（若服务支持）</div>
            </div>
            <TogglePill
              enabled={etl4llm.filter_page_header_footer}
              onClick={() =>
                updateEtl4Llm({
                  filter_page_header_footer: !etl4llm.filter_page_header_footer,
                })
              }
              accentClassName="border-success/20 bg-success/10 text-success"
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className="mb-6 flex items-center gap-2 text-lg font-semibold text-foreground">
          <LayoutGrid className="h-5 w-5 text-success" />
          Marker 配置
        </h2>

        <div className="space-y-4 rounded-2xl border border-border bg-card p-6 shadow-sm">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2 lg:col-span-2">
              <div className="text-sm font-medium text-foreground/80">API URL</div>
              <Input
                value={marker.api_url}
                onChange={(event) => updateMarker({ api_url: event.target.value })}
                placeholder="http://localhost:2080/convert"
              />
              <div className="text-xs text-muted-foreground">
                启用后会写入 `MARKER_API_URL`，并用于解析器 `marker`。
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">超时（秒）</div>
              <Input
                type="number"
                min={30}
                value={marker.timeout_sec}
                onChange={(event) =>
                  updateMarker({
                    timeout_sec: Number.parseInt(event.target.value || '0', 10) || 600,
                  })
                }
              />
              <div className="text-xs text-muted-foreground">大文件/复杂 PDF 建议调大</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className="mb-6 flex items-center gap-2 text-lg font-semibold text-foreground">
          <ScanLine className="h-5 w-5 text-orange-600 dark:text-orange-300" />
          PaddleOCR-VL 配置
        </h2>

        <div className="space-y-4 rounded-2xl border border-border bg-card p-6 shadow-sm">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2 lg:col-span-2">
              <div className="text-sm font-medium text-foreground/80">API URL</div>
              <Input
                value={paddleVl.api_url}
                onChange={(event) => updatePaddleVL({ api_url: event.target.value })}
                placeholder="http://localhost:9030/convert"
              />
              <div className="text-xs text-muted-foreground">
                启用后会写入 `PADDLE_VL_API_URL`，并用于解析器 `paddle_vl`（别名：paddle-vl / paddleocr-vl）。
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">超时（秒）</div>
              <Input
                type="number"
                min={30}
                value={paddleVl.timeout_sec}
                onChange={(event) =>
                  updatePaddleVL({
                    timeout_sec: Number.parseInt(event.target.value || '0', 10) || 600,
                  })
                }
              />
              <div className="text-xs text-muted-foreground">扫描件/OCR 场景建议调大</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className="mb-6 flex items-center gap-2 text-lg font-semibold text-foreground">
          <Wand2 className="h-5 w-5 text-fuchsia-700 dark:text-fuchsia-300" />
          MagicPDF 配置
        </h2>

        <div className="space-y-4 rounded-2xl border border-border bg-card p-6 shadow-sm">
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">解析方法</div>
              <select
                value={magicPdf.method}
                onChange={(event) => updateMagicPDF({ method: event.target.value })}
                className="w-full rounded-lg border border-border bg-card px-3 py-2 text-sm"
              >
                <option value="auto">auto（自动）</option>
                <option value="txt">txt（文本优先）</option>
                <option value="ocr">ocr（OCR 优先）</option>
              </select>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">语言（可选）</div>
              <Input
                value={magicPdf.lang}
                onChange={(event) => updateMagicPDF({ lang: event.target.value })}
                placeholder='例如 "ch"'
              />
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">超时（秒）</div>
              <Input
                type="number"
                min={30}
                value={magicPdf.timeout_sec}
                onChange={(event) =>
                  updateMagicPDF({
                    timeout_sec: Number.parseInt(event.target.value || '0', 10) || 600,
                  })
                }
              />
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-border pt-4">
            <div>
              <div className="text-sm font-medium text-foreground/80">保留解析产物</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                默认会在入库流程完成后清理 `.magicpdf/` 目录
              </div>
            </div>
            <TogglePill
              enabled={magicPdf.keep_artifacts}
              onClick={() => updateMagicPDF({ keep_artifacts: !magicPdf.keep_artifacts })}
              accentClassName="border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-500/30 dark:bg-fuchsia-500/10 dark:text-fuchsia-300"
            />
          </div>
        </div>
      </section>
    </>
  )
}
