'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ChevronRight, Hash, Loader2, Lock, Plus, RefreshCw, Upload } from '@/components/icons'
import { toast } from 'sonner'
import { Link } from '@/i18n/navigation'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { SearchInput } from '@/components/ui/search-input'
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { AUTH_SCOPE_CHANGED_EVENT } from '@/lib/auth-storage'
import { buildGovernanceProfileCreateFromExisting, buildIngestionPolicyExportFilename } from '@/lib/governance-profile-utils'
import { queryKeys } from '@/lib/query-keys'
import type { GovernanceProfileCreate, GovernanceProfileListResponse, GovernanceProfileOut, GovernanceProfileSummary } from '@/types'
import { ProfileEditorDrawer } from './profile-editor-drawer'
import { ProfileDetail } from './profile-detail'
import { ProfileMark } from './profile-mark'
import { profileIdentity, profileRef } from './profile-presentation'
import { emptyPreviewSource } from './preview-source'
import styles from './profiles.module.css'

const LIST_PARAMS = { include_builtin: true, limit: 200 }
const LIST_KEY = queryKeys.governance.profiles(LIST_PARAMS)

export function GovernanceProfilesPage() {
  const client = useQueryClient()
  const [previewSource, setPreviewSource] = useState(emptyPreviewSource)
  useEffect(() => {
    const reset = () => setPreviewSource(emptyPreviewSource())
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, reset)
    return () => window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, reset)
  }, [])
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [source, setSource] = useState<'builtin' | 'custom'>('builtin')
  const [selectedRef, setSelectedRef] = useState<string | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [editor, setEditor] = useState<{ mode: 'create' | 'edit'; ref?: string; seed?: GovernanceProfileCreate } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<GovernanceProfileSummary | null>(null)
  const [overwrite, setOverwrite] = useState(false)
  const importInput = useRef<HTMLInputElement>(null)
  const [returnTarget, setReturnTarget] = useState<HTMLButtonElement | null>(null)
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 200)
    return () => window.clearTimeout(timer)
  }, [query])

  const list = useQuery({ queryKey: LIST_KEY, queryFn: () => pipelineApi.listGovernanceProfiles(LIST_PARAMS) })
  const searchParams = { ...LIST_PARAMS, q: search }
  const matches = useQuery({ queryKey: queryKeys.governance.profiles(searchParams), queryFn: () => pipelineApi.listGovernanceProfiles(searchParams), enabled: Boolean(search) })
  const activeQuery = search ? matches : list
  const items = useMemo(() => (activeQuery.data?.items || []).filter(item => item.is_system === (source === 'builtin')), [activeQuery.data?.items, source])
  const builtinCount = (list.data?.items || []).filter(item => item.is_system).length
  const customCount = list.data ? Math.max(0, list.data.total - builtinCount) : 0
  const selected = items.find(item => profileRef(item) === selectedRef) || items.find(item => item.key === 'builtin:pdf_text') || items[0]
  const groups = useMemo(() => {
    const grouped = new Map<string, GovernanceProfileSummary[]>()
    for (const item of items) {
      const group = profileIdentity(item).group
      grouped.set(group, [...(grouped.get(group) || []), item])
    }
    return grouped
  }, [items])
  const waiting = query.trim() !== search || activeQuery.isPending
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ['governance', 'profiles'] })
    void client.invalidateQueries({ queryKey: ['governance', 'profile-resolved'] })
  }
  const saved = (profile: GovernanceProfileOut, created = false) => {
    client.setQueryData<GovernanceProfileListResponse>(LIST_KEY, previous => previous ? { total: previous.total + (created ? 1 : 0), items: [profile, ...previous.items.filter(item => profileRef(item) !== profileRef(profile))] } : { total: 1, items: [profile] })
    setSource(profile.is_system ? 'builtin' : 'custom')
    setSelectedRef(profileRef(profile)); setQuery(''); setSearch(''); setRevealed(true)
    refresh()
  }
  const copy = useMutation({
    mutationFn: (profile: GovernanceProfileSummary) => pipelineApi.getGovernanceProfile(profileRef(profile)),
    onSuccess: profile => setEditor({ mode: 'create', seed: buildGovernanceProfileCreateFromExisting(profile) }),
    onError: error => toast.error(formatApiError(error, '复制配置失败')),
  })
  const importing = useMutation({
    mutationFn: ({ file, overwrite: replace }: { file: File; overwrite: boolean }) => pipelineApi.importGovernanceProfiles(file, replace),
    onSuccess: result => { toast.success(`已导入：新建 ${result.created} 项，更新 ${result.updated} 项`); refresh() },
    onError: error => toast.error(formatApiError(error, '导入失败')),
    onSettled: () => { if (importInput.current) importInput.current.value = '' },
  })
  const deleting = useMutation({
    mutationFn: (profile: GovernanceProfileSummary) => {
      if (profile.is_system) throw new Error('内置模板不能删除')
      return pipelineApi.deleteGovernanceProfile(profileRef(profile))
    },
    onSuccess: (_, profile) => {
      client.setQueryData<GovernanceProfileListResponse>(LIST_KEY, previous => previous ? { total: Math.max(0, previous.total - 1), items: previous.items.filter(item => profileRef(item) !== profileRef(profile)) } : previous)
      setDeleteTarget(null); toast.success('已删除配置'); refresh()
    },
    onError: error => toast.error(formatApiError(error, '删除失败，请重试')),
  })

  const exportProfile = async (profile: GovernanceProfileSummary, policy = false) => {
    try {
      const ref = profileRef(profile)
      const blob = await (policy ? pipelineApi.exportGovernanceProfileIngestionPolicy(ref) : pipelineApi.exportGovernanceProfile(ref))
      const filename = policy ? buildIngestionPolicyExportFilename(profile.key) : `${profile.key.replaceAll(/[\\/:*?"<>|]+/g, '_').slice(0, 120)}.governance-profile.json`
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { toast.error(formatApiError(error, '导出配置失败')) }
  }
  const changeSource = (next: 'builtin' | 'custom') => { setSource(next); setRevealed(false) }
  const selectProfile = (profile: GovernanceProfileSummary, target: HTMLButtonElement) => {
    setReturnTarget(target)
    setSelectedRef(profileRef(profile))
    setRevealed((target.closest('[data-profile-page]')?.clientWidth || 0) < 850)
  }
  const back = () => { setRevealed(false); requestAnimationFrame(() => returnTarget?.focus()) }

  return <div className={styles.page} data-profile-page data-detail-open={revealed}>
    <header className={styles.header}>
      <div className={styles.title}><PageTitleIcon name="governance-config" /><div><h1>治理配置</h1><p>管理可复用的文档清洗与脱敏规则</p></div></div>
      <div className={styles.headerActions}>
        <Button asChild variant="ghost" className={styles.commonLines}><Link href="/data-governance/common-lines"><Hash />重复内容规则</Link></Button>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" disabled={importing.isPending}>{importing.isPending ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Upload />}{importing.isPending ? '正在导入…' : '导入'}</Button></DropdownMenuTrigger><DropdownMenuContent align="end">
          <DropdownMenuCheckboxItem checked={overwrite} onCheckedChange={setOverwrite} onSelect={event => event.preventDefault()}>覆盖同名配置</DropdownMenuCheckboxItem><DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => importInput.current?.click()}><Upload />选择 JSON 文件</DropdownMenuItem>
        </DropdownMenuContent></DropdownMenu>
        <Button onClick={() => setEditor({ mode: 'create' })}><Plus />新建配置</Button>
      </div>
      <input ref={importInput} type="file" accept="application/json,.json" className="hidden" aria-label="导入治理配置文件" onChange={event => { const file = event.target.files?.[0]; if (file) importing.mutate({ file, overwrite }) }} />
    </header>
    <div className={styles.workspace}>
      <aside className={styles.directory} aria-label="治理模板目录" data-profile-directory>
        <div className={styles.directoryHead}>
          <div className={styles.directoryTitle}><h2>模板目录</h2><span>{list.data ? `${list.data.total} 个配置` : '正在读取…'}</span></div>
          <SearchInput value={query} onValueChange={value => { setQuery(value); setRevealed(false) }} placeholder="搜索模板名称或说明" aria-label="搜索治理配置" inputClassName={styles.search} />
          <div className={styles.sourceTabs} role="group" aria-label="配置来源">
            <button type="button" aria-pressed={source === 'builtin'} onClick={() => changeSource('builtin')}>内置模板<span>{builtinCount}</span></button>
            <button type="button" aria-pressed={source === 'custom'} onClick={() => changeSource('custom')}>自定义配置<span>{customCount}</span></button>
          </div>
        </div>
        <nav className={styles.directoryScroll} aria-label="配置列表" aria-busy={waiting || activeQuery.isFetching}>
          {activeQuery.isError ? <div className={styles.listState} role="alert"><AlertCircle /><p>{formatApiError(activeQuery.error, '读取目录失败')}</p><Button variant="outline" onClick={() => void activeQuery.refetch()}>重试读取</Button></div> : waiting ? <div className={styles.listLoading} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" />正在查找配置…</div> : !items.length ? <div className={styles.listState}><p>{search ? '没有找到匹配的配置' : source === 'custom' ? '还没有自定义配置' : '暂无内置模板'}</p>{search ? <Button variant="ghost" onClick={() => { setQuery(''); setSearch('') }}>清除搜索</Button> : source === 'custom' && <Button variant="outline" onClick={() => setEditor({ mode: 'create' })}><Plus />新建配置</Button>}</div> : [...groups].map(([group, profiles]) => <section className={styles.directoryGroup} key={group} aria-label={group}>
            <h3>{group}<span>{profiles.length}</span></h3>
            {profiles.map(profile => <button type="button" className={styles.directoryItem} key={profileRef(profile)} aria-current={selected && profileRef(selected) === profileRef(profile) ? 'true' : undefined} data-profile-ref={profileRef(profile)} title={profile.name} onClick={event => selectProfile(profile, event.currentTarget)}>
              <ProfileMark profile={profile} /><span>{profileIdentity(profile).name}</span>{selected && profileRef(selected) === profileRef(profile) && <ChevronRight aria-hidden="true" />}
            </button>)}
          </section>)}
        </nav>
        <footer className={styles.directoryFooter}><Lock aria-hidden="true" /><span>{(activeQuery.data?.total || 0) > (activeQuery.data?.items.length || 0) ? '更多配置可通过搜索查找' : source === 'builtin' ? '内置模板可复制为自定义配置' : `${customCount} 项自定义配置`}</span><Button variant="ghost" size="icon" aria-label="重新加载目录" disabled={activeQuery.isFetching} onClick={refresh}><RefreshCw className={activeQuery.isFetching ? 'animate-spin motion-reduce:animate-none' : undefined} /></Button></footer>
      </aside>
      <div className={styles.reader}>
        {selected && !waiting && !activeQuery.isError ? <ProfileDetail key={profileRef(selected)} summary={selected} revealed={revealed} copying={copy.isPending} previewSource={previewSource} onPreviewSourceChange={setPreviewSource} onBack={back} onCopy={() => copy.mutate(selected)} onEdit={() => setEditor({ mode: 'edit', ref: profileRef(selected) })} onExport={policy => void exportProfile(selected, policy)} onDelete={() => { deleting.reset(); setDeleteTarget(selected) }} /> : <div className={styles.emptyDetail}><PageTitleIcon name="governance-config" /><h2>{waiting ? '正在读取配置' : activeQuery.isError ? '无法读取配置目录' : search ? '没有匹配的配置' : '选择或新建治理配置'}</h2><p>{waiting ? '目录与规则将显示在这里' : source === 'custom' && !search ? '从内置模板复制，或创建自己的清洗规则。' : '在左侧目录中选择一项，查看规则与参数。'}</p></div>}
      </div>
    </div>
    <ProfileEditorDrawer open={Boolean(editor)} mode={editor?.mode || 'create'} profileRef={editor?.ref} seedCreate={editor?.seed} onOpenChange={open => { if (!open) setEditor(null) }} onSaved={profile => saved(profile)} onCreated={profile => saved(profile, true)} />
    <AlertDialog open={Boolean(deleteTarget)} onOpenChange={open => { if (!open && !deleting.isPending) setDeleteTarget(null) }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>删除治理配置？</AlertDialogTitle><AlertDialogDescription>将删除「{deleteTarget?.name}」，此操作无法恢复。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel disabled={deleting.isPending}>取消</AlertDialogCancel><AlertDialogAction disabled={deleting.isPending} onClick={event => { event.preventDefault(); if (deleteTarget) deleting.mutate(deleteTarget) }}>{deleting.isPending ? '正在删除…' : '删除配置'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
  </div>
}
