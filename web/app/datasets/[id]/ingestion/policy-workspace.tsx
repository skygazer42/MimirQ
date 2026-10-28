'use client'

import { useRef, useState } from 'react'
import { ArrowDown, ArrowLeft, ArrowUp, BarChart3, FileSearch, Heart, Loader2, MoreHorizontal, Pencil, Plus, RefreshCw, Settings2, Table2, Trash2 } from '@/components/icons'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Switch } from '@/components/ui/switch'
import { useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { PARSER_BACKEND_REGISTRY_OPTIONS } from '@/lib/parser-options'
import { useIngestionPolicy, type IngestionPolicyController } from './use-ingestion-policy'
import { PolicyRuleEditor, PolicyTemplateDialog } from './policy-dialogs'
import { PolicyOverviewDialog, PolicyPreviewDialog } from './policy-preview'
import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import styles from './policy.module.css'

function RulesTable({ c }: { c: IngestionPolicyController }) {
  return <div className={styles.tableScroll} aria-label="规则列表滚动区域" tabIndex={0}><table className={styles.table} aria-label="入库规则"><thead><tr><th scope="col">顺序</th><th scope="col">规则与匹配条件</th><th scope="col" className={styles.processingColumn}>解析与切块</th><th scope="col" className={styles.profileColumn}>治理预设</th><th scope="col">启用</th><th scope="col"><span className="sr-only">操作</span></th></tr></thead><tbody>
    {c.rules.map((rule, index) => {
      const parser = PARSER_BACKEND_REGISTRY_OPTIONS.find(option => option.value === rule.parser_backend)?.label ?? rule.parser_backend ?? '使用默认解析器'
      const profile = c.profilesQuery.data?.items?.find(item => item.key === rule.governance_profile_ref || item.id === rule.governance_profile_ref)
      return <tr key={rule.id} data-rule-id={rule.id} data-enabled={rule.enabled}>
        <td className={styles.order}>{index + 1}</td>
        <th scope="row"><button className={styles.ruleName} aria-label={`编辑规则 ${rule.name}`} disabled={c.blocked} onClick={event => c.openEditor(rule, event.currentTarget)}>{rule.name}</button><div className={styles.match}>{rule.match?.extensions?.length ? rule.match.extensions.join(' · ') : '任意文件类型'}</div>{rule.match?.filename_regex ? <div className={styles.regex} title={rule.match.filename_regex}>文件名：<code>{rule.match.filename_regex}</code></div> : null}</th>
        <td className={styles.processingColumn}><span>{parser}</span><small>{rule.chunk_strategy || '使用默认切块策略'}{rule.preprocess?.enabled ? ` · 预处理 ${rule.preprocess.steps?.length ?? 0} 项` : ''}</small></td>
        <td className={styles.profileColumn}><span>{profile?.name ?? rule.governance_profile_ref ?? '不使用预设'}</span>{rule.pipeline_patch && Object.keys(rule.pipeline_patch).length ? <small>参数覆盖 {Object.keys(rule.pipeline_patch).length} 项</small> : null}</td>
        <td><Switch aria-label={`启用规则 ${rule.name}`} checked={rule.enabled} disabled={c.blocked} onCheckedChange={enabled => c.changeRules(c.rules.map(item => item.id === rule.id ? { ...item, enabled } : item))} /></td>
        <td><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" data-rule-menu={rule.id} aria-label={`规则操作 ${rule.name}`} disabled={c.blocked}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className={styles.rowMenu} onCloseAutoFocus={event => { if (c.editor) event.preventDefault() }}>
          <DropdownMenuItem onSelect={() => { const trigger = document.querySelector<HTMLElement>(`[data-rule-menu="${rule.id}"]`); if (trigger) c.openEditor(rule, trigger) }}><Pencil />编辑规则</DropdownMenuItem>
          <DropdownMenuItem disabled={index === 0} onSelect={() => c.moveRule(rule.id, -1)}><ArrowUp />上移一位</DropdownMenuItem>
          <DropdownMenuItem disabled={index === c.rules.length - 1} onSelect={() => c.moveRule(rule.id, 1)}><ArrowDown />下移一位</DropdownMenuItem>
          <DropdownMenuSeparator /><DropdownMenuItem className="text-destructive" onSelect={() => c.removeRule(rule.id)}><Trash2 />移除规则</DropdownMenuItem>
        </DropdownMenuContent></DropdownMenu></td>
      </tr>
    })}
  </tbody></table></div>
}

export default function PolicyWorkspace({ datasetId }: { datasetId: string }) {
  const c = useIngestionPolicy(datasetId), router = useRouter()
  const menuTrigger = useRef<HTMLButtonElement | null>(null)
  const [pendingNavigation, setPendingNavigation] = useState<string | null>(null)
  function navigate(path: string, trigger = menuTrigger.current) {
    if (c.dirty) { if (trigger) c.captureFocus(trigger); setPendingNavigation(path); c.setDiscardOpen(true) }
    else router.push(path)
  }
  return <AppFrame><section className={styles.workspace} data-policy-workspace>
    <header className={styles.header}><Button variant="ghost" size="icon" className={styles.back} aria-label="返回数据集" disabled={c.saving || c.previewing} onClick={event => navigate('/datasets', event.currentTarget)}><ArrowLeft /></Button><div className={styles.titleGroup}><div className={styles.heading}><PageTitleIcon name="ingestion-operation" /><h1>入库策略</h1></div><span className={styles.datasetContext} title={c.datasetQuery.data?.name}>{c.datasetQuery.data?.name ?? (c.datasetQuery.isPending ? '正在读取数据集…' : '数据集未取得')}</span></div><div className={styles.headerActions}>
      <Button variant="outline" aria-label="预览文件" disabled={!c.policy || c.policyQuery.isError} onClick={event => { c.captureFocus(event.currentTarget); c.setPreviewOpen(true) }}><FileSearch /><span>预览文件</span></Button>
      <DropdownMenu><DropdownMenuTrigger asChild><Button ref={menuTrigger} variant="ghost" size="icon" aria-label="数据集操作" disabled={c.saving || c.previewing}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" onCloseAutoFocus={event => { if (c.overviewOpen || c.discardOpen) event.preventDefault() }}>
        <DropdownMenuItem onSelect={() => { if (menuTrigger.current) c.captureFocus(menuTrigger.current); c.setOverviewOpen(true) }}><BarChart3 />入库概览</DropdownMenuItem><DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate(`/datasets/${datasetId}/health`)}><Heart />健康概览</DropdownMenuItem><DropdownMenuItem onSelect={() => navigate(`/datasets/${datasetId}/precheck`)}><FileSearch />文档预检</DropdownMenuItem><DropdownMenuItem onSelect={() => navigate(`/datasets/${datasetId}/profile`)}><BarChart3 />数据画像</DropdownMenuItem><DropdownMenuItem onSelect={() => navigate(`/datasets/${datasetId}/tables`)}><Table2 />表格资产</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem disabled={c.dirty || c.saving || c.policyQuery.isFetching} onSelect={() => { void c.policyQuery.refetch() }}><RefreshCw />重新读取策略</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu>
    </div></header>
    <div className={styles.toolbar}><div className={styles.listHeading}><h2>匹配规则</h2>{c.policy ? <span>{c.rules.length} 条</span> : null}</div><p className={styles.matchHint}>从上到下匹配，采用第一条命中的启用规则。</p><span className={styles.spacer} /><Button variant="outline" aria-label="从模板添加" disabled={c.blocked} onClick={event => { c.captureFocus(event.currentTarget); c.setTemplatesOpen(true) }}><Settings2 /><span>从模板添加</span></Button><Button variant="outline" data-policy-add aria-label="新增规则" disabled={c.blocked || c.rules.length >= 60} onClick={event => c.openEditor(null, event.currentTarget)}><Plus /><span>新增规则</span></Button></div>
    {c.datasetQuery.isError ? <div role="alert" className={styles.notice}><span>{formatApiError(c.datasetQuery.error, '数据集读取失败')}</span><button onClick={() => { void c.datasetQuery.refetch() }}>重新读取数据集</button></div> : null}
    {c.policyQuery.isError ? <div role="alert" className={styles.notice}><span>{c.policy ? '策略更新失败，保留上次数据。' : '策略读取失败。'}{formatApiError(c.policyQuery.error, '无法读取入库策略')}</span><button disabled={c.policyQuery.isFetching} onClick={() => { void c.policyQuery.refetch() }}>重新读取策略</button></div> : null}
    {c.saveError ? <div role="alert" className={styles.notice}><span>{c.saveError}，修改已保留。</span><button disabled={c.saving} onClick={() => { void c.save() }}>重试保存</button></div> : null}
    {c.policyQuery.isPending ? <div className={styles.empty} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" /><p>正在读取入库策略…</p></div> : c.rules.length ? <RulesTable c={c} /> : c.policy && !c.policyQuery.isError ? <div className={styles.empty}><Settings2 /><h2>还没有匹配规则</h2><p>未命中的文件沿用默认处理配置。</p><Button variant="ghost" disabled={c.blocked} onClick={event => { c.captureFocus(event.currentTarget); c.setTemplatesOpen(true) }}>从模板添加规则</Button></div> : <div className={styles.remainingSpace} />}
    <footer className={styles.footer} data-task-center-dock><span className={styles.saveState} aria-live="polite">{c.saving ? '正在保存…' : c.dirty ? '有未保存的修改' : c.policyQuery.isError ? '策略读取失败' : c.policy ? '已保存' : '尚未读取策略'}</span><span className={styles.spacer} />{c.dirty ? <Button variant="ghost" disabled={c.saving || c.previewing} onClick={event => { c.captureFocus(event.currentTarget); setPendingNavigation(null); c.setDiscardOpen(true) }}>放弃修改</Button> : null}<Button disabled={!c.dirty || c.blocked} aria-label="保存策略" onClick={() => { void c.save() }}>{c.saving ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : null}{c.saving ? '保存中' : '保存策略'}</Button></footer>
    {c.editor ? <PolicyRuleEditor c={c} /> : null}
    {c.templatesOpen ? <PolicyTemplateDialog c={c} /> : null}
    {c.previewOpen ? <PolicyPreviewDialog c={c} /> : null}
    {c.overviewOpen ? <PolicyOverviewDialog c={c} /> : null}
    <AlertDialog open={c.discardOpen} onOpenChange={open => { c.setDiscardOpen(open); if (!open) setPendingNavigation(null) }}><AlertDialogContent className={styles.confirmDialog} onCloseAutoFocus={event => { event.preventDefault(); c.restoreFocus() }}><AlertDialogHeader className={styles.dialogHeader}><AlertDialogTitle>放弃未保存的修改？</AlertDialogTitle><AlertDialogDescription>{pendingNavigation ? '离开后，当前未保存的规则修改将丢失。' : '规则将恢复为最近读取的已保存策略。'}</AlertDialogDescription></AlertDialogHeader><div className={styles.dialogFooter}><Button variant="ghost" onClick={() => { c.setDiscardOpen(false); setPendingNavigation(null) }}>继续编辑</Button><Button variant="destructive" onClick={() => { const target = pendingNavigation; c.discard(); setPendingNavigation(null); if (target) router.push(target) }}>{pendingNavigation ? '放弃并离开' : '放弃修改'}</Button></div></AlertDialogContent></AlertDialog>
  </section></AppFrame>
}
