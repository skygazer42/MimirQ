'use client'

import { Fragment } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { SearchInput } from '@/components/ui/search-input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { WorkspaceNotice, WorkspaceNoticeStack } from '@/components/ui/operational-workspace'
import { SplitEmptyStudio } from '@/components/ui/split-empty-studio'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  Edit,
  Filter,
  Link2,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Prompts,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from '@/components/icons'
import type { PromptTemplate } from '@/lib/api/prompts'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { PROMPT_SCENARIOS, promptDate, promptPageNumbers, promptScenario } from './prompt-model'
import type { PromptsController } from './use-prompt-templates'
import styles from './prompts.module.css'

const CATEGORY_VALUE_PREFIX = 'category:'

const PROMPT_EMPTY_STEPS = [
  {
    index: '01',
    title: '内置场景模板',
    description: '覆盖问答生成、查询改写、知识图谱抽取与 RAG 评测',
  },
  {
    index: '02',
    title: '变量与场景绑定',
    description: '支持 {context}、{question} 等变量校验与场景生效配置',
  },
  {
    index: '03',
    title: '只读保护与派生',
    description: '内置模板只读，可复制为自定义模板',
  },
] as const

function PromptStudioIllustration() {
  return (
    <svg width="160" height="126" viewBox="0 0 160 126" fill="none" aria-hidden="true">
      <rect
        x="20"
        y="20"
        width="102"
        height="78"
        rx="10"
        fill="hsl(var(--card))"
        stroke="hsl(var(--border))"
        strokeWidth="1.25"
      />
      <line x1="20" y1="38" x2="122" y2="38" stroke="hsl(var(--border))" strokeWidth="1.25" />
      <circle cx="32" cy="29" r="2.2" fill="hsl(var(--muted-foreground) / 0.4)" />
      <circle cx="40" cy="29" r="2.2" fill="hsl(var(--muted-foreground) / 0.4)" />
      <circle cx="48" cy="29" r="2.2" fill="hsl(var(--muted-foreground) / 0.4)" />
      <path
        d="M34 54L41 60L34 66"
        stroke="hsl(var(--accent))"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <line
        x1="48"
        y1="60"
        x2="86"
        y2="60"
        stroke="hsl(var(--muted-foreground) / 0.55)"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <rect x="34" y="74" width="32" height="12" rx="4" fill="hsl(var(--muted))" />
      <line
        x1="41"
        y1="80"
        x2="59"
        y2="80"
        stroke="hsl(var(--muted-foreground) / 0.65)"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <rect x="72" y="74" width="34" height="12" rx="4" fill="hsl(var(--muted))" />
      <line
        x1="79"
        y1="80"
        x2="99"
        y2="80"
        stroke="hsl(var(--muted-foreground) / 0.45)"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <circle cx="122" cy="88" r="20" fill="hsl(var(--accent))" />
      <path
        d="M115 84L120 88L115 92"
        stroke="hsl(var(--accent-foreground))"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <line
        x1="123"
        y1="92"
        x2="130"
        y2="92"
        stroke="hsl(var(--accent-foreground))"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function PromptStatus({ template }: { template: PromptTemplate }) {
  return (
    <span className={cn(styles.status, template.is_active ? styles.enabled : styles.disabled)}>
      <i aria-hidden="true" />
      {template.is_active ? '启用' : '停用'}
    </span>
  )
}
export function PromptVariables({
  variables,
  limit = variables.length,
}: {
  variables: readonly string[]
  limit?: number
}) {
  if (!variables.length) return <span className={styles.muted}>—</span>
  return (
    <span className={styles.variables}>
      {variables.slice(0, limit).map((v) => (
        <code key={v} className={styles.variable} title={`{${v}}`}>{`{${v}}`}</code>
      ))}
      {variables.length > limit ? (
        <span
          className={styles.moreVariables}
          title={variables
            .slice(limit)
            .map((v) => `{${v}}`)
            .join(', ')}
        >
          +{variables.length - limit}
        </span>
      ) : null}
    </span>
  )
}

function PromptActions({ template, controller }: { template: PromptTemplate; controller: PromptsController }) {
  return (
    <div className={styles.rowActions}>
      <Button
        variant="ghost"
        className={styles.previewButton}
        onClick={() => controller.openPreview(template)}
        aria-label={`预览 ${template.name}`}
      >
        预览
      </Button>
      {controller.canManage ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className={styles.moreButton}
              disabled={controller.busy !== ''}
              aria-label={`更多操作 ${template.name}`}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className={styles.menu}
            onCloseAutoFocus={(event) => {
              if (controller.editorOpen || controller.preview !== null || controller.deleteTargets.length > 0) {
                event.preventDefault()
              }
            }}
          >
            <DropdownMenuItem onSelect={() => controller.openPreview(template)}>阅读模板</DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                void controller.duplicate(template)
              }}
            >
              <Copy />
              复制为自定义模板
            </DropdownMenuItem>
            {!template.is_system ? (
              <>
                <DropdownMenuItem onSelect={() => controller.openEditor(template)}>
                  <Edit />
                  编辑模板
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => {
                    void controller.toggleActive(template)
                  }}
                >
                  {template.is_active ? '停用模板' : '启用模板'}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem className={styles.dangerText} onSelect={() => controller.openDelete([template])}>
                  <Trash2 />
                  删除模板
                </DropdownMenuItem>
              </>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  )
}

export function PromptTable({
  controller,
  hasFilters,
  quietEmpty,
}: {
  controller: PromptsController
  hasFilters: boolean
  quietEmpty: boolean
}) {
  const category = controller.filters.category
  const hasTemplates = controller.query.data !== undefined
  const waitingForNetwork = controller.query.isPending && controller.query.isPaused
  const pageNumbers = promptPageNumbers(controller.currentPage, controller.totalPages)
  const activeCount = controller.templates.filter((t) => t.is_active).length
  return (
    <>
      {!quietEmpty ? (
        <Tabs
          value={controller.filters.scenario}
          onValueChange={(value) => {
            const scenario = PROMPT_SCENARIOS.find((item) => item.key === value)
            if (scenario !== undefined) controller.changeFilter('scenario', scenario.key)
          }}
          className={styles.scenarios}
        >
          <TabsList aria-label="提示词场景" className={styles.tabs}>
            {PROMPT_SCENARIOS.filter((s) => s.key !== 'other' || controller.counts.other > 0).map((s) => (
              <TabsTrigger key={s.key} value={s.key} className={styles.tab}>
                {s.label}
                {hasTemplates && !quietEmpty ? <span>{controller.counts[s.key]}</span> : null}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      ) : null}
      {!quietEmpty ? (
        <div className={styles.toolbar}>
          <SearchInput
            aria-label="搜索模板"
            value={controller.filters.query}
            onValueChange={(value) => controller.changeFilter('query', value)}
            placeholder="搜索名称、内容或标签"
            containerClassName={styles.search}
            inputClassName={styles.searchInput}
          />
          <div className={styles.filters}>
            <Select
              value={controller.filters.status}
              onValueChange={(value) => controller.changeFilter('status', value as typeof controller.filters.status)}
            >
              <SelectTrigger aria-label="模板状态" className={styles.filterSelect}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="active">已启用</SelectItem>
                <SelectItem value="inactive">已停用</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={controller.filters.source}
              onValueChange={(value) => controller.changeFilter('source', value as typeof controller.filters.source)}
            >
              <SelectTrigger aria-label="模板来源" className={styles.filterSelect}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部来源</SelectItem>
                <SelectItem value="system">内置模板</SelectItem>
                <SelectItem value="custom">自定义模板</SelectItem>
              </SelectContent>
            </Select>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="更多筛选与排序"
                  className={cn(styles.filterButton, category !== null && styles.filterActive)}
                >
                  <Filter />
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className={styles.filterPopover}>
                <div>
                  <Label htmlFor="prompt-category-filter">分类</Label>
                  <Select
                    value={category === null ? 'all' : `${CATEGORY_VALUE_PREFIX}${category}`}
                    onValueChange={(value) =>
                      controller.changeFilter(
                        'category',
                        value === 'all' ? null : value.slice(CATEGORY_VALUE_PREFIX.length),
                      )
                    }
                  >
                    <SelectTrigger id="prompt-category-filter" aria-label="模板分类">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全部分类</SelectItem>
                      {controller.categories.map((category) => (
                        <SelectItem key={category} value={`${CATEGORY_VALUE_PREFIX}${category}`}>
                          {category}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label htmlFor="prompt-order">排序</Label>
                  <Select
                    value={controller.filters.sort}
                    onValueChange={(value) => controller.changeFilter('sort', value as typeof controller.filters.sort)}
                  >
                    <SelectTrigger id="prompt-order" aria-label="模板排序">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="updated">最近更新</SelectItem>
                      <SelectItem value="name">名称 A–Z</SelectItem>
                      <SelectItem value="usage">使用次数最多</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {hasFilters ? (
                  <Button variant="ghost" onClick={controller.clearFilters}>
                    清除筛选
                  </Button>
                ) : null}
              </PopoverContent>
            </Popover>
            {category !== null ? (
              <Button
                variant="ghost"
                className={styles.categoryChip}
                onClick={() => controller.changeFilter('category', null)}
                title="清除分类筛选"
              >
                {category}
                <X />
              </Button>
            ) : null}
          </div>
          {controller.query.isLoading || controller.query.isFetching ? (
            <span className={styles.collectionCount} role="status">
              {controller.query.isLoading ? '加载中' : '正在更新'}
            </span>
          ) : null}
        </div>
      ) : null}
      {controller.selectedCount > 0 ? (
        <div className={styles.selectionBar} role="region" aria-label="批量操作">
          <span>已选择 {controller.selectedCount} 个模板</span>
          {controller.selectedCount > controller.selectedPageCount ? <small>含其他页的选择</small> : null}
          <div>
            <Button
              variant="ghost"
              disabled={Boolean(controller.busy)}
              onClick={() => {
                void controller.batchActive(true)
              }}
            >
              批量启用
            </Button>
            <Button
              variant="ghost"
              disabled={Boolean(controller.busy)}
              onClick={() => {
                void controller.batchActive(false)
              }}
            >
              批量停用
            </Button>
            <Button
              variant="ghost"
              className={styles.dangerText}
              disabled={Boolean(controller.busy)}
              onClick={() => controller.openDelete(controller.selectedTemplates)}
            >
              批量删除
            </Button>
            <Button
              variant="ghost"
              size="icon"
              disabled={Boolean(controller.busy)}
              aria-label="取消选择"
              onClick={controller.clearSelection}
            >
              <X />
            </Button>
          </div>
        </div>
      ) : null}
      {(controller.actionError && !controller.editorOpen && !controller.deleteTargets.length) ||
      (controller.query.isError && controller.templates.length > 0) ? (
        <WorkspaceNoticeStack>
          {controller.actionError && !controller.editorOpen && !controller.deleteTargets.length ? (
            <WorkspaceNotice tone="error" onDismiss={() => controller.setActionError('')} dismissLabel="关闭操作错误">
              {controller.actionError}
            </WorkspaceNotice>
          ) : null}
          {controller.query.isError && controller.templates.length > 0 ? (
            <WorkspaceNotice
              tone="warning"
              title="列表更新失败"
              error={controller.query.error}
              fallbackMessage="请重试"
              retry={() => {
                void controller.query.refetch()
              }}
              retryLabel="重试"
              pending={controller.query.isFetching}
            />
          ) : null}
        </WorkspaceNoticeStack>
      ) : null}
      {quietEmpty ? (
        <SplitEmptyStudio
          illustration={<PromptStudioIllustration />}
          title="还没有提示词模板"
          description={
            controller.canManage
              ? '同步内置模板或新建自定义模板。'
              : '等待管理员添加模板。'
          }
          actions={
            controller.canManage ? (
              <>
                <Button
                  className={styles.primary}
                  disabled={Boolean(controller.busy)}
                  onClick={() => {
                    void controller.syncBuiltins()
                  }}
                >
                  {controller.busy === 'sync' ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                  {controller.busy === 'sync' ? '同步中' : '同步内置模板'}
                </Button>
                <Button variant="outline" disabled={Boolean(controller.busy)} onClick={() => controller.openEditor()}>
                  <Plus />
                  创建模板
                </Button>
              </>
            ) : undefined
          }
          stepsHeading="提示词管理能力"
          steps={PROMPT_EMPTY_STEPS}
          shortcutsHeading="常用入口"
          shortcuts={
            controller.canManage
              ? [
                  {
                    key: 'prompt-bindings',
                    icon: <Link2 />,
                    title: '场景绑定',
                    description: '查看问答、图谱与评测各环节的默认模板',
                    onClick: controller.openBindings,
                  },
                  {
                    key: 'prompt-evaluations',
                    icon: <CheckCircle2 />,
                    title: 'RAG 评测',
                    description: '对比不同提示词下的问答忠实度与相关性',
                    href: '/evaluations',
                  },
                ]
              : [
                  {
                    key: 'prompt-chat',
                    icon: <MessageSquare />,
                    title: '前往知识问答',
                    description: '使用当前生效提示词发起知识问答',
                    href: '/',
                  },
                  {
                    key: 'prompt-evaluations',
                    icon: <CheckCircle2 />,
                    title: 'RAG 评测',
                    description: '查看问答质量与检索指标',
                    href: '/evaluations',
                  },
                ]
          }
        />
      ) : (
        <div className={styles.tableScroll} aria-busy={controller.query.isFetching}>
          <div className={styles.tableFrame}>
            <table className={styles.table} aria-label="提示词模板">
              <colgroup>
                <col className={styles.checkColumn} />
                <col className={styles.nameColumn} />
                <col className={styles.sceneColumn} />
                <col className={styles.sourceColumn} />
                <col className={styles.variablesColumn} />
                <col className={styles.usageColumn} />
                <col className={styles.dateColumn} />
                <col className={styles.statusColumn} />
                <col className={styles.actionsColumn} />
              </colgroup>
              <thead>
                <tr>
                  <th className={styles.checkColumn}>
                    <Checkbox
                      aria-label="选择本页自定义模板"
                      title="仅选择本页可编辑的自定义模板"
                      disabled={!controller.canManage || !controller.selectablePage.length || Boolean(controller.busy)}
                      checked={
                        controller.selectedPageCount === 0
                          ? false
                          : controller.selectedPageCount === controller.selectablePage.length
                            ? true
                            : 'indeterminate'
                      }
                      onCheckedChange={controller.togglePage}
                    />
                  </th>
                  <th className={styles.nameColumn} scope="col">
                    模板名称
                  </th>
                  <th className={styles.sceneColumn} scope="col">
                    场景
                  </th>
                  <th className={styles.sourceColumn} scope="col">
                    来源
                  </th>
                  <th className={styles.variablesColumn} scope="col">
                    变量
                  </th>
                  <th className={styles.usageColumn} scope="col">
                    使用次数
                  </th>
                  <th className={styles.dateColumn} scope="col">
                    更新时间
                  </th>
                  <th className={styles.statusColumn} scope="col">
                    状态
                  </th>
                  <th className={styles.actionsColumn} scope="col">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody>
                {controller.query.isLoading
                  ? Array.from({ length: 8 }, (_, i) => (
                      <tr key={i} aria-hidden="true">
                        <td colSpan={9} className={styles.skeletonCell}>
                          <div className={styles.skeleton} />
                        </td>
                      </tr>
                    ))
                  : controller.pageItems.map((template) => {
                      const scene = promptScenario(template.category)
                      return (
                        <tr
                          key={template.id}
                          data-selected={controller.selectedIds.has(template.id) ? true : undefined}
                        >
                          <td className={styles.checkColumn}>
                            <Checkbox
                              checked={controller.selectedIds.has(template.id)}
                              disabled={!controller.canManage || template.is_system || Boolean(controller.busy)}
                              title={template.is_system ? '内置模板只读，复制后可修改' : undefined}
                              aria-label={`选择 ${template.name}`}
                              onCheckedChange={() => controller.toggleOne(template)}
                            />
                          </td>
                          <td className={styles.nameColumn}>
                            <div className={styles.templateIdentity}>
                              <span className={cn(styles.objectIcon, styles[scene.tone])} aria-hidden="true">
                                <Prompts />
                              </span>
                              <div>
                                <button
                                  className={styles.nameButton}
                                  data-prompt-open={template.id}
                                  onClick={() => controller.openPreview(template)}
                                  title={template.name}
                                >
                                  {template.name}
                                </button>
                                {template.description ? (
                                  <p className={styles.templateDescription} title={template.description}>
                                    {template.description}
                                  </p>
                                ) : null}
                                <span className={styles.mobileMeta}>
                                  {scene.label} · {template.is_system ? '内置' : '自定义'}
                                </span>
                              </div>
                            </div>
                          </td>
                          <td className={styles.sceneColumn}>
                            <span className={cn(styles.sceneLabel, styles[scene.tone])}>
                              <i aria-hidden="true" />
                              {scene.label}
                            </span>
                          </td>
                          <td className={styles.sourceColumn}>
                            <span className={template.is_system ? styles.builtinSource : styles.customSource}>
                              {template.is_system ? '内置' : '自定义'}
                            </span>
                          </td>
                          <td className={styles.variablesColumn}>
                            <PromptVariables variables={template.variables} limit={2} />
                          </td>
                          <td className={styles.usageColumn}>{template.usage_count.toLocaleString()}</td>
                          <td className={styles.dateColumn}>
                            <time dateTime={template.updated_at} title={promptDate(template.updated_at, true)}>
                              {promptDate(template.updated_at)}
                            </time>
                          </td>
                          <td className={styles.statusColumn}>
                            <PromptStatus template={template} />
                          </td>
                          <td className={styles.actionsColumn}>
                            <PromptActions template={template} controller={controller} />
                          </td>
                        </tr>
                      )
                    })}
              </tbody>
            </table>
          </div>
          {!controller.query.isLoading && !controller.pageItems.length ? (
            <section className={styles.empty}>
              {controller.query.isError ? (
                <>
                  <h2>提示词加载失败</h2>
                  <p role="alert">{formatApiError(controller.query.error, '请重试')}</p>
                  <Button
                    variant="outline"
                    disabled={controller.query.isFetching}
                    onClick={() => {
                      void controller.query.refetch()
                    }}
                  >
                    <RefreshCw />
                    重新加载
                  </Button>
                </>
              ) : waitingForNetwork ? (
                <h2>等待网络连接</h2>
              ) : hasFilters ? (
                <>
                  <h2>没有匹配的模板</h2>
                  <p>调整搜索或筛选条件后再试。</p>
                  <Button variant="outline" onClick={controller.clearFilters}>
                    清除筛选
                  </Button>
                </>
              ) : null}
            </section>
          ) : null}
        </div>
      )}
      {hasTemplates && !quietEmpty ? (
        <footer className={styles.footer}>
          <span className={styles.resultCount}>
            {hasFilters
              ? `找到 ${controller.filtered.length} 个 / 全部 ${controller.templates.length} 个`
              : `共 ${controller.templates.length} 个模板 · ${activeCount} 个启用`}
          </span>
          <div className={styles.pagination}>
            <Select
              value={String(controller.pageSize)}
              onValueChange={(value) => controller.changePageSize(Number(value))}
            >
              <SelectTrigger aria-label="每页模板数" className={styles.pageSize}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[20, 50, 100].map((size) => (
                  <SelectItem key={size} value={String(size)}>
                    {size} 条 / 页
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="icon"
              aria-label="上一页"
              disabled={controller.currentPage <= 1}
              onClick={() => controller.setPage(controller.currentPage - 1)}
            >
              <ChevronLeft />
            </Button>
            <div className={styles.pageNumbers}>
              {pageNumbers.map((page, i) => (
                <Fragment key={page}>
                  {i > 0 && page - pageNumbers[i - 1] > 1 ? <span>…</span> : null}
                  <Button
                    variant="ghost"
                    aria-label={`第 ${page} 页`}
                    aria-current={controller.currentPage === page ? 'page' : undefined}
                    className={controller.currentPage === page ? styles.currentPage : undefined}
                    onClick={() => controller.setPage(page)}
                  >
                    {page}
                  </Button>
                </Fragment>
              ))}
            </div>
            <span className={styles.mobilePage}>
              第 {controller.currentPage} / {controller.totalPages} 页
            </span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="下一页"
              disabled={controller.currentPage >= controller.totalPages}
              onClick={() => controller.setPage(controller.currentPage + 1)}
            >
              <ChevronRight />
            </Button>
          </div>
        </footer>
      ) : null}
    </>
  )
}
