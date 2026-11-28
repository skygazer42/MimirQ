'use client'

import {
  Copy,
  FileText,
  Folder,
  Hash,
  Highlighter,
  Layers,
  ListChecks,
  ScanLine,
  Shield,
  SlidersHorizontal,
  Table2,
  Type,
} from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import type { DocumentPipelineOptions } from '@/types'
import styles from './governance-inbox.module.css'

type EmptyPresetTab = 'clean' | 'annotate' | 'classify'

type GovernanceEmptyPresetsProps = {
  tab: EmptyPresetTab
  onOpenConfig: () => void
  onOpenDirectory: () => void
}

const MATRIX_CLEANING_RULES = [
  {
    key: 'governance_remove_noise_lines',
    icon: SlidersHorizontal,
    title: '噪声行清理',
    description: '删除页眉页脚与乱码干扰行',
  },
  {
    key: 'governance_remove_toc_lines',
    icon: ListChecks,
    title: '目录行清理',
    description: '识别并移除目录索引行',
  },
  {
    key: 'governance_remove_common_lines',
    icon: Layers,
    title: '公共行清理',
    description: '清理跨页重复出现的固定行',
  },
  {
    key: 'governance_unwrap_lines',
    icon: ScanLine,
    title: '断行合并',
    description: '合并因换行导致的异常断行',
  },
  {
    key: 'governance_pii_anonymize',
    icon: Shield,
    title: 'PII 脱敏',
    description: '检测并脱敏邮箱与电话信息',
  },
  {
    key: 'governance_drop_duplicate_paragraphs',
    icon: Copy,
    title: '重复段清理',
    description: '识别并清理文档内重复段落',
  },
] as const satisfies ReadonlyArray<{
  key: keyof DocumentPipelineOptions
  icon: typeof FileText
  title: string
  description: string
}>

const ANNOTATION_TYPES = [
  {
    id: 'entity',
    icon: Hash,
    title: '实体标注',
    description: '人物、机构、产品与专有名词',
  },
  {
    id: 'keyword',
    icon: Highlighter,
    title: '关键词标注',
    description: '核心术语、主题概念与检索词',
  },
  {
    id: 'sensitive',
    icon: Shield,
    title: '敏感信息',
    description: '隐私字段、合规风险与受限片段',
  },
  {
    id: 'custom',
    icon: Type,
    title: '自定义标签',
    description: '按业务规范补充自定义划词分类',
  },
] as const

const ANNOTATION_ENGINES = [
  { name: 'CPU 规则提取', detail: '抽取实体与高频关键词，无需模型' },
  { name: 'LLM 语义提取', detail: '理解上下文生成主题、领域与结构化语义标签' },
  { name: '合规敏感扫描', detail: '结合 PII、密钥与正则规则定位敏感片段' },
] as const

const PRESET_CATEGORIES = [
  { id: 'technical', icon: FileText, title: '技术文档', description: '架构说明、接口手册与运维规范' },
  { id: 'product', icon: FileText, title: '产品文档', description: '需求方案、功能说明与发布记录' },
  { id: 'business', icon: Folder, title: '业务文档', description: '流程 SOP、运营台账与项目资料' },
  { id: 'legal', icon: Shield, title: '法务合规', description: '合同协议、审计条款与制度文件' },
  { id: 'hr', icon: Folder, title: '人力行政', description: '员工手册、考核办法与内部通知' },
  { id: 'finance', icon: Folder, title: '财务文档', description: '预算报表、报销规范与结算资料' },
] as const

const SENSITIVITY_LEVELS = ['公开', '内部', '机密', '受限'] as const

