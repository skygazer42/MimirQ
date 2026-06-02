import type { ChunkStrategyInfo } from '@/types'

export interface ChunkStrategyOption {
  value: string
  label: string
  description: string
  icon: 'recursive' | 'token' | 'sentence' | 'hierarchical' | 'integrated' | 'separator'
  badge?: string
  group?: 'preset' | 'langchain' | 'llama_index' | 'integrated'
  disabled?: boolean
}

type ChunkStrategyGroup = NonNullable<ChunkStrategyOption['group']>

function strategy(
  value: string,
  label: string,
  description: string,
  icon: ChunkStrategyOption['icon'],
  badge: string,
  group: ChunkStrategyGroup
): ChunkStrategyOption {
  return { value, label, description, icon, badge, group }
}

export const CHUNK_STRATEGY_OPTIONS: ChunkStrategyOption[] = [
  strategy('auto', '自动选择（推荐）', '自动识别内容形态（Q&A/对话/论文/大纲/Markdown/JSON），选择合适的切块器。', 'recursive', '推荐', 'preset'),
  strategy('pdf_layout', 'PDF 版式感知（bbox/columns）', String.raw`适用于包含 @@page\tl\tr\tt\tb## 位置标签的 PDF 解析结果：按版面块聚合，写入 bbox/column 元数据，并从 chunk 文本中去除位置标签。`, 'hierarchical', 'PDF', 'preset'),
  strategy('manuscript', '文稿/讲稿（预设）', '面向文稿/讲稿/手稿/报告：优先按 Q&A / 对话 / 论文 / 大纲切块。', 'hierarchical', '文稿', 'preset'),
  strategy('outline', '大纲/章节（预设）', '识别 1. / 1.1 / 第X章 等编号标题，按章节结构切块。', 'hierarchical', '大纲', 'preset'),
  strategy('transcript', '访谈/会议纪要（预设）', '识别“张三：…”等说话人行，尽量保持完整发言轮次。', 'sentence', '对话', 'preset'),
  strategy('qa_pairs', 'FAQ / Q&A（预设）', '识别 Q/A 或 问/答 标记，尽量保持每组问答不被拆散。', 'sentence', 'Q&A', 'preset'),
  strategy('paper', '论文/报告（预设）', '识别摘要/引言/方法/结果/讨论/参考文献等常见章节并切块。', 'hierarchical', '论文', 'preset'),
  strategy('book_structured', '书籍/长文档（预设）', '识别 Chapter/Part/Volume/第X章 等结构，按章节上下文切块。', 'hierarchical', '书籍', 'preset'),
  strategy('laws_structured', '法律/合同/制度（预设）', '识别 第X条/（一）/Article 等条款结构，按条款切块。', 'hierarchical', '条款', 'preset'),
  strategy('email_thread', '邮件线程（预设）', '识别 From/To/Subject/-----Original Message----- 等，按邮件消息切块。', 'sentence', '邮件', 'preset'),
  strategy('sop_steps', 'SOP/操作步骤（预设）', '识别 Step 1/步骤一 等步骤标题，尽量保持步骤不被拆散。', 'hierarchical', 'SOP', 'preset'),
  strategy('glossary', '术语表/词典（预设）', '识别“术语：定义”条目，按条目切块并保留术语列表。', 'separator', '术语', 'preset'),
  strategy('resume_structured', '简历/履历（预设）', '识别教育/经历/项目/技能等常见章节，按简历结构切块。', 'hierarchical', '简历', 'preset'),
  strategy('presentation_slides', 'PPT/幻灯片（预设）', "识别 --- 分隔或 Slide/Page 标记，尽量保持每页/每张幻灯片内容完整。", 'hierarchical', 'PPT', 'preset'),
  strategy('chat_history', '聊天记录（预设）', '识别带时间戳的对话记录，按消息分组并保留上下文。', 'sentence', '聊天', 'preset'),
  strategy('markdown_table', 'Markdown 表格（预设）', '识别 Markdown 表格块，避免在行内切分，超大表格按行边界拆分。', 'separator', '表格', 'preset'),
  strategy('csv_rows', 'CSV 行（预设）', "适配 CsvParser 的 row N: 输出，按行聚合切块并支持行级 overlap。", 'separator', 'CSV', 'preset'),
  strategy('spreadsheet_sheet', 'Excel 工作表（预设）', "适配 ExcelParser 的 ## Sheet: 输出，先按工作表切分再切块。", 'hierarchical', '工作表', 'preset'),
  strategy('changelog', 'Changelog / Release Notes（预设）', '识别版本/Unreleased 标题，按发布版本切块。', 'hierarchical', 'Changelog', 'preset'),
  strategy('log_events', '日志（预设）', '识别时间戳+级别的日志行，按日志条目聚合切块。', 'separator', 'Log', 'preset'),
  strategy('subtitles', '字幕 SRT/VTT（预设）', '识别 00:00:00,000 --> 00:00:01,000 时间码，按字幕 cue 切块。', 'sentence', '字幕', 'preset'),
  strategy('api_reference', 'API 接口文档（预设）', '识别 GET /path 等端点签名，按接口块切块。', 'hierarchical', 'API', 'preset'),
  strategy('diff_patch', 'Diff / Patch（预设）', '识别 diff --git 与 @@ hunk，按文件与 hunk 边界切块。', 'separator', 'Diff', 'preset'),
  strategy('kv_config', '配置 Key=Value（预设）', '识别大量 KEY=VALUE（支持 [section]），按配置项聚合切块。', 'separator', '配置', 'preset'),
  strategy('qa_markdown', 'Markdown Q&A（预设）', '识别 **Q:**/**A:** 或 ### Q: 等 Markdown 形式问答，按问答对切块。', 'sentence', 'Q&A', 'preset'),
  strategy('meeting_minutes', '会议纪要/行动项（预设）', '识别 议程/讨论/决议/行动项 等章节，按纪要结构切块。', 'hierarchical', '纪要', 'preset'),
  strategy('timeline_events', '时间线/事件（预设）', '识别以日期开头的事件行（YYYY-MM-DD），按事件聚合切块。', 'hierarchical', '时间线', 'preset'),
  strategy('yaml_manifest', 'YAML / K8s Manifest（预设）', "识别 YAML 多文档（---）与 kind/name，按文档聚合切块。", 'hierarchical', 'YAML', 'preset'),
  strategy('toml_config', 'TOML 配置（预设）', '识别 [table] / [[array]] 与 key=value，按表/配置项聚合切块。', 'separator', 'TOML', 'preset'),
  strategy('sql_schema', 'SQL Schema / DDL（预设）', '识别 CREATE/ALTER 等语句，按表/对象语句块切块。', 'separator', 'SQL', 'preset'),
  strategy('stacktrace', '异常堆栈/Traceback（预设）', '识别 Python/Java 等堆栈块，尽量保持完整 traceback 不拆散。', 'separator', 'Trace', 'preset'),
  strategy('git_commit_log', 'Git Commit Log（预设）', "识别 commit <sha> / Author / Date 等提交头，按提交块切块并保留提交上下文。", 'separator', 'Git', 'preset'),
  strategy('jsonl_records', 'JSONL / NDJSON（预设）', '按每行 JSON 记录聚合切块，避免把记录拆散（适合日志/事件流）。', 'separator', 'JSONL', 'preset'),
  strategy('xml_feed', 'RSS / Atom Feed（预设）', '识别 <item>/<entry> 条目块，按条目切块并保留标题等元信息。', 'hierarchical', 'Feed', 'preset'),
  strategy('openapi_spec', 'OpenAPI / Swagger（预设）', '识别 paths: 下的端点块，按 path 切块，避免接口说明被拆散。', 'hierarchical', 'OpenAPI', 'preset'),
  strategy('graphql_schema', 'GraphQL Schema（预设）', '按 type/input/enum/interface/union 等顶层定义切块，保持 schema 结构。', 'separator', 'GraphQL', 'preset'),
  strategy('proto_schema', 'Protobuf / .proto（预设）', '按 message/enum/service 等顶层块切块（brace-aware），适合接口与数据结构定义。', 'separator', 'Proto', 'preset'),
  strategy('terraform_hcl', 'Terraform / HCL（预设）', '按 resource/module/variable 等块切块（brace-aware），保持配置块完整。', 'separator', 'Terraform', 'preset'),
  strategy('postmortem_report', '事故复盘 / RCA（预设）', '识别 Summary/Impact/Timeline/Root Cause/Action Items 等章节，按复盘结构切块。', 'hierarchical', 'RCA', 'preset'),
  strategy('docker_compose', 'Docker Compose（预设）', '识别 services: 下的服务块，按 service 切块，适合 docker-compose.yml。', 'hierarchical', 'Compose', 'preset'),
  strategy('github_actions', 'GitHub Actions（预设）', '识别 jobs: 下的 job 块，按 job 切块，适合 .github/workflows/*.yml。', 'hierarchical', 'Actions', 'preset'),
  strategy('gitlab_ci', 'GitLab CI（预设）', '按顶层 job/config 块切块（stages/variables/job 等），适合 .gitlab-ci.yml。', 'hierarchical', 'CI', 'preset'),
  strategy('ansible_playbook', 'Ansible Playbook（预设）', '识别顶层 play（- name/- hosts），按 play 块切块，适合 playbook.yml。', 'hierarchical', 'Ansible', 'preset'),
  strategy('markdown_frontmatter', 'Markdown Frontmatter（预设）', '保留 YAML Frontmatter（--- ... ---），再对正文按 Markdown 友好分隔切块。', 'hierarchical', 'FM', 'preset'),
  strategy('http_trace', 'HTTP Trace（预设）', '识别 GET/POST ... HTTP/1.1 与 HTTP/1.1 200 等请求响应头，按请求块切块。', 'separator', 'HTTP', 'preset'),
  strategy('junit_xml', 'JUnit XML（预设）', '识别 <testsuite>/<testcase>，按 testcase 块切块，适合测试报告 XML。', 'hierarchical', 'JUnit', 'preset'),
  strategy('sitemap_xml', 'Sitemap XML（预设）', '识别 <urlset>/<sitemapindex> 中的条目，按 <url>/<sitemap> 块切块。', 'hierarchical', 'Sitemap', 'preset'),
  strategy('maven_pom', 'Maven POM（预设）', '识别 pom.xml 中的 <dependency>/<plugin>，按记录聚合切块并提取坐标信息。', 'separator', 'Maven', 'preset'),
  strategy('terraform_plan', 'Terraform Plan（预设）', '识别 “# ... will be ...” 变更头，按资源变更块切块，适合 terraform plan 输出。', 'separator', 'TF Plan', 'preset'),
  strategy('dockerfile', 'Dockerfile（预设）', '识别 FROM 阶段与 RUN/COPY 等指令块，按阶段/指令聚合切块。', 'separator', 'Docker', 'preset'),
  strategy('makefile', 'Makefile（预设）', '识别 target: 规则与配方（tab 缩进），按 target 块聚合切块。', 'separator', 'Make', 'preset'),
  strategy('nginx_config', 'Nginx 配置（预设）', '识别 server {}/location {} 等块，按 server 块聚合切块。', 'separator', 'Nginx', 'preset'),
  strategy('jira_ticket', 'Jira / 工单（预设）', '识别 Summary/Description/Steps/Expected/Actual 等字段，按工单结构切块。', 'hierarchical', 'Jira', 'preset'),
  strategy('prd_spec', 'PRD / 需求文档（预设）', '识别 背景/目标/范围/需求/验收/风险/里程碑 等章节，按 PRD 结构切块。', 'hierarchical', 'PRD', 'preset'),
  strategy('html_sections', 'HTML 标题（预设）', '识别 <h1>-<h6> 标题标签，按标题层级切块。', 'hierarchical', 'HTML', 'preset'),
  strategy('rst_sections', 'reStructuredText（预设）', '识别 ===/--- 下划线标题，按章节结构切块。', 'hierarchical', 'RST', 'preset'),
  strategy('asciidoc_sections', 'AsciiDoc（预设）', '识别 =/==/=== 标题行，按章节层级切块。', 'hierarchical', 'AsciiDoc', 'preset'),
  strategy('latex_sections', 'LaTeX（预设）', String.raw`识别 \section/\chapter 等结构命令，按章节切块。`, 'hierarchical', 'LaTeX', 'preset'),
  strategy('orgmode_sections', 'Org-mode（预设）', '识别 * / ** 标题行，按章节层级切块。', 'hierarchical', 'Org', 'preset'),
  strategy('mediawiki_sections', 'WikiText / MediaWiki（预设）', '识别 == Heading == 标题行，按章节层级切块。', 'hierarchical', 'Wiki', 'preset'),
  strategy('langchain_recursive', 'LangChain 递归切分', '按分隔符（段落、句号等）递归切分，保留语义完整性。', 'recursive', '通用', 'langchain'),
  strategy('semantic_sentence', '语义句子切分', '按句子边界聚合，减少断句（适合长文本）。', 'sentence', '句子', 'langchain'),
  strategy('sentence_window', '句子窗口切分', '按句子窗口聚合，使用“按句子”重叠（避免 overlap 截断句子）。', 'sentence', '窗口', 'langchain'),
  strategy('parent_child', '父子切分', '先生成父块，再切子块，保留 parent_id。', 'hierarchical', '层级', 'langchain'),
  strategy('langchain_token', 'LangChain Token 切分', '按 Token 数量切分，适合控制 LLM 输入长度。', 'token', 'Token', 'langchain'),
  strategy('separator', '自定义分隔符切分', '按指定分隔符直接切分，适合结构化/规则化文档。', 'separator', '自定义', 'langchain'),
  strategy('markdown_header', 'Markdown 标题切分', '按 # / ## / ### 标题层级切分，保留标题上下文。', 'hierarchical', 'Markdown', 'langchain'),
  strategy('markdown_outline', 'Markdown Outline Split', 'Split by markdown heading hierarchy and preserve outline_path/header_path.', 'hierarchical', 'Markdown', 'langchain'),
  strategy('markdown_aware', 'Markdown 感知切分', '针对 Markdown 结构优化（标题/列表/代码块）并保留字符位置。', 'recursive', 'Markdown', 'langchain'),
  strategy('json', 'JSON 结构切分', '尽量按 JSON 结构拆分（数组元素/对象键），通常不使用 overlap。', 'separator', 'JSON', 'langchain'),
  strategy('code', '代码切分', '按代码结构/语句块切分（适合多语言代码）。', 'separator', 'Code', 'langchain'),
  strategy('smart_code', '智能代码切分（Python）', '基于 AST-like 结构切分 Python，减少函数/类被拆分。', 'separator', 'Python', 'langchain'),
  strategy('llama_index', 'LlamaIndex 句子切分', '基于句子边界的智能切分，保持语义完整性。', 'sentence', 'LlamaIndex', 'llama_index'),
  strategy('llama_index_hierarchical', 'LlamaIndex 分层切分', '多层级切分策略，适合复杂文档结构。', 'hierarchical', '分层', 'llama_index'),
  strategy('integrated_naive', 'Integrated pipeline 通用切分', 'Integrated pipeline 通用文档切分（集成解析+切块）。', 'integrated', 'Integrated pipeline', 'integrated'),
  strategy('integrated_book', 'Integrated pipeline 书籍切分', '针对书籍/长文档优化，尽量保留章节结构。', 'integrated', '书籍', 'integrated'),
  strategy('integrated_laws', 'Integrated pipeline 法律切分', '针对法律文档优化，尽量保留条款结构。', 'integrated', '法律', 'integrated'),
  strategy('integrated_email', 'Integrated pipeline 邮件切分', '针对邮件/通信优化，尽量保留引用结构。', 'integrated', '邮件', 'integrated'),
]

