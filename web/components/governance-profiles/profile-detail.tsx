'use client'

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Braces,
  Check,
  Copy,
  Download,
  FileText,
  Layers,
  ListChecks,
  Loader2,
  Lock,
  MoreHorizontal,
  Pencil,
  Play,
  ScanLine,
  Shield,
  SlidersHorizontal,
  Table2,
  Trash2,
} from '@/components/icons'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Switch } from '@/components/ui/switch'
import { pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import type { GovernanceProfileOut, GovernanceProfileSummary } from '@/types'
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
  onForkWithPatch: (profile: GovernanceProfileOut, patchOverride: Record<string, unknown>, label: string) => void
  onEdit: () => void
  onExport: (policy?: boolean) => void
  onDelete: () => void
  previewSource: PreviewSource
  onPreviewSourceChange: Dispatch<SetStateAction<PreviewSource>>
}

function getRuleIcon(key: string) {
  if (key.includes('toc')) return ListChecks
  if (key.includes('noise')) return SlidersHorizontal
  if (key.includes('unwrap')) return ScanLine
  if (key.includes('common') || key.includes('boilerplate')) return Layers
  if (key.includes('table')) return Table2
  if (key.includes('pii') || key.includes('secret')) return Shield
  if (key.includes('duplicate')) return Copy
  return FileText
}