export function GovernanceEmptyPresets({
  tab,
  onOpenConfig,
  onOpenDirectory,
}: Readonly<GovernanceEmptyPresetsProps>) {
  const { options, updateOption, setEnabled } = usePipelineOptions()

  if (tab === 'clean') {
    const enabledCount =
      MATRIX_CLEANING_RULES.filter((rule) => options[rule.key] === true).length +
      (options.governance_normalize_tables === true ? 1 : 0)
    const maxBlankValue =
      typeof options.governance_max_blank_lines === 'number' ? String(options.governance_max_blank_lines) : 'unlimited'

    return (
      <div className={styles.presetShell} data-governance-empty-presets="clean">
        <div className={styles.presetSummaryBar}>
          <span className={styles.presetSummaryText}>
            <span className={styles.presetSummaryDot} aria-hidden="true" />
            已启用 {enabledCount} 项清洗规则 · 待选择文档
          </span>
          <Button size="sm" variant="outline" className={styles.presetSummaryBtn} onClick={onOpenConfig}>
            高级配置
          </Button>
        </div>

        <section className={styles.presetSection} aria-label="常用清洗规则">
          <h4 className={styles.presetHeading}>常用清洗规则</h4>
          <div className={styles.presetMatrix}>
            {MATRIX_CLEANING_RULES.map((rule) => {
              const Icon = rule.icon
              const checked = options[rule.key] === true
              const inputId = `governance-preset-${rule.key}`
              return (
                <label key={rule.key} htmlFor={inputId} className={styles.presetTile}>
                  <Icon className="size-4 shrink-0 text-muted-foreground mt-0.5" aria-hidden="true" />
                  <span className={styles.presetTileCopy}>
                    <strong>{rule.title}</strong>
                    <small>{rule.description}</small>
                  </span>
                  <Switch
                    id={inputId}
                    checked={checked}
                    className="data-[state=checked]:bg-accent"
                    onCheckedChange={(next) => {
                      setEnabled(true)
                      updateOption(rule.key, next)
                    }}
                  />
                </label>
              )
            })}
          </div>
        </section>

        <section className={styles.presetFooterCard} aria-label="版面与空行规整">
          <h4 className={styles.presetHeading}>版面与空行规整</h4>
          <div className={styles.presetInlineRow}>
            <label htmlFor="governance-preset-tables" className={styles.presetRowLabel}>
              <Table2 className="size-3.5 text-muted-foreground" aria-hidden="true" />
              表格规范化
            </label>
            <Switch
              id="governance-preset-tables"
              checked={options.governance_normalize_tables === true}
              className="data-[state=checked]:bg-accent"
              onCheckedChange={(next) => {
                setEnabled(true)
                updateOption('governance_normalize_tables', next)
              }}
            />
          </div>
          <div className={styles.presetInlineRow}>
            <label htmlFor="governance-preset-blank-lines" className={styles.presetRowLabel}>
              空行规整
            </label>
            <select
              id="governance-preset-blank-lines"
              className={styles.presetCompactSelect}
              value={maxBlankValue}
              onChange={(event) => {
                setEnabled(true)
                const raw = event.target.value
                updateOption('governance_max_blank_lines', raw === 'unlimited' ? undefined : Number(raw))
              }}
            >
              <option value="unlimited">保留原空行</option>
              <option value="1">最多保留 1 行</option>
              <option value="2">最多保留 2 行</option>
              <option value="3">最多保留 3 行</option>
            </select>
          </div>
        </section>
      </div>
    )
  }

  if (tab === 'annotate') {
    return (
      <div className={styles.presetShell} data-governance-empty-presets="annotate">
        <div className={styles.presetSummaryBar}>
          <span className={styles.presetSummaryText}>
            <span className={styles.presetSummaryDot} aria-hidden="true" />
            4 类标注体系 · 3 种自动提取引擎 · 待选择文档
          </span>
          <Button size="sm" variant="outline" className={styles.presetSummaryBtn} onClick={onOpenDirectory}>
            选择文档
          </Button>
        </div>

        <section className={styles.presetSection} aria-label="支持标注类型">
          <h4 className={styles.presetHeading}>标注类型体系</h4>
          <div className={styles.presetMatrix}>
            {ANNOTATION_TYPES.map((item) => {
              const Icon = item.icon
              return (
                <div key={item.id} className={styles.presetInfoTile}>
                  <Icon className="size-4 shrink-0 text-muted-foreground mt-0.5" aria-hidden="true" />
                  <span className={styles.presetTileCopy}>
                    <strong>{item.title}</strong>
                    <small>{item.description}</small>
                  </span>
                </div>
              )
            })}
          </div>
        </section>

        <section className={styles.presetFooterCard} aria-label="自动标注引擎">
          <h4 className={styles.presetHeading}>自动标注引擎</h4>
          {ANNOTATION_ENGINES.map((engine) => (
            <div key={engine.name} className={styles.presetEngineRow}>
              <strong>{engine.name}</strong>
              <span>{engine.detail}</span>
            </div>
          ))}
        </section>
      </div>
    )
  }

  return (
    <div className={styles.presetShell} data-governance-empty-presets="classify">
      <div className={styles.presetSummaryBar}>
        <span className={styles.presetSummaryText}>
          <span className={styles.presetSummaryDot} aria-hidden="true" />
          预设业务分类 · 4 级敏感度标签 · 待选择文档
        </span>
        <Button size="sm" variant="outline" className={styles.presetSummaryBtn} onClick={onOpenDirectory}>
          选择文档
        </Button>
      </div>

      <section className={styles.presetSection} aria-label="预设业务分类目录">
        <h4 className={styles.presetHeading}>预设业务分类</h4>
        <div className={styles.presetMatrix}>
          {PRESET_CATEGORIES.map((category) => {
            const Icon = category.icon
            return (
              <div key={category.id} className={styles.presetInfoTile}>
                <Icon className="size-4 shrink-0 text-muted-foreground mt-0.5" aria-hidden="true" />
                <span className={styles.presetTileCopy}>
                  <strong>{category.title}</strong>
                  <small>{category.description}</small>
                </span>
              </div>
            )
          })}
        </div>
      </section>

      <section className={styles.presetFooterCard} aria-label="敏感度分级与归档说明">
        <h4 className={styles.presetHeading}>敏感度分级与入库衔接</h4>
        <div className={styles.presetInlineRow}>
          <span className={styles.presetRowLabel}>敏感度级别</span>
          <div className={styles.presetChipRow}>
            {SENSITIVITY_LEVELS.map((level) => (
              <span key={level}>{level}</span>
            ))}
          </div>
        </div>
        <div className={styles.presetEngineRow}>
          <strong>归档入库</strong>
          <span>载入文档后支持自动分类推荐与自定义标签，保存后可直接进入切块预览。</span>
        </div>
      </section>
    </div>
  )
}