export function getChunkStrategyOption(value?: string) {
  const normalized = (value || '').toLowerCase()
  return (
    CHUNK_STRATEGY_OPTIONS.find((option) => option.value === normalized) ||
    CHUNK_STRATEGY_OPTIONS.find((option) => option.value === 'langchain_recursive') ||
    CHUNK_STRATEGY_OPTIONS[0]
  )
}

export function getChunkStrategyLabel(value?: string) {
  return getChunkStrategyOption(value).label
}

export function getStrategiesByGroup(group: string) {
  return CHUNK_STRATEGY_OPTIONS.filter((option) => option.group === group)
}

export const INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES = [
  'langchain_recursive',
  ...getStrategiesByGroup('integrated').map((option) => option.value),
]

export type ChunkStrategyRecommendation =
  | 'mainstream'
  | 'specialized'
  | 'experimental'
  | 'optional'
  | 'integrated'

export interface ChunkStrategyCatalogItem extends ChunkStrategyOption {
  available?: boolean
  notes?: string | null
  recommendation: ChunkStrategyRecommendation
  recommendationLabel: string
}

const MAINSTREAM_STRATEGIES = new Set([
  'auto',
  'langchain_recursive',
  'semantic_sentence',
  'parent_child',
  'markdown',
  'markdown_header',
  'markdown_hierarchy',
  'text_hierarchy',
  'markdown_table',
  'csv_rows',
  'spreadsheet_sheet',
  'smart_code',
  'json',
  'html_sections',
  'qa_pairs',
  'api_reference',
  'openapi_spec',
  'sql_schema',
  'jira_ticket',
  'laws_structured',
  'paper',
])