export function ProfileDetail({
  summary,
  revealed,
  copying,
  onBack,
  onCopy,
  onForkWithPatch,
  onEdit,
  onExport,
  onDelete,
  previewSource,
  onPreviewSourceChange,
}: Readonly<Props>) {
  const ref = profileRef(summary)
  const client = useQueryClient()
  const heading = useRef<HTMLHeadingElement>(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [jsonOpen, setJsonOpen] = useState(false)
  const [copiedJson, setCopiedJson] = useState(false)
  const [togglingKey, setTogglingKey] = useState<string | null>(null)
  const query = useQuery({
    queryKey: queryKeys.governance.profileResolved(ref),
    queryFn: ({ signal }) => pipelineApi.getGovernanceProfileResolved(ref, { signal }),
    retry: 1,
  })
  const toggleRuleMutation = useMutation({
    mutationFn: ({ key, nextValue }: { key: string; label: string; nextValue: boolean }) => {
      if (!query.data || query.data.profile.is_system) {
        throw new Error('内置模板不可直接修改')
      }
      return pipelineApi.updateGovernanceProfile(ref, {
        payload: {
          ...query.data.profile.payload,
          pipeline_patch: {
            ...query.data.profile.payload.pipeline_patch,
            [key]: nextValue,
          },
        },
      })
    },
    onMutate: ({ key }) => {
      setTogglingKey(key)
      return getAuthSessionKey()
    },
    onSuccess: (_updated, { label, nextValue }, sessionKey) => {
      if (sessionKey !== getAuthSessionKey()) return
      toast.success(`${nextValue ? '已启用' : '已关闭'}「${label}」`)
      void client.invalidateQueries({ queryKey: queryKeys.governance.all })
    },
    onError: (error, { label }, sessionKey) => {
      if (sessionKey !== getAuthSessionKey()) return
      toast.error(formatApiError(error, `更新「${label}」失败`))
    },
    onSettled: () => {
      setTogglingKey(null)
    },
  })
  const handleToggleRule = (key: string, label: string, nextValue: boolean) => {
    if (!query.data || togglingKey !== null) return
    if (query.data.profile.is_system) {
      onForkWithPatch(query.data.profile, { [key]: nextValue }, label)
      return
    }
    toggleRuleMutation.mutate({ key, label, nextValue })
  }
  const handleCopyJson = async () => {
    if (!effective) return
    try {
      await navigator.clipboard.writeText(JSON.stringify(effective, null, 2))
      setCopiedJson(true)
      toast.success('已复制配置 JSON')
      window.setTimeout(() => setCopiedJson(false), 1800)
    } catch {
      toast.error('复制失败，请手动选中复制')
    }
  }
  useEffect(() => {
    if (revealed) heading.current?.focus({ preventScroll: true })
  }, [revealed])
  const profile = query.data?.profile || summary
  const effective = query.data?.effective
  const meta = profileIdentity(profile)
  const patch = effective?.pipeline_patch || {}
  const entries = Object.entries(patch).filter(([key]) => key !== 'governance_enabled')
  const enabled = entries.filter(([, value]) => value === true).length
  const disabledCount = entries.filter(([, value]) => value === false).length
  return (
    <article className={styles.detail} aria-label="配置详情" data-profile-detail>
      <header className={styles.detailHero}>
        <div className={styles.detailTitleRow}>
          <Button variant="ghost" size="icon" className={styles.back} onClick={onBack} aria-label="返回模板目录">
            <ArrowLeft />
          </Button>
          <ProfileMark profile={profile} />
          <div className={styles.detailIdentity}>
            <h2 ref={heading} tabIndex={-1} title={profile.name}>
              {meta.name}
            </h2>
            <div className={styles.detailMetaLine}>
              <span>{meta.group}</span>
              <span aria-hidden="true">·</span>
              <code>{profile.key}</code>
              <span aria-hidden="true">·</span>
              <span className={styles.metaSource}>
                {profile.is_system && <Lock aria-hidden="true" />}
                {profile.is_system ? '内置只读' : '自定义'}
              </span>
              {patch.governance_pii_anonymize === true && (
                <span className={styles.domainPill} data-tone="governance">
                  个人信息脱敏
                </span>
              )}
              {patch.governance_secrets_redact === true && (
                <span className={styles.domainPill} data-tone="governance">
                  密钥脱敏
                </span>
              )}
            </div>
          </div>
          <div className={styles.detailActions}>
            <Button
              variant="outline"
              className={styles.previewTriggerBtn}
              disabled={!effective}
              onClick={() => setPreviewOpen(true)}
            >
              <Play />
              清洗预览
            </Button>
            <Button variant="outline" onClick={() => onExport()}>
              <Download />
              导出
            </Button>
            <Button variant="outline" className={styles.copyOrEditBtn} onClick={summary.is_system ? onCopy : onEdit} disabled={copying}>
              {copying ? (
                <Loader2 className="animate-spin motion-reduce:animate-none" />
              ) : summary.is_system ? (
                <Copy />
              ) : (
                <Pencil />
              )}
              {summary.is_system ? '复制为自定义' : '编辑配置'}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="当前配置更多操作">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {!summary.is_system && (
                  <DropdownMenuItem onSelect={onCopy} disabled={copying}>
                    <Copy />
                    复制配置
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={() => onExport(true)}>
                  <Download />
                  导出入库策略
                </DropdownMenuItem>
                {effective ? (
                  <DropdownMenuItem onSelect={() => setJsonOpen(true)}>
                    <Braces />
                    查看配置 JSON
                  </DropdownMenuItem>
                ) : null}
                {!summary.is_system && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={onDelete}>
                      <Trash2 />
                      删除配置
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {profile.description && <p className={styles.description}>{profile.description}</p>}
      </header>
      {query.isPending ? (
        <div className={styles.loading} role="status">
          <Loader2 className="animate-spin motion-reduce:animate-none" />
          正在读取规则…
        </div>
      ) : query.isError ? (
        <div className={styles.detailError} role="alert">
          <AlertCircle />
          <p>{formatApiError(query.error, '读取配置失败')}</p>
          <Button variant="outline" onClick={() => void query.refetch()}>
            重试读取
          </Button>
        </div>
      ) : (
        effective && (
          <div className={styles.detailBody}>
            <section className={styles.rules} aria-labelledby="profile-rules-heading">
              <div className={styles.summaryBar} aria-label="规则统计">
                <div className={styles.summaryBarLeft}>
                  <span className={styles.summaryLabel}>输入格式</span>
                  {effective.input_formats.map((format) => (
                    <span className={styles.format} data-format={format} key={format}>
                      {format === 'html' ? 'HTML' : 'Markdown'}
                    </span>
                  ))}
                  <span className={styles.summarySep} aria-hidden="true">·</span>
                  <span className={styles.ruleCount}>共 {entries.length} 项配置</span>
                  <span className={styles.summarySep} aria-hidden="true">·</span>
                  <span className={styles.enabled}>已启用 {enabled}</span>
                  <span className={styles.summarySep} aria-hidden="true">·</span>
                  <span>已关闭 {disabledCount}</span>
                </div>
                <span className={styles.summaryHint}>
                  {profile.is_system ? (
                    <>
                      <Lock aria-hidden="true" />
                      点击开关可复制为自定义规则
                    </>
                  ) : (
                    <>
                      <Pencil aria-hidden="true" />
                      点击开关即时保存生效
                    </>
                  )}
                </span>
              </div>

              <h3 id="profile-rules-heading" className="sr-only">
                规则与参数
              </h3>

              {!!query.data?.chain.length && query.data.chain.length > 1 && (
                <p className={styles.inheritance}>
                  继承自{' '}
                  {query.data.chain
                    .slice(0, -1)
                    .map((parent) => parent.name)
                    .join(' / ')}
                  ，下方展示合并后的配置。
                </p>
              )}

              {entries.length ? (
                <div className={styles.rulesMatrix} data-rule-matrix="true">
                  {entries.map(([key, value]) => {
                    const field = profileField(key)
                    const RuleIcon = getRuleIcon(key)
                    const ownRule = Object.hasOwn(query.data.profile.payload.pipeline_patch, key)
                    const state =
                      value == null ? 'unset' : value === false ? 'disabled' : ownRule ? 'resolved' : 'inherited'
                    const isBusy = togglingKey === key
                    return (
                      <div key={key} className={styles.ruleCard} data-rule-state={state}>
                        <RuleIcon className={styles.ruleCardIcon} aria-hidden="true" />
                        <div className={styles.ruleCardCopy}>
                          <strong>{field.label}</strong>
                          <small>{field.purpose}</small>
                        </div>
                        <div className={styles.ruleCardStatus}>
                          {typeof value === 'boolean' ? (
                            <div className={styles.ruleSwitchRow}>
                              <span className={value ? styles.enabledLabel : styles.disabledLabel}>
                                {value ? '已启用' : '关闭'}
                              </span>
                              <Switch
                                checked={value}
                                disabled={togglingKey !== null}
                                aria-busy={isBusy}
                                aria-label={`切换${field.label}`}
                                onCheckedChange={(checked) => handleToggleRule(key, field.label, checked)}
                              />
                            </div>
                          ) : (
                            <span className={styles.ruleValue}>
                              {profileValue(value, key)}
                              {typeof value === 'number' && field.unit && <small>{field.unit}</small>}
                            </span>
                          )}
                          {state === 'unset' ? (
                            <small className={styles.ruleOrigin}>未设置</small>
                          ) : !ownRule ? (
                            <small className={styles.ruleOrigin}>继承</small>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className={styles.note}>未设置其他管线覆盖参数。</p>
              )}

              {(effective.regex_rules.length > 0 || (effective.processing_scripts?.length || 0) > 0) && (
                <p className={styles.extraRules}>
                  {effective.regex_rules.length > 0 && <span>附加正则规则 {effective.regex_rules.length} 条</span>}
                  {!!effective.processing_scripts?.length && (
                    <span>审阅脚本 {effective.processing_scripts.length} 个（不执行）</span>
                  )}
                </p>
              )}
            </section>
          </div>
        )
      )}

      {effective ? (
        <Dialog open={jsonOpen} onOpenChange={setJsonOpen}>
          <DialogContent className={styles.jsonDialog} aria-label="配置 JSON">
            <header className={styles.jsonDialogHeader}>
              <div className={styles.previewModalTitle}>
                <DialogTitle className="text-[15px] font-medium">配置 JSON</DialogTitle>
                <span className={styles.previewModalBadge}>{profile.key}</span>
              </div>
              <Button variant="outline" size="sm" onClick={() => void handleCopyJson()}>
                {copiedJson ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {copiedJson ? '已复制' : '复制 JSON'}
              </Button>
              <DialogDescription className="sr-only">查看并复制当前治理配置的合并 JSON 内容。</DialogDescription>
            </header>
            <pre className={styles.jsonDialogPre}>{JSON.stringify(effective, null, 2)}</pre>
          </DialogContent>
        </Dialog>
      ) : null}

      {effective ? (
        <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
          <DialogContent className={styles.previewModal} aria-label="清洗前后对照">
            <header className={styles.previewModalHeader}>
              <div className={styles.previewModalTitle}>
                <DialogTitle className="text-[15px] font-medium">清洗前后对照</DialogTitle>
                <span className={styles.previewModalBadge}>
                  {meta.name} · {profile.key}
                </span>
              </div>
              <DialogDescription className="sr-only">
                按当前治理配置试运行文档清洗并对照清洗前后差异，不会修改已保存文档。
              </DialogDescription>
            </header>
            <div className={styles.previewModalBody}>
              <CleaningPreview
                key={JSON.stringify(effective)}
                payload={effective}
                source={previewSource}
                onSourceChange={onPreviewSourceChange}
                inModal
              />
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </article>
  )
}
