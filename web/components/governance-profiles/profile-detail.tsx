'use client'

import { useEffect, useRef, type Dispatch, type SetStateAction } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, ArrowLeft, Braces, Check, ChevronRight, Copy, Download, Loader2, Lock, MoreHorizontal, Pencil, Trash2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import type { GovernanceProfileSummary } from '@/types'
import { CleaningPreview } from './cleaning-preview'
import type { PreviewSource } from './preview-source'
import { profileField, profileIdentity, profileRef, profileValue } from './profile-presentation'
import { ProfileMark } from './profile-mark'
import styles from './profiles.module.css'

type Props = {
  summary: GovernanceProfileSummary
  revealed: boolean
  copying: boolean
  onBack: () => void
  onCopy: () => void
  onEdit: () => void
  onExport: (policy?: boolean) => void
  onDelete: () => void
  previewSource: PreviewSource
  onPreviewSourceChange: Dispatch<SetStateAction<PreviewSource>>
}

export function ProfileDetail({ summary, revealed, copying, onBack, onCopy, onEdit, onExport, onDelete, previewSource, onPreviewSourceChange }: Readonly<Props>) {
  const ref = profileRef(summary)
  const heading = useRef<HTMLHeadingElement>(null)
  const query = useQuery({ queryKey: queryKeys.governance.profileResolved(ref), queryFn: () => pipelineApi.getGovernanceProfileResolved(ref), retry: 1 })
  useEffect(() => { if (revealed) heading.current?.focus({ preventScroll: true }) }, [revealed])
  const profile = query.data?.profile || summary
  const effective = query.data?.effective
  const meta = profileIdentity(profile)
  const patch = effective?.pipeline_patch || {}
  const entries = Object.entries(patch).filter(([key]) => key !== 'governance_enabled')
  const enabled = entries.filter(([, value]) => value === true).length
  return <article className={styles.detail} aria-label="配置详情" data-profile-detail>
    <header className={styles.detailHero}>
      <div className={styles.location}><Button variant="ghost" size="icon" className={styles.back} onClick={onBack} aria-label="返回模板目录"><ArrowLeft /></Button><span>{meta.group}</span><ChevronRight aria-hidden="true" /><span>配置详情</span></div>
      <div className={styles.detailTitleRow}>
        <ProfileMark profile={profile} />
        <h2 ref={heading} tabIndex={-1} title={profile.name}>{meta.name}</h2>
        <div className={styles.detailActions}>
          <Button variant="outline" onClick={() => onExport()}><Download />导出</Button>
          <Button onClick={summary.is_system ? onCopy : onEdit} disabled={copying}>{copying ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : summary.is_system ? <Copy /> : <Pencil />}{summary.is_system ? '复制为自定义' : '编辑配置'}</Button>
          <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="当前配置更多操作"><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
            {!summary.is_system && <DropdownMenuItem onSelect={onCopy} disabled={copying}><Copy />复制配置</DropdownMenuItem>}
            <DropdownMenuItem onSelect={() => onExport(true)}><Download />导出入库策略</DropdownMenuItem>
            {!summary.is_system && <><DropdownMenuSeparator /><DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}><Trash2 />删除配置</DropdownMenuItem></>}
          </DropdownMenuContent></DropdownMenu>
        </div>
      </div>
      {profile.description && <p className={styles.description}>{profile.description}</p>}
      <dl className={styles.attributes}>
        <div><dt>输入格式</dt><dd>{effective ? effective.input_formats.map(format => <span className={styles.format} key={format}>{format === 'html' ? 'HTML' : 'Markdown'}</span>) : '—'}</dd></div>
        <div><dt>治理清洗</dt><dd className={patch.governance_enabled === true ? styles.enabled : undefined}>{patch.governance_enabled === true && <Check aria-hidden="true" />}{profileValue(patch.governance_enabled)}</dd></div>
        <div><dt>配置标识</dt><dd><code>{profile.key}</code></dd></div>
        <div><dt className="sr-only">来源</dt><dd>{profile.is_system && <Lock aria-hidden="true" />}{profile.is_system ? '内置 · 只读' : '自定义'}</dd></div>
      </dl>
    </header>
    {query.isPending ? <div className={styles.loading} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" />正在读取规则…</div> : query.isError ? <div className={styles.detailError} role="alert"><AlertCircle /><p>{formatApiError(query.error, '读取配置失败')}</p><Button variant="outline" onClick={() => void query.refetch()}>重试读取</Button></div> : effective && <div className={styles.detailBody}>
      <section className={styles.rules} aria-labelledby="profile-rules-heading">
        <div className={styles.sectionHeading}><h3 id="profile-rules-heading">规则与参数</h3><span>{entries.length} 项配置 · {enabled} 项启用</span>{profile.is_system && <span className={styles.readonly}><Lock />复制后可调整</span>}</div>
        {!!query.data?.chain.length && query.data.chain.length > 1 && <p className={styles.inheritance}>继承自 {query.data.chain.slice(0, -1).map(parent => parent.name).join(' / ')}，下方展示合并后的配置。</p>}
        {entries.length ? <table className={styles.rulesTable}><thead><tr><th scope="col">规则</th><th scope="col">作用</th><th scope="col">设置</th></tr></thead><tbody>{entries.map(([key, value]) => {
          const field = profileField(key)
          return <tr key={key}><th scope="row">{field.label}<span className={styles.mobilePurpose}>{field.purpose}</span></th><td>{field.purpose}</td><td>{typeof value === 'boolean' ? <span className={value ? styles.enabled : undefined}>{value && <Check aria-hidden="true" />}{profileValue(value)}</span> : <span className={styles.ruleValue}>{profileValue(value, key)}{typeof value === 'number' && field.unit && <small>{field.unit}</small>}</span>}</td></tr>
        })}</tbody></table> : <p className={styles.note}>此配置未覆盖管线参数，沿用系统默认值。</p>}
        {(effective.regex_rules.length > 0 || (effective.processing_scripts?.length || 0) > 0) && <p className={styles.extraRules}>{effective.regex_rules.length > 0 && <span>附加正则规则 {effective.regex_rules.length} 条</span>}{!!effective.processing_scripts?.length && <span>审阅脚本 {effective.processing_scripts.length} 个（不执行）</span>}</p>}
        <details className={styles.jsonDetails}><summary><Braces />查看配置 JSON</summary><pre>{JSON.stringify(effective, null, 2)}</pre></details>
      </section>
      <CleaningPreview key={JSON.stringify(effective)} payload={effective} source={previewSource} onSourceChange={onPreviewSourceChange} />
    </div>}
  </article>
}
