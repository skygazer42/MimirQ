'use client'

import { SettingsNumberInput } from '@/components/settings/settings-number-input'
import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Input } from '@/components/ui/input'
import type {
  DoclingConfig,
  Etl4LlmConfig,
  MagicPDFConfig,
  MarkerConfig,
  MinerUConfig,
  PaddleVLConfig,
  TextInConfig,
} from '@/types/settings'
import { cn } from '@/lib/utils'
import { LayoutGrid, ScanLine, Wand2 } from '@/components/icons'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'

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

const SECTION_TITLE = 'mb-2 flex items-center gap-2 text-[13px] font-semibold text-foreground'
const CARD = 'space-y-5'
const GRID = 'grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3'
const FIELD_LABEL = 'block text-[13px] font-semibold text-muted-foreground'
const FIELD_HINT = settingsTextTokens.helpText
const DENSE_INPUT = 'h-11 sm:h-9 rounded-md border-input bg-background text-[13px]'
const DENSE_SELECT = 'w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-[13px]'

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
  return (
    <>
      <section>
        <h2 className={SECTION_TITLE}>
          <ScanLine className="h-4 w-4 text-foreground" />
          MinerU 配置
        </h2>

        <div className={CARD}>
          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2.5">
            <div className="text-[13px] font-semibold text-foreground">本地部署优先</div>
            <div className={cn(FIELD_HINT, 'mt-0.5')}>
              配置本地 MinerU 服务地址后，解析会走本地 ZIP 模式；未配置时再使用在线 API 令牌
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(220px,1fr)]">
            <div className="space-y-3">
              <div className="space-y-2">
                <label className="block space-y-2">
                  <span className={FIELD_LABEL}>本地 MinerU API 地址</span>
                  <Input
                    className={DENSE_INPUT}
                    value={mineru.local_server_url}
                    onChange={(event) => updateMinerU({ local_server_url: event.target.value })}
                    placeholder="http://localhost:30001"
                  />
                </label>
                <div className={FIELD_HINT}>本地部署入口，解析会优先发送到这个服务</div>
              </div>

              <details
                open={mineru.backend === 'vlm-http-client'}
                className="group rounded-md border border-dashed border-border/70 bg-muted/35 px-3 py-2"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[13px] font-semibold text-foreground/78">
                  <span>VLM HTTP 后端</span>
                  <span className="text-[13px] font-medium text-muted-foreground">
                    {mineru.backend === 'vlm-http-client' ? '当前会使用' : '默认不会使用'}
                  </span>
                </summary>
                <div className="mt-3 space-y-2">
                  <label className="block space-y-2">
                    <span className={FIELD_LABEL}>VLM 模型服务地址</span>
                    <Input
                      className={DENSE_INPUT}
                      value={mineru.vl_server}
                      onChange={(event) => updateMinerU({ vl_server: event.target.value })}
                      placeholder="http://localhost:30002"
                    />
                  </label>
                  <div className={FIELD_HINT}>切到 VLM HTTP 模式时需要填写，供本地 MinerU 调用模型服务</div>
                </div>
              </details>
            </div>

            <div className="space-y-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>本地后端模式</span>
                <select
                  value={mineru.backend}
                  onChange={(event) => updateMinerU({ backend: event.target.value })}
                  className={DENSE_SELECT}
                >
                  <option value="pipeline">Pipeline</option>
                  <option value="vlm-http-client">VLM HTTP</option>
                </select>
              </label>
              <div className={FIELD_HINT}>Pipeline 只使用本地 API；VLM HTTP 会额外传入下方模型服务地址</div>
            </div>
          </div>

          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>在线 API 地址</span>
                <Input
                  className={DENSE_INPUT}
                  value={mineru.api_base}
                  onChange={(event) => updateMinerU({ api_base: event.target.value })}
                  placeholder="https://mineru.net/api/v4"
                />
              </label>
              <div className={FIELD_HINT}>未配置本地服务时，在线 MinerU 会使用这个 API 地址</div>
            </div>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>模型版本</span>
              <select
                value={mineru.model_version}
                onChange={(event) => updateMinerU({ model_version: event.target.value })}
                className={DENSE_SELECT}
              >
                <option value="vlm">VLM</option>
                <option value="pipeline">Pipeline</option>
              </select>
            </label>

            <div className="space-y-2 lg:col-span-3">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>在线 API 令牌</span>
                <Input
                  className={DENSE_INPUT}
                  type="password"
                  value={mineru.api_token}
                  onChange={(event) => updateMinerU({ api_token: event.target.value })}
                  placeholder="本地服务已配置时可留空"
                />
              </label>
              <div className={FIELD_HINT}>只用于在线 MinerU，本地部署时可留空</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-foreground" />
          ETL4LLM 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>服务地址</span>
                <Input
                  className={DENSE_INPUT}
                  value={etl4llm.api_url}
                  onChange={(event) => updateEtl4Llm({ api_url: event.target.value })}
                  placeholder="http://localhost:10001/v1/etl4llm/predict"
                />
              </label>
              <div className={FIELD_HINT}>ETL4LLM 解析服务入口</div>
            </div>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>解析模式（mode）</span>
              <select
                value={etl4llm.mode}
                onChange={(event) => updateEtl4Llm({ mode: event.target.value })}
                className={DENSE_SELECT}
              >
                <option value="partition">版面结构（partition）</option>
                <option value="text">纯文本（text）</option>
              </select>
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>超时（秒）</span>
              <SettingsNumberInput
                className={DENSE_INPUT}
                min={10}
                value={etl4llm.timeout_sec}
                onValueChange={(seconds) => updateEtl4Llm({ timeout_sec: seconds })}
              />
            </label>
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">强制 OCR</div>
              <div className={FIELD_HINT}>扫描件/图片型 PDF 建议开启</div>
            </div>
            <SettingsSwitch
              checked={etl4llm.force_ocr}
              onCheckedChange={(checked) => updateEtl4Llm({ force_ocr: checked })}
              aria-label="切换强制 OCR"
              className="shrink-0"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">提取图片</div>
              <div className={FIELD_HINT}>输出图片引用用于预览/入库</div>
            </div>
            <SettingsSwitch
              checked={etl4llm.extract_images}
              onCheckedChange={(checked) => updateEtl4Llm({ extract_images: checked })}
              aria-label="切换提取图片"
              className="shrink-0"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">公式识别</div>
              <div className={FIELD_HINT}>尽量保留公式/LaTeX 输出</div>
            </div>
            <SettingsSwitch
              checked={etl4llm.enable_formula}
              onCheckedChange={(checked) => updateEtl4Llm({ enable_formula: checked })}
              aria-label="切换公式识别"
              className="shrink-0"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">过滤页眉页脚</div>
              <div className={FIELD_HINT}>减少检索噪音（若服务支持）</div>
            </div>
            <SettingsSwitch
              checked={etl4llm.filter_page_header_footer}
              onCheckedChange={(checked) => updateEtl4Llm({ filter_page_header_footer: checked })}
              aria-label="切换过滤页眉页脚"
              className="shrink-0"
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-foreground" />
          Docling Serve 配置
        </h2>

        <div className={CARD}>
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2.5">
            <div className="text-[13px] font-semibold text-foreground">独立服务模式</div>
            <div className={cn(FIELD_HINT, 'mt-0.5')}>
              Docling 依赖与模型只运行在独立容器中，不会增加 Ragvia API / worker 镜像体积
            </div>
          </div>

          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>服务基础地址</span>
                <Input
                  className={DENSE_INPUT}
                  value={docling.api_url}
                  onChange={(event) => updateDocling({ api_url: event.target.value })}
                  placeholder="http://mimirq-docling:5001"
                />
              </label>
              <div className={FIELD_HINT}>可填写基础地址或 /v1/convert/file 完整地址</div>
            </div>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>转换超时（秒）</span>
              <SettingsNumberInput
                className={DENSE_INPUT}
                min={1}
                max={86_400}
                value={docling.request_timeout_sec}
                onValueChange={(seconds) => updateDocling({ request_timeout_sec: seconds })}
              />
            </label>

            <label className="block space-y-2 lg:col-span-2">
              <span className={FIELD_LABEL}>API Key（可选）</span>
              <Input
                className={DENSE_INPUT}
                type="password"
                value={docling.api_key}
                onChange={(event) => updateDocling({ api_key: event.target.value })}
                placeholder="未启用 Docling Serve 鉴权时留空"
              />
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>健康检查超时（秒）</span>
              <SettingsNumberInput
                className={DENSE_INPUT}
                min={1}
                max={120}
                value={docling.health_timeout_sec}
                onValueChange={(seconds) => updateDocling({ health_timeout_sec: seconds })}
              />
            </label>
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">启用 OCR</div>
              <div className={FIELD_HINT}>扫描件建议开启；数字原生文档可关闭以降低耗时</div>
            </div>
            <SettingsSwitch
              checked={docling.ocr_enabled}
              onCheckedChange={(checked) => updateDocling({ ocr_enabled: checked })}
              aria-label="切换 Docling OCR"
              className="shrink-0"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">继承系统代理</div>
              <div className={FIELD_HINT}>内网容器保持关闭；只有远程服务必须走代理时才开启</div>
            </div>
            <SettingsSwitch
              checked={docling.http_trust_env}
              onCheckedChange={(checked) => updateDocling({ http_trust_env: checked })}
              aria-label="切换 Docling 系统代理"
              className="shrink-0"
            />
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-foreground" />
          Marker 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>服务地址</span>
                <Input
                  className={DENSE_INPUT}
                  value={marker.api_url}
                  onChange={(event) => updateMarker({ api_url: event.target.value })}
                  placeholder="http://localhost:2080/convert"
                />
              </label>
              <div className={FIELD_HINT}>Marker 解析服务入口</div>
            </div>

            <div className="space-y-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>超时（秒）</span>
                <SettingsNumberInput
                  className={DENSE_INPUT}
                  min={30}
                  value={marker.timeout_sec}
                  onValueChange={(seconds) => updateMarker({ timeout_sec: seconds })}
                />
              </label>
              <div className={FIELD_HINT}>大文件/复杂 PDF 建议调大</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <ScanLine className="h-4 w-4 text-foreground" />
          PaddleOCR-VL 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>服务地址</span>
                <Input
                  className={DENSE_INPUT}
                  value={paddleVl.api_url}
                  onChange={(event) => updatePaddleVL({ api_url: event.target.value })}
                  placeholder="http://localhost:9030/convert"
                />
              </label>
              <div className={FIELD_HINT}>PaddleOCR-VL 解析服务入口</div>
            </div>

            <div className="space-y-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>超时（秒）</span>
                <SettingsNumberInput
                  className={DENSE_INPUT}
                  min={30}
                  value={paddleVl.timeout_sec}
                  onValueChange={(seconds) => updatePaddleVL({ timeout_sec: seconds })}
                />
              </label>
              <div className={FIELD_HINT}>扫描件/OCR 场景建议调大</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className={SECTION_TITLE}>
          <LayoutGrid className="h-4 w-4 text-foreground dark:text-foreground" />
          TextIn xParse 配置
        </h2>

        <div className={CARD}>
          <div className={GRID}>
            <div className="space-y-2 lg:col-span-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>API 地址</span>
                <Input
                  className={DENSE_INPUT}
                  value={textIn.api_url}
                  onChange={(event) => updateTextIn({ api_url: event.target.value })}
                  placeholder="https://api.textin.com/ai/service/v1/pdf_to_markdown"
                />
              </label>
              <div className={FIELD_HINT}>TextIn 文档解析服务入口</div>
            </div>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>超时（秒）</span>
              <SettingsNumberInput
                className={DENSE_INPUT}
                min={10}
                value={textIn.timeout_sec}
                onValueChange={(seconds) => updateTextIn({ timeout_sec: seconds })}
              />
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>APP ID</span>
              <Input
                className={DENSE_INPUT}
                value={textIn.app_id}
                onChange={(event) => updateTextIn({ app_id: event.target.value })}
                placeholder="你的 TextIn APP ID"
              />
            </label>

            <label className="block space-y-2 lg:col-span-2">
              <span className={FIELD_LABEL}>Secret Code</span>
              <Input
                className={DENSE_INPUT}
                type="password"
                value={textIn.secret_code}
                onChange={(event) => updateTextIn({ secret_code: event.target.value })}
                placeholder="你的 TextIn Secret Code"
              />
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>解析模式</span>
              <select
                value={textIn.parse_mode}
                onChange={(event) => updateTextIn({ parse_mode: event.target.value })}
                className={DENSE_SELECT}
              >
                <option value="auto">auto</option>
                <option value="scan">scan</option>
                <option value="parse">parse</option>
                <option value="lite">lite</option>
                <option value="vlm">vlm</option>
              </select>
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>表格输出</span>
              <select
                value={textIn.table_flavor}
                onChange={(event) => updateTextIn({ table_flavor: event.target.value })}
                className={DENSE_SELECT}
              >
                <option value="html">html</option>
                <option value="markdown">markdown</option>
              </select>
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>DPI</span>
              <SettingsNumberInput
                className={DENSE_INPUT}
                min={72}
                value={textIn.dpi}
                onValueChange={(dpi) => updateTextIn({ dpi })}
              />
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>页数限制（0=全部）</span>
              <SettingsNumberInput
                className={DENSE_INPUT}
                min={0}
                value={textIn.page_count}
                onValueChange={(pageCount) => updateTextIn({ page_count: pageCount })}
              />
            </label>
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">应用文档树</div>
              <div className={FIELD_HINT}>尽量保留标题层级 / 文档结构</div>
            </div>
            <SettingsSwitch
              checked={textIn.apply_document_tree}
              onCheckedChange={(checked) => updateTextIn({ apply_document_tree: checked })}
              aria-label="切换应用文档树"
              className="shrink-0"
            />
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">Markdown 细节增强</div>
              <div className={FIELD_HINT}>返回更丰富的 Markdown 结构</div>
            </div>
            <SettingsSwitch
              checked={textIn.markdown_details}
              onCheckedChange={(checked) => updateTextIn({ markdown_details: checked })}
              aria-label="切换 Markdown 细节增强"
              className="shrink-0"
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
            <label className="block space-y-2">
              <span className={FIELD_LABEL}>解析方法（method）</span>
              <select
                value={magicPdf.method}
                onChange={(event) => updateMagicPDF({ method: event.target.value })}
                className={DENSE_SELECT}
              >
                <option value="auto">自动（auto）</option>
                <option value="txt">文本优先（txt）</option>
                <option value="ocr">OCR 优先（ocr）</option>
              </select>
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>文档语言</span>
              <Input
                className={DENSE_INPUT}
                value={magicPdf.lang}
                onChange={(event) => updateMagicPDF({ lang: event.target.value })}
                placeholder='例如"ch"'
              />
            </label>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>超时（秒）</span>
              <SettingsNumberInput
                className={DENSE_INPUT}
                min={30}
                value={magicPdf.timeout_sec}
                onValueChange={(seconds) => updateMagicPDF({ timeout_sec: seconds })}
              />
            </label>

            <div className="space-y-2 lg:col-span-2">
              <label className="block space-y-2">
                <span className={FIELD_LABEL}>模型目录</span>
                <Input
                  className={DENSE_INPUT}
                  value={magicPdf.models_dir}
                  onChange={(event) => updateMagicPDF({ models_dir: event.target.value })}
                  placeholder="/opt/mimirq-model-cache/.../PDF-Extract-Kit-1.0/.../models"
                />
              </label>
              <div className={FIELD_HINT}>留空时后端会自动查找 Docker 挂载的 MinerU / PDF-Extract-Kit 模型缓存</div>
            </div>

            <label className="block space-y-2">
              <span className={FIELD_LABEL}>设备模式</span>
              <select
                className={DENSE_SELECT}
                value={magicPdf.device_mode}
                onChange={(event) => updateMagicPDF({ device_mode: event.target.value })}
              >
                <option value="">使用默认设备</option>
                <option value="cpu">CPU</option>
                <option value="cuda">CUDA / GPU</option>
              </select>
            </label>
          </div>

          <div className="flex items-center justify-between border-t border-border/70 pt-3">
            <div>
              <div className="text-[13px] font-medium text-foreground/80">保留解析产物</div>
              <div className={FIELD_HINT}>默认会在入库流程完成后清理 `.magicpdf/` 目录</div>
            </div>
            <SettingsSwitch
              checked={magicPdf.keep_artifacts}
              onCheckedChange={(checked) => updateMagicPDF({ keep_artifacts: checked })}
              aria-label="切换保留解析产物"
              className="shrink-0"
            />
          </div>
        </div>
      </section>
    </>
  )
}
