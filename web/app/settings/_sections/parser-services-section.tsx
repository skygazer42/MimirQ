'use client'

import { Input } from '@/components/ui/input'
import type {
  Etl4LlmConfig,
  MagicPDFConfig,
  MarkerConfig,
  PaddleVLConfig,
  TextInConfig,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { LayoutGrid, ScanLine, Wand2 } from 'lucide-react'
import {
  systemPageTokens,
  systemWorkbenchTokens,
} from '@/components/ui/system-page-tokens'

type ParserServicesSectionProps = {
  etl4llm: Etl4LlmConfig
  marker: MarkerConfig
  paddleVl: PaddleVLConfig
  textIn: TextInConfig
  magicPdf: MagicPDFConfig
  updateEtl4Llm: (patch: Partial<Etl4LlmConfig>) => void
  updateMarker: (patch: Partial<MarkerConfig>) => void
  updatePaddleVL: (patch: Partial<PaddleVLConfig>) => void
  updateTextIn: (patch: Partial<TextInConfig>) => void
  updateMagicPDF: (patch: Partial<MagicPDFConfig>) => void
}

const SECTION_TITLE =
  'mb-2 flex items-center gap-2 text-[13px] font-medium text-slate-950'
const CARD = cn(
  systemWorkbenchTokens.panel,
  'space-y-3 rounded-[16px] border border-slate-200/75 bg-card p-3 shadow-sm'
)
const GRID = 'grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3'
const FIELD_LABEL = 'text-[11px] font-medium text-muted-foreground'
const FIELD_HINT = systemPageTokens.subtle
const DENSE_INPUT = 'h-8 rounded-md border-border/70 bg-background text-[12px]'
const DENSE_SELECT =
  'w-full rounded-md border border-border/70 bg-background px-2.5 py-1.5 text-[12px]'

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
        'h-7 rounded-full border px-2.5 text-[11px] font-semibold leading-none',
        enabled
          ? accentClassName
          : 'border-border bg-muted text-muted-foreground'
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
  textIn,
  magicPdf,
  updateEtl4Llm,
  updateMarker,
  updatePaddleVL,
  updateTextIn,
  updateMagicPDF,
}: Readonly<ParserServicesSectionProps>) {
  return (
    <>
      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-success" />
          ETL4LLM 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>服务地址（API URL）</div>
              <Input
                className={DENSE_INPUT}
                value={etl4llm.api_url}
                onChange={(event) =>
                  updateEtl4Llm({ api_url: event.target.value })
                }
                placeholder="http://localhost:10001/v1/etl4llm/predict"
              />
              <div className={FIELD_HINT}>
                启用后会写入 `ETL4LLM_API_URL`，并用于解析器 `etl4llm`。
              </div>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>解析模式（mode）</div>
              <select
                value={etl4llm.mode}
                onChange={(event) =>
                  updateEtl4Llm({ mode: event.target.value })
                }
                className={DENSE_SELECT}
              >
                <option value="partition">版面结构（partition）</option>
                <option value="text">纯文本（text）</option>
              </select>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>超时（秒）</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={10}
                value={etl4llm.timeout_sec}
                onChange={(event) =>
                  updateEtl4Llm({
                    timeout_sec:
                      Number.parseInt(event.target.value || '0', 10) || 120,
                  })
                }
              />
            </div>

          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">
                强制 OCR
              </div>
              <div className={FIELD_HINT}>扫描件/图片型 PDF 建议开启</div>
            </div>
            <TogglePill
              enabled={etl4llm.force_ocr}
              onClick={() => updateEtl4Llm({ force_ocr: !etl4llm.force_ocr })}
              accentClassName="border-success/20 bg-success/10 text-success"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">
                提取图片
              </div>
              <div className={FIELD_HINT}>输出图片引用用于预览/入库</div>
            </div>
            <TogglePill
              enabled={etl4llm.extract_images}
              onClick={() =>
                updateEtl4Llm({ extract_images: !etl4llm.extract_images })
              }
              accentClassName="border-success/20 bg-success/10 text-success"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">
                公式识别
              </div>
              <div className={FIELD_HINT}>尽量保留公式/LaTeX 输出</div>
            </div>
            <TogglePill
              enabled={etl4llm.enable_formula}
              onClick={() =>
                updateEtl4Llm({ enable_formula: !etl4llm.enable_formula })
              }
              accentClassName="border-success/20 bg-success/10 text-success"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">
                过滤页眉页脚
              </div>
              <div className={FIELD_HINT}>减少检索噪音（若服务支持）</div>
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
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-success" />
          Marker 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>服务地址（API URL）</div>
              <Input
                className={DENSE_INPUT}
                value={marker.api_url}
                onChange={(event) =>
                  updateMarker({ api_url: event.target.value })
                }
                placeholder="http://localhost:2080/convert"
              />
              <div className={FIELD_HINT}>
                启用后会写入 `MARKER_API_URL`，并用于解析器 `marker`。
              </div>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>超时（秒）</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={30}
                value={marker.timeout_sec}
                onChange={(event) =>
                  updateMarker({
                    timeout_sec:
                      Number.parseInt(event.target.value || '0', 10) || 600,
                  })
                }
              />
              <div className={FIELD_HINT}>大文件/复杂 PDF 建议调大</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <ScanLine className="h-4 w-4 text-orange-600 dark:text-orange-300" />
          PaddleOCR-VL 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>服务地址（API URL）</div>
              <Input
                className={DENSE_INPUT}
                value={paddleVl.api_url}
                onChange={(event) =>
                  updatePaddleVL({ api_url: event.target.value })
                }
                placeholder="http://localhost:9030/convert"
              />
              <div className={FIELD_HINT}>
                启用后会写入 `PADDLE_VL_API_URL`，并用于解析器
                `paddle_vl`（别名：paddle-vl / paddleocr-vl）。
              </div>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>超时（秒）</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={30}
                value={paddleVl.timeout_sec}
                onChange={(event) =>
                  updatePaddleVL({
                    timeout_sec:
                      Number.parseInt(event.target.value || '0', 10) || 600,
                  })
                }
              />
              <div className={FIELD_HINT}>扫描件/OCR 场景建议调大</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-info dark:text-info" />
          TextIn xParse 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>API 地址</div>
              <Input
                className={DENSE_INPUT}
                value={textIn.api_url}
                onChange={(event) =>
                  updateTextIn({ api_url: event.target.value })
                }
                placeholder="https://api.textin.com/ai/service/v1/pdf_to_markdown"
              />
              <div className={FIELD_HINT}>
                启用后会写入 `TEXTIN_API_URL`，并用于解析器 `textin`。
              </div>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>超时（秒）</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={10}
                value={textIn.timeout_sec}
                onChange={(event) =>
                  updateTextIn({
                    timeout_sec:
                      Number.parseInt(event.target.value || '0', 10) || 180,
                  })
                }
              />
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>APP ID</div>
              <Input
                className={DENSE_INPUT}
                value={textIn.app_id}
                onChange={(event) =>
                  updateTextIn({ app_id: event.target.value })
                }
                placeholder="你的 TextIn APP ID"
              />
            </div>

            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>Secret Code</div>
              <Input
                className={DENSE_INPUT}
                type="password"
                value={textIn.secret_code}
                onChange={(event) =>
                  updateTextIn({ secret_code: event.target.value })
                }
                placeholder="你的 TextIn Secret Code"
              />
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>解析模式</div>
              <select
                value={textIn.parse_mode}
                onChange={(event) =>
                  updateTextIn({ parse_mode: event.target.value })
                }
                className={DENSE_SELECT}
              >
                <option value="auto">auto</option>
                <option value="scan">scan</option>
                <option value="parse">parse</option>
                <option value="lite">lite</option>
                <option value="vlm">vlm</option>
              </select>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>表格输出</div>
              <select
                value={textIn.table_flavor}
                onChange={(event) =>
                  updateTextIn({ table_flavor: event.target.value })
                }
                className={DENSE_SELECT}
              >
                <option value="html">html</option>
                <option value="markdown">markdown</option>
              </select>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>DPI</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={72}
                value={textIn.dpi}
                onChange={(event) =>
                  updateTextIn({
                    dpi: Number.parseInt(event.target.value || '0', 10) || 144,
                  })
                }
              />
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>页数限制（0=全部）</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={0}
                value={textIn.page_count}
                onChange={(event) =>
                  updateTextIn({
                    page_count:
                      Number.parseInt(event.target.value || '0', 10) || 0,
                  })
                }
              />
            </div>

          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">
                应用文档树
              </div>
              <div className={FIELD_HINT}>尽量保留标题层级 / 文档结构</div>
            </div>
            <TogglePill
              enabled={textIn.apply_document_tree}
              onClick={() =>
                updateTextIn({
                  apply_document_tree: !textIn.apply_document_tree,
                })
              }
              accentClassName="border-info/20 bg-info/10 text-info"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">
                Markdown 细节增强
              </div>
              <div className={FIELD_HINT}>返回更丰富的 Markdown 结构</div>
            </div>
            <TogglePill
              enabled={textIn.markdown_details}
              onClick={() =>
                updateTextIn({ markdown_details: !textIn.markdown_details })
              }
              accentClassName="border-info/20 bg-info/10 text-info"
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <Wand2 className="h-4 w-4 text-fuchsia-700 dark:text-fuchsia-300" />
          MagicPDF 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2">
              <div className={FIELD_LABEL}>解析方法（method）</div>
              <select
                value={magicPdf.method}
                onChange={(event) =>
                  updateMagicPDF({ method: event.target.value })
                }
                className={DENSE_SELECT}
              >
                <option value="auto">自动（auto）</option>
                <option value="txt">文本优先（txt）</option>
                <option value="ocr">OCR 优先（ocr）</option>
              </select>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>语言（lang，可选）</div>
              <Input
                className={DENSE_INPUT}
                value={magicPdf.lang}
                onChange={(event) =>
                  updateMagicPDF({ lang: event.target.value })
                }
                placeholder='例如"ch"'
              />
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>超时（秒）</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={30}
                value={magicPdf.timeout_sec}
                onChange={(event) =>
                  updateMagicPDF({
                    timeout_sec:
                      Number.parseInt(event.target.value || '0', 10) || 600,
                  })
                }
              />
            </div>

            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>模型目录（models-dir，可选）</div>
              <Input
                className={DENSE_INPUT}
                value={magicPdf.models_dir}
                onChange={(event) =>
                  updateMagicPDF({ models_dir: event.target.value })
                }
                placeholder="/opt/mimirq-model-cache/.../PDF-Extract-Kit-1.0/.../models"
              />
              <div className={FIELD_HINT}>
                留空时后端会自动查找 Docker 挂载的 MinerU / PDF-Extract-Kit 模型缓存。
              </div>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>设备模式</div>
              <select
                className={DENSE_SELECT}
                value={magicPdf.device_mode || 'cpu'}
                onChange={(event) =>
                  updateMagicPDF({ device_mode: event.target.value })
                }
              >
                <option value="cpu">CPU</option>
                <option value="cuda">CUDA / GPU</option>
              </select>
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">
                保留解析产物
              </div>
              <div className={FIELD_HINT}>
                默认会在入库流程完成后清理 `.magicpdf/` 目录
              </div>
            </div>
            <TogglePill
              enabled={magicPdf.keep_artifacts}
              onClick={() =>
                updateMagicPDF({ keep_artifacts: !magicPdf.keep_artifacts })
              }
              accentClassName="border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-500/30 dark:bg-fuchsia-500/10 dark:text-fuchsia-300"
            />
          </div>
        </div>
      </section>
    </>
  )
}
