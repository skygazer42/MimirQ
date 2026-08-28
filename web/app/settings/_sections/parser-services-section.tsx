'use client'

import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Input } from '@/components/ui/input'
import type {
  Etl4LlmConfig,
  MagicPDFConfig,
  MarkerConfig,
  MinerUConfig,
  PaddleVLConfig,
  SystemSettings,
  TextInConfig,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { LayoutGrid, ScanLine, Wand2 } from 'lucide-react'
import {
  systemPageTokens,
  systemWorkbenchTokens,
} from '@/components/ui/system-page-tokens'

type DoclingConfig = NonNullable<SystemSettings['docling']>

type ParserServicesSectionProps = {
  mineru: MinerUConfig
  etl4llm: Etl4LlmConfig
  marker: MarkerConfig
  docling: DoclingConfig
  paddleVl: PaddleVLConfig
  textIn: TextInConfig
  magicPdf: MagicPDFConfig
  updateMinerU: (patch: Partial<MinerUConfig>) => void
  updateEtl4Llm: (patch: Partial<Etl4LlmConfig>) => void
  updateMarker: (patch: Partial<MarkerConfig>) => void
  updateDocling: (patch: Partial<DoclingConfig>) => void
  updatePaddleVL: (patch: Partial<PaddleVLConfig>) => void
  updateTextIn: (patch: Partial<TextInConfig>) => void
  updateMagicPDF: (patch: Partial<MagicPDFConfig>) => void
}

const SECTION_TITLE =
  'mb-2 flex items-center gap-2 text-[13px] font-semibold text-foreground'
const CARD = cn(
  systemWorkbenchTokens.panel,
  'space-y-3 rounded-xl border border-info/15 bg-info/[0.025] p-3 shadow-none'
)
const GRID = 'grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3'
const FIELD_LABEL = 'text-[11px] font-semibold text-muted-foreground'
const FIELD_HINT = systemPageTokens.subtle
const DENSE_INPUT = 'h-8 rounded-md border-info/15 bg-info/[0.025] text-[12px]'
const DENSE_SELECT =
  'w-full rounded-md border border-info/15 bg-info/[0.025] px-2.5 py-1.5 text-[12px]'

function TogglePill({
  enabled,
  onClick,
  label,
}: Readonly<{
  enabled: boolean
  onClick: () => void
  label: string
}>) {
  return (
    <SettingsSwitch
      checked={enabled}
      onCheckedChange={onClick}
      aria-label={label}
      className="shrink-0"
    />
  )
}

export function ParserServicesSection({
  mineru,
  etl4llm,
  marker,
  docling,
  paddleVl,
  textIn,
  magicPdf,
  updateMinerU,
  updateEtl4Llm,
  updateMarker,
  updateDocling,
  updatePaddleVL,
  updateTextIn,
  updateMagicPDF,
}: Readonly<ParserServicesSectionProps>) {
  const mineruBackend = mineru.backend || 'pipeline'

  return (
    <>
      <section>
        <h2 className={SECTION_TITLE}>
          <ScanLine className="h-4 w-4 text-info" />
          MinerU 配置
        </h2>

        <div className={CARD}>
          <div className="rounded-[14px] border border-info/20 bg-info/[0.06] px-3 py-2.5">
            <div className="text-[12px] font-semibold text-foreground">本地部署优先</div>
            <div className={cn(FIELD_HINT, 'mt-0.5')}>
              配置本地 MinerU 服务地址后，解析会走本地 ZIP 模式；未配置时再使用在线 API 令牌
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(220px,1fr)]">
            <div className="space-y-3">
              <div className="space-y-2">
                <div className={FIELD_LABEL}>本地 MinerU API 地址</div>
                <Input
                  className={DENSE_INPUT}
                  value={mineru.local_server_url}
                  onChange={(event) =>
                    updateMinerU({ local_server_url: event.target.value })
                  }
                  placeholder="http://localhost:30001"
                />
                <div className={FIELD_HINT}>
                  本地部署入口，解析会优先发送到这个服务
                </div>
              </div>

              <details
                open={mineruBackend === 'vlm-http-client'}
                className="group rounded-[14px] border border-dashed border-border/70 bg-muted/35 px-3 py-2"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[12px] font-semibold text-foreground/78">
                  <span>VLM HTTP 后端</span>
                  <span className="text-[11px] font-medium text-muted-foreground">
                    {mineruBackend === 'vlm-http-client'
                      ? '当前会使用'
                      : '默认不会使用'}
                  </span>
                </summary>
                <div className="mt-3 space-y-2">
                  <div className={FIELD_LABEL}>VLM 模型服务地址</div>
                  <Input
                    className={DENSE_INPUT}
                    value={mineru.vl_server}
                    onChange={(event) =>
                      updateMinerU({ vl_server: event.target.value })
                    }
                    placeholder="http://localhost:30002"
                  />
                  <div className={FIELD_HINT}>
                    切到 VLM HTTP 模式时需要填写，供本地 MinerU 调用模型服务
                  </div>
                </div>
              </details>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>本地后端模式</div>
              <select
                value={mineruBackend}
                onChange={(event) =>
                  updateMinerU({ backend: event.target.value })
                }
                className={DENSE_SELECT}
              >
                <option value="pipeline">Pipeline</option>
                <option value="vlm-http-client">VLM HTTP</option>
              </select>
              <div className={FIELD_HINT}>
                Pipeline 只使用本地 API；VLM HTTP 会额外传入下方模型服务地址
              </div>
            </div>
          </div>

          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>在线 API 地址</div>
              <Input
                className={DENSE_INPUT}
                value={mineru.api_base}
                onChange={(event) =>
                  updateMinerU({ api_base: event.target.value })
                }
                placeholder="https://mineru.net/api/v4"
              />
              <div className={FIELD_HINT}>
                未配置本地服务时，在线 MinerU 会使用这个 API 地址
              </div>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>模型版本</div>
              <select
                value={mineru.model_version}
                onChange={(event) =>
                  updateMinerU({ model_version: event.target.value })
                }
                className={DENSE_SELECT}
              >
                <option value="vlm">VLM</option>
                <option value="pipeline">Pipeline</option>
              </select>
            </div>

            <div className="space-y-2 lg:col-span-3">
              <div className={FIELD_LABEL}>在线 API 令牌</div>
              <Input
                className={DENSE_INPUT}
                type="password"
                value={mineru.api_token}
                onChange={(event) =>
                  updateMinerU({ api_token: event.target.value })
                }
                placeholder="本地服务已配置时可留空"
              />
              <div className={FIELD_HINT}>
                只用于在线 MinerU，本地部署时可留空
              </div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-info" />
          ETL4LLM 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>服务地址</div>
              <Input
                className={DENSE_INPUT}
                value={etl4llm.api_url}
                onChange={(event) =>
                  updateEtl4Llm({ api_url: event.target.value })
                }
                placeholder="http://localhost:10001/v1/etl4llm/predict"
              />
              <div className={FIELD_HINT}>
                ETL4LLM 解析服务入口
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
              label="切换强制 OCR"
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
              label="切换提取图片"
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
              label="切换公式识别"
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
              label="切换过滤页眉页脚"
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-info" />
          Docling Serve 配置
        </h2>

        <div className={CARD}>
          <div className="rounded-[14px] border border-info/20 bg-info/[0.07] px-3 py-2.5">
            <div className="text-[12px] font-semibold text-foreground">独立服务模式</div>
            <div className={cn(FIELD_HINT, 'mt-0.5')}>
              Docling 依赖与模型只运行在独立容器中，不会增加 MimirQ API / worker 镜像体积
            </div>
          </div>

          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>服务基础地址</div>
              <Input
                className={DENSE_INPUT}
                value={docling.api_url}
                onChange={(event) => updateDocling({ api_url: event.target.value })}
                placeholder="http://mimirq-docling:5001"
              />
              <div className={FIELD_HINT}>可填写基础地址或 /v1/convert/file 完整地址</div>
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>转换超时（秒）</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={30}
                value={docling.request_timeout_sec}
                onChange={(event) =>
                  updateDocling({
                    request_timeout_sec:
                      Number.parseInt(event.target.value || '0', 10) || 600,
                  })
                }
              />
            </div>

            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>API Key（可选）</div>
              <Input
                className={DENSE_INPUT}
                type="password"
                value={docling.api_key}
                onChange={(event) => updateDocling({ api_key: event.target.value })}
                placeholder="未启用 Docling Serve 鉴权时留空"
              />
            </div>

            <div className="space-y-2">
              <div className={FIELD_LABEL}>健康检查超时（秒）</div>
              <Input
                className={DENSE_INPUT}
                type="number"
                min={1}
                value={docling.health_timeout_sec}
                onChange={(event) =>
                  updateDocling({
                    health_timeout_sec:
                      Number.parseInt(event.target.value || '0', 10) || 5,
                  })
                }
              />
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">启用 OCR</div>
              <div className={FIELD_HINT}>扫描件建议开启；数字原生文档可关闭以降低耗时</div>
            </div>
            <TogglePill
              enabled={docling.ocr_enabled}
              onClick={() => updateDocling({ ocr_enabled: !docling.ocr_enabled })}
              label="切换 Docling OCR"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[12px] font-medium text-foreground/80">继承系统代理</div>
              <div className={FIELD_HINT}>内网容器保持关闭；只有远程服务必须走代理时才开启</div>
            </div>
            <TogglePill
              enabled={docling.http_trust_env}
              onClick={() => updateDocling({ http_trust_env: !docling.http_trust_env })}
              label="切换 Docling 系统代理"
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-info" />
          Marker 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>服务地址</div>
              <Input
                className={DENSE_INPUT}
                value={marker.api_url}
                onChange={(event) =>
                  updateMarker({ api_url: event.target.value })
                }
                placeholder="http://localhost:2080/convert"
              />
              <div className={FIELD_HINT}>
                Marker 解析服务入口
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
          <ScanLine className="h-4 w-4 text-info" />
          PaddleOCR-VL 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <div className={FIELD_LABEL}>服务地址</div>
              <Input
                className={DENSE_INPUT}
                value={paddleVl.api_url}
                onChange={(event) =>
                  updatePaddleVL({ api_url: event.target.value })
                }
                placeholder="http://localhost:9030/convert"
              />
              <div className={FIELD_HINT}>
                PaddleOCR-VL 解析服务入口
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
                TextIn 文档解析服务入口
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
              label="切换应用文档树"
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
              label="切换 Markdown 细节增强"
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <Wand2 className="h-4 w-4 text-accent" />
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
              <div className={FIELD_LABEL}>文档语言</div>
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
              <div className={FIELD_LABEL}>模型目录</div>
              <Input
                className={DENSE_INPUT}
                value={magicPdf.models_dir}
                onChange={(event) =>
                  updateMagicPDF({ models_dir: event.target.value })
                }
                placeholder="/opt/mimirq-model-cache/.../PDF-Extract-Kit-1.0/.../models"
              />
              <div className={FIELD_HINT}>
                留空时后端会自动查找 Docker 挂载的 MinerU / PDF-Extract-Kit 模型缓存
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
              label="切换保留解析产物"
            />
          </div>
        </div>
      </section>
    </>
  )
}
