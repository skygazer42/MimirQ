'use client'

import { useState, type Dispatch, type RefObject, type SetStateAction } from 'react'
import { Loader2, Play } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { DatasetPrecheckScanRunCreateRequest } from '@/types'
import styles from './precheck.module.css'

type Config = DatasetPrecheckScanRunCreateRequest
const checks = [
  ['enable_pdf_quality', 'PDF 质量', '识别扫描件和文本密度。'],
  ['enable_text_extract', '文本抽样', '提取少量正文用于质量统计。'],
  ['enable_pii', '个人信息检测', '查找邮箱、手机号等个人信息。'],
  ['enable_secrets', '密钥检测', '查找令牌和密钥。'],
  ['redact_paths', '隐藏文件路径', '报告中隐藏本机路径，并停用敏感信息上下文样本。'],
  ['compute_file_hash', '计算文件哈希', '计算 SHA-256，用于识别文件。'],
  ['reuse_unchanged_files', '复用未变更文件', '仅在未隐藏路径且扫描目录相同时生效。'],
] as const
const advancedChecks = [
  ['enable_near_dup', '近重复候选', '使用抽样正文查找相似文件，不自动删除文件。'],
  ['enable_sampling', '生成抽样清单', '生成代表性样本和问题样本。'],
] as const
const numbers = [
  ['pdf_sample_pages', 'PDF 抽样页数', '默认 3'],
  ['text_extract_max_bytes', '文本抽样字节上限', '默认 2000000'],
  ['sample_size', '抽样数量', '默认 60'],
  ['near_dup_hamming_threshold', '近重复阈值', '默认 5'],
] as const

export function ScanConfigDialog({ open, onOpenChange, config, setConfig, starting, error, onStart, triggerRef }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  config: Config
  setConfig: Dispatch<SetStateAction<Config>>
  starting: boolean
  error: string | null
  onStart: () => Promise<boolean>
  triggerRef: RefObject<HTMLButtonElement | null>
}) {
  const [tab, setTab] = useState('scope')
  function checkRows(rows: typeof checks | typeof advancedChecks) {
    return rows.map(([key, label, description]) => <div key={key} className={styles.configRow}><div><Label htmlFor={`precheck-${key}`}>{label}</Label><p>{description}</p></div><Switch id={`precheck-${key}`} checked={Boolean(config[key])} disabled={starting} onCheckedChange={value => setConfig(current => ({ ...current, [key]: value }))} /></div>)
  }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className={styles.configDialog} onCloseAutoFocus={event => { event.preventDefault(); triggerRef.current?.focus() }}>
    <DialogHeader className={styles.dialogHeader}><DialogTitle>新建文档预检</DialogTitle><DialogDescription>扫描文件并生成质量报告，不执行入库、切块或索引。</DialogDescription></DialogHeader>
    <form className={styles.configForm} onSubmit={event => { event.preventDefault(); void onStart().then(started => { if (started) onOpenChange(false); else if (!config.root_path.trim()) setTab('scope') }) }}>
      <Tabs value={tab} onValueChange={setTab} className={styles.configTabs}><TabsList aria-label="预检配置分类" className={styles.configTabList}><TabsTrigger value="scope">扫描范围</TabsTrigger><TabsTrigger value="advanced">高级选项</TabsTrigger></TabsList>
        <div className={styles.dialogBody}>
          <TabsContent value="scope" className="m-0 space-y-5"><div className={styles.field}><Label htmlFor="precheck-root-path">扫描目录</Label><Input id="precheck-root-path" aria-describedby="precheck-path-help" required placeholder="/data/docs" value={config.root_path} disabled={starting} onChange={event => setConfig(current => ({ ...current, root_path: event.target.value }))} /><p id="precheck-path-help">填写 API 或 Worker 能访问的目录路径。</p></div>
            <div className={styles.field}><Label htmlFor="precheck-max-files">最大文件数</Label><Input id="precheck-max-files" type="number" min={0} step={1} placeholder="不限" value={config.max_files ?? ''} disabled={starting} onChange={event => setConfig(current => ({ ...current, max_files: event.target.value ? Number(event.target.value) : null }))} /><p>留空或填 0 表示不限制。</p></div><div>{checkRows(checks)}</div></TabsContent>
          <TabsContent value="advanced" className="m-0 space-y-5"><div>{checkRows(advancedChecks)}</div><div className={styles.numericFields}>{numbers.map(([key, label, placeholder]) => <div key={key} className={styles.field}><Label htmlFor={`precheck-${key}`}>{label}</Label><Input id={`precheck-${key}`} type="number" min={0} step={1} placeholder={placeholder} value={config[key] ?? ''} disabled={starting} onChange={event => setConfig(current => ({ ...current, [key]: event.target.value ? Number(event.target.value) : null }))} /></div>)}</div></TabsContent>
        </div>
      </Tabs>
      {error ? <div role="alert" className={styles.formError}>{error}</div> : null}
      <div className={styles.dialogFooter}><Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>关闭</Button><Button type="submit" disabled={starting}>{starting ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Play />}{starting ? '正在启动…' : '开始预检'}</Button></div>
    </form>
  </DialogContent></Dialog>
}