const EXPERIMENTAL_STRATEGIES = new Set([
  'agentic_chunker',
  'late_chunking',
  'late_chunking_jina',
  'proposition',
  'raptor',
])

const OPTIONAL_STRATEGIES = new Set(['llama_index', 'llama_index_hierarchical'])

const INTEGRATED_STRATEGIES = new Set(
  CHUNK_STRATEGY_OPTIONS.filter((option) => option.group === 'integrated').map((option) => option.value)
)

const NOTE_PREFIX_TO_RECOMMENDATION: Array<{
  prefix: string
  recommendation: ChunkStrategyRecommendation
}> = [
  { prefix: '[Mainstream RAG recommended]', recommendation: 'mainstream' },
  { prefix: '[Specialized document strategy]', recommendation: 'specialized' },
  { prefix: '[Experimental or corpus-specific]', recommendation: 'experimental' },
  { prefix: '[Optional dependency]', recommendation: 'optional' },
  { prefix: '[Integrated parse+chunk preset]', recommendation: 'integrated' },
]

const RECOMMENDATION_LABELS: Record<ChunkStrategyRecommendation, string> = {
  mainstream: '主流推荐',
  specialized: '专项适配',
  experimental: '实验性',
  optional: '按需启用',
  integrated: '集成预设',
}

