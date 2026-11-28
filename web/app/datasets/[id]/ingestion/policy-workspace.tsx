'use client'

import { useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  BarChart3,
  FileSearch,
  Heart,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Settings2,
  Table2,
  Trash2,
} from '@/components/icons'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { WorkspaceNotice, WorkspaceNoticeStack } from '@/components/ui/operational-workspace'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Switch } from '@/components/ui/switch'
import { useRouter } from '@/i18n/navigation'
import { getParserLabel } from '@/lib/parser-options'
import { getDatasetDomainTone } from '@/lib/dataset-domain-tone'
import { useIngestionPolicy, type IngestionPolicyController } from './use-ingestion-policy'
import { PolicyRuleEditor, PolicyTemplateDialog } from './policy-dialogs'
import { PolicyOverviewDialog, PolicyPreviewDialog } from './policy-preview'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import styles from './policy.module.css'

function RulesTable({ policyController }: { policyController: IngestionPolicyController }) {
  return (
    <div className={styles.tableScroll} aria-label="规则列表滚动区域" tabIndex={0}>
      <table className={styles.table} aria-label="入库规则">
        <thead>
          <tr>
            <th scope="col">顺序</th>
            <th scope="col">规则与匹配条件</th>
            <th scope="col" className={styles.processingColumn}>
              解析与切块
            </th>
            <th scope="col" className={styles.profileColumn}>
              治理预设
            </th>
            <th scope="col">启用</th>
            <th scope="col">
              <span className="sr-only">操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {policyController.rules.map((rule, index) => {
            const parser = rule.parser_backend == null ? '使用默认解析器' : getParserLabel(rule.parser_backend)
            const profile = policyController.profilesQuery.data?.items?.find(
              (item) => item.key === rule.governance_profile_ref || item.id === rule.governance_profile_ref,
            )
            return (
              <tr key={rule.id} data-rule-id={rule.id} data-enabled={rule.enabled}>
                <td className={styles.order}>{index + 1}</td>
                <th scope="row">
                  <button
                    className={styles.ruleName}
                    aria-label={`编辑规则 ${rule.name}`}
                    disabled={policyController.blocked}
                    onClick={(event) => policyController.openEditor(rule, event.currentTarget)}
                  >
                    {rule.name}
                  </button>
                  <div className={`${styles.match} ${styles.semanticPill}`} data-tone="source">
                    {rule.match?.extensions?.length ? rule.match.extensions.join(' · ') : '任意文件类型'}
                  </div>
                  {rule.match?.filename_regex ? (
                    <div className={styles.regex} title={rule.match.filename_regex}>
                      文件名：<code>{rule.match.filename_regex}</code>
                    </div>
                  ) : null}
                </th>
                <td className={styles.processingColumn}>
                  <span className={styles.semanticPill} data-tone="process">
                    {parser}
                  </span>
                  <small>
                    {rule.chunk_strategy || '使用默认切块策略'}
                    {rule.preprocess?.enabled ? ` · 预处理 ${rule.preprocess.steps?.length ?? 0} 项` : ''}
                  </small>
                </td>
                <td className={styles.profileColumn}>
                  <span
                    className={styles.semanticPill}
                    data-tone={rule.governance_profile_ref ? 'governance' : undefined}
                  >
                    {profile?.name ?? rule.governance_profile_ref ?? '不使用预设'}
                  </span>
                  {rule.pipeline_patch && Object.keys(rule.pipeline_patch).length ? (
                    <small className={styles.semanticPill} data-tone="process">
                      参数覆盖 {Object.keys(rule.pipeline_patch).length} 项
                    </small>
                  ) : null}
                </td>
                <td>
                  <Switch
                    aria-label={`启用规则 ${rule.name}`}
                    checked={rule.enabled}
                    disabled={policyController.blocked}
                    onCheckedChange={(enabled) =>
                      policyController.changeRules(
                        policyController.rules.map((item) => (item.id === rule.id ? { ...item, enabled } : item)),
                      )
                    }
                  />
                </td>
                <td>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        data-rule-menu={rule.id}
                        aria-label={`规则操作 ${rule.name}`}
                        disabled={policyController.blocked}
                      >
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="end"
                      className={styles.rowMenu}
                      onCloseAutoFocus={(event) => {
                        if (policyController.editor) event.preventDefault()
                      }}
                    >
                      <DropdownMenuItem
                        onSelect={() => {
                          const trigger = document.querySelector<HTMLElement>(`[data-rule-menu="${rule.id}"]`)
                          if (trigger) policyController.openEditor(rule, trigger)
                        }}
                      >
                        <Pencil />
                        编辑规则
                      </DropdownMenuItem>
                      <DropdownMenuItem disabled={index === 0} onSelect={() => policyController.moveRule(rule.id, -1)}>
                        <ArrowUp />
                        上移一位
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        disabled={index === policyController.rules.length - 1}
                        onSelect={() => policyController.moveRule(rule.id, 1)}
                      >
                        <ArrowDown />
                        下移一位
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        className="text-destructive"
                        onSelect={() => policyController.removeRule(rule.id)}
                      >
                        <Trash2 />
                        移除规则
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function PolicyWorkspace({ datasetId }: { datasetId: string }) {
  const policyController = useIngestionPolicy(datasetId)
  const router = useRouter()
  const menuTrigger = useRef<HTMLButtonElement | null>(null)
  const [pendingNavigation, setPendingNavigation] = useState<string | null>(null)
  function navigate(path: string, trigger = menuTrigger.current) {
    if (policyController.dirty) {
      if (trigger) policyController.captureFocus(trigger)
      setPendingNavigation(path)
      policyController.setDiscardOpen(true)
    } else router.push(path)
  }
  return (
    <AppFrame>
      <section className={styles.workspace} data-policy-workspace>
        <header className={styles.header}>
          <Button
            variant="ghost"
            size="icon"
            className={styles.back}
            aria-label="返回数据集"
            disabled={policyController.saving || policyController.previewing}
            onClick={(event) => navigate('/datasets', event.currentTarget)}
          >
            <ArrowLeft />
          </Button>
          <div className={styles.titleGroup}>
            <div className={styles.heading}>
              <PageTitleIcon name="ingestion-operation" />
              <h1>入库策略</h1>
            </div>
            <span
              className={styles.datasetContext}
              title={policyController.datasetQuery.data?.name}
              data-tone={
                policyController.datasetQuery.data
                  ? getDatasetDomainTone(policyController.datasetQuery.data)
                  : undefined
              }
            >
              {policyController.datasetQuery.data?.name ??
                (policyController.datasetQuery.isPending ? '正在读取数据集…' : '数据集未取得')}
            </span>
          </div>
          <div className={styles.headerActions}>
            <Button
              variant="outline"
              aria-label="预览文件"
              disabled={!policyController.policy || policyController.policyQuery.isError}
              onClick={(event) => {
                policyController.captureFocus(event.currentTarget)
                policyController.setPreviewOpen(true)
              }}
            >
              <FileSearch />
              <span>预览文件</span>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  ref={menuTrigger}
                  variant="ghost"
                  size="icon"
                  aria-label="数据集操作"
                  disabled={policyController.saving || policyController.previewing}
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                onCloseAutoFocus={(event) => {
                  if (policyController.overviewOpen || policyController.discardOpen) event.preventDefault()
                }}
              >
                <DropdownMenuItem
                  onSelect={() => {
                    if (menuTrigger.current) policyController.captureFocus(menuTrigger.current)
                    policyController.setOverviewOpen(true)
                  }}
                >
                  <BarChart3 />
                  入库概览
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => navigate(`/datasets/${datasetId}/health`)}>
                  <Heart />
                  健康概览
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => navigate(`/datasets/${datasetId}/precheck`)}>
                  <FileSearch />
                  文档预检
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => navigate(`/datasets/${datasetId}/profile`)}>
                  <BarChart3 />
                  数据画像
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => navigate(`/datasets/${datasetId}/tables`)}>
                  <Table2 />
                  表格资产
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  disabled={
                    policyController.dirty || policyController.saving || policyController.policyQuery.isFetching
                  }
                  onSelect={() => {
                    void policyController.policyQuery.refetch()
                  }}
                >
                  <RefreshCw />
                  重新读取策略
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <div className={styles.toolbar}>
          <div className={styles.listHeading}>
            <h2>匹配规则</h2>
            {policyController.policy ? <span>{policyController.rules.length} 条</span> : null}
          </div>
          <p className={styles.matchHint}>从上到下匹配，采用第一条命中的启用规则。</p>
          <span className={styles.spacer} />
          <Button
            variant="outline"
            aria-label="从模板添加"
            disabled={policyController.blocked}
            onClick={(event) => {
              policyController.captureFocus(event.currentTarget)
              policyController.setTemplatesOpen(true)
            }}
          >
            <Settings2 />
            <span>从模板添加</span>
          </Button>
          <Button
            variant="outline"
            data-policy-add
            className={styles.primaryAction}
            aria-label="新增规则"
            disabled={policyController.blocked || policyController.rules.length >= 60}
            onClick={(event) => policyController.openEditor(null, event.currentTarget)}
          >
            <Plus />
            <span>新增规则</span>
          </Button>
        </div>
        <WorkspaceNoticeStack ariaLabel="入库策略状态提示">
          {policyController.datasetQuery.isError ? (
            <WorkspaceNotice
              error={policyController.datasetQuery.error}
              fallbackMessage="数据集读取失败"
              retry={() => void policyController.datasetQuery.refetch()}
              retryLabel="重新读取数据集"
            />
          ) : null}
          {policyController.policyQuery.isError ? (
            <WorkspaceNotice
              title={policyController.policy ? '策略更新失败，保留上次数据' : '策略读取失败'}
              error={policyController.policyQuery.error}
              fallbackMessage="无法读取入库策略"
              retry={() => void policyController.policyQuery.refetch()}
              retryLabel="重新读取策略"
              pending={policyController.policyQuery.isFetching}
            />
          ) : null}
          {policyController.saveError ? (
            <WorkspaceNotice
              retry={() => void policyController.save()}
              retryLabel="重试保存"
              retryDisabled={policyController.blocked}
            >
              {policyController.saveError}，修改已保留。
            </WorkspaceNotice>
          ) : null}
        </WorkspaceNoticeStack>
        {policyController.policyQuery.isPending ? (
          <div className={styles.empty} role="status">
            <Loader2 className="animate-spin motion-reduce:animate-none" />
            <p>正在读取入库策略…</p>
          </div>
        ) : policyController.rules.length ? (
          <RulesTable policyController={policyController} />
        ) : policyController.policy && !policyController.policyQuery.isError ? (
          <div className={styles.empty}>
            <Settings2 />
            <h2>还没有匹配规则</h2>
            <p>未命中的文件沿用默认处理配置。</p>
            <Button
              variant="ghost"
              disabled={policyController.blocked}
              onClick={(event) => {
                policyController.captureFocus(event.currentTarget)
                policyController.setTemplatesOpen(true)
              }}
            >
              从模板添加规则
            </Button>
          </div>
        ) : (
          <div className={styles.remainingSpace} />
        )}
        <footer className={styles.footer} data-task-center-dock>
          <span className={styles.saveState} aria-live="polite">
            {policyController.saving
              ? '正在保存…'
              : policyController.dirty
                ? '有未保存的修改'
                : policyController.policyQuery.isError
                  ? '策略读取失败'
                  : policyController.policy
                    ? '已保存'
                    : '尚未读取策略'}
          </span>
          <span className={styles.spacer} />
          {policyController.dirty ? (
            <Button
              variant="ghost"
              disabled={policyController.saving || policyController.previewing}
              onClick={(event) => {
                policyController.captureFocus(event.currentTarget)
                setPendingNavigation(null)
                policyController.setDiscardOpen(true)
              }}
            >
              放弃修改
            </Button>
          ) : null}
          <Button
            disabled={!policyController.dirty || policyController.blocked}
            aria-label="保存策略"
            className={styles.primaryAction}
            onClick={() => {
              void policyController.save()
            }}
          >
            {policyController.saving ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : null}
            {policyController.saving ? '保存中' : '保存策略'}
          </Button>
        </footer>
        {policyController.editor !== null ? (
          <PolicyRuleEditor editor={policyController.editor} policyController={policyController} />
        ) : null}
        {policyController.templatesOpen ? <PolicyTemplateDialog policyController={policyController} /> : null}
        {policyController.previewOpen ? <PolicyPreviewDialog policyController={policyController} /> : null}
        {policyController.overviewOpen ? <PolicyOverviewDialog policyController={policyController} /> : null}
        <AlertDialog
          open={policyController.discardOpen}
          onOpenChange={(open) => {
            policyController.setDiscardOpen(open)
            if (!open) setPendingNavigation(null)
          }}
        >
          <AlertDialogContent
            className={styles.confirmDialog}
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              policyController.restoreFocus()
            }}
          >
            <AlertDialogHeader className={styles.dialogHeader}>
              <AlertDialogTitle>放弃未保存的修改？</AlertDialogTitle>
              <AlertDialogDescription>
                {pendingNavigation ? '离开后，当前未保存的规则修改将丢失。' : '规则将恢复为最近读取的已保存策略。'}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <div className={styles.dialogFooter}>
              <Button
                variant="ghost"
                onClick={() => {
                  policyController.setDiscardOpen(false)
                  setPendingNavigation(null)
                }}
              >
                继续编辑
              </Button>
              <Button
                variant="destructive"
                onClick={() => {
                  const target = pendingNavigation
                  policyController.discard()
                  setPendingNavigation(null)
                  if (target) router.push(target)
                }}
              >
                {pendingNavigation ? '放弃并离开' : '放弃修改'}
              </Button>
            </div>
          </AlertDialogContent>
        </AlertDialog>
      </section>
    </AppFrame>
  )
}