const RECOMMENDATION_ORDER: Record<ChunkStrategyRecommendation, number> = {
  mainstream: 0,
  specialized: 1,
  experimental: 2,
  optional: 3,
  integrated: 4,
}

function humanizeChunkStrategyValue(value: string) {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function stripRecommendationPrefix(notes?: string | null) {
  const source = String(notes || '').trim()
  if (!source) return ''
  for (const item of NOTE_PREFIX_TO_RECOMMENDATION) {
    if (source.startsWith(item.prefix)) {
      return source.slice(item.prefix.length).trim()
    }
  }
  return source
}

export function getChunkStrategyRecommendation(
  value: string,
  notes?: string | null
): ChunkStrategyRecommendation {
  const normalized = String(value || '').trim().toLowerCase()
  const source = String(notes || '').trim()
  for (const item of NOTE_PREFIX_TO_RECOMMENDATION) {
    if (source.startsWith(item.prefix)) {
      return item.recommendation
    }
  }
  if (INTEGRATED_STRATEGIES.has(normalized)) return 'integrated'
  if (OPTIONAL_STRATEGIES.has(normalized)) return 'optional'
  if (EXPERIMENTAL_STRATEGIES.has(normalized)) return 'experimental'
  if (MAINSTREAM_STRATEGIES.has(normalized)) return 'mainstream'
  return 'specialized'
}

export function getChunkStrategyRecommendationLabel(recommendation: ChunkStrategyRecommendation) {
  return RECOMMENDATION_LABELS[recommendation]
}

export function buildChunkStrategyCatalog(
  capabilities?: ChunkStrategyInfo[] | null
): ChunkStrategyCatalogItem[] {
  const baseMap = new Map(CHUNK_STRATEGY_OPTIONS.map((option) => [option.value, option]))
  const capabilityMap = new Map(
    (capabilities || [])
      .map((item) => ({
        ...item,
        name: String(item.name || '').trim().toLowerCase(),
      }))
      .filter((item) => item.name)
      .map((item) => [item.name, item] as const)
  )

  const names = new Set<string>([
    ...Array.from(baseMap.keys()),
    ...Array.from(capabilityMap.keys()),
  ])

  return Array.from(names)
    .map((name) => {
      const base = baseMap.get(name)
      const capability = capabilityMap.get(name)
      const recommendation = getChunkStrategyRecommendation(name, capability?.notes)
      const strippedNotes = stripRecommendationPrefix(capability?.notes)
      return {
        value: name,
        label: base?.label || humanizeChunkStrategyValue(name),
        description: base?.description || strippedNotes || `${humanizeChunkStrategyValue(name)} 切块策略`,
        icon: base?.icon || (recommendation === 'integrated' ? 'integrated' : 'recursive'),
        badge: base?.badge,
        group: base?.group,
        disabled: base?.disabled,
        available: capability?.available,
        notes: capability?.notes,
        recommendation,
        recommendationLabel: getChunkStrategyRecommendationLabel(recommendation),
      } satisfies ChunkStrategyCatalogItem
    })
    .sort((a, b) => {
      const rec = RECOMMENDATION_ORDER[a.recommendation] - RECOMMENDATION_ORDER[b.recommendation]
      if (rec !== 0) return rec
      return a.label.localeCompare(b.label, 'zh-CN')
    })
}
