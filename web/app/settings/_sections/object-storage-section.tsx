'use client'

import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Input } from '@/components/ui/input'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'
import type { SystemSettings } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Archive, FileText, ImageIcon, LockKeyhole, Server } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

type MinIOSettings = NonNullable<SystemSettings['minio']>

type ObjectStorageSectionProps = {
  minio: MinIOSettings
  updateMinIO: (patch: Partial<MinIOSettings>) => void
}

const STORAGE_CARD =
  'rounded-xl border border-info/15 bg-info/[0.025] p-3.5 shadow-none'
const STORAGE_INPUT = 'h-8 rounded-lg border-info/15 bg-info/[0.025] text-[12px]'

function StorageCard({
  icon: Icon,
  label,
  title,
  description,
  action,
  children,
}: Readonly<{
  icon: LucideIcon
  label: string
  title: string
  description: string
  action?: ReactNode
  children?: ReactNode
}>) {
  return (
    <div className={STORAGE_CARD}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 gap-2.5">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-[12px] border border-info/20 bg-info/10 text-info">
            <Icon className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-info/80">
              {label}
            </div>
            <div className="mt-0.5 text-[13px] font-medium tracking-[-0.005em] text-foreground">
              {title}
            </div>
            <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>{description}</div>
          </div>
        </div>
        {action}
      </div>
      {children ? <div className="mt-3 space-y-3">{children}</div> : null}
    </div>
  )
}

function Field({
  label,
  children,
  hint,
}: Readonly<{ label: string; children: ReactNode; hint?: string }>) {
  return (
    <div className="space-y-1.5">
      <div className={settingsTextTokens.fieldLabel}>{label}</div>
      {children}
      {hint ? <div className={settingsTextTokens.helpText}>{hint}</div> : null}
    </div>
  )
}

function ToggleRow({
  title,
  description,
  checked,
  onToggle,
  label,
}: Readonly<{
  title: string
  description: string
  checked: boolean
  onToggle: () => void
  label: string
}>) {
  return (
    <div
      className={cn(
        'flex items-start justify-between gap-3 rounded-xl border px-3 py-2.5 transition-colors',
        checked ? 'border-info/25 bg-info/10' : 'border-border/60 bg-muted/28'
      )}
    >
      <div className="min-w-0">
        <div className={settingsTextTokens.panelTitle}>{title}</div>
        <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>{description}</div>
      </div>
      <SettingsSwitch
        checked={checked}
        onCheckedChange={() => onToggle()}
        className="shrink-0"
        aria-label={label}
      />
    </div>
  )
}

export function ObjectStorageSection({
  minio,
  updateMinIO,
}: Readonly<ObjectStorageSectionProps>) {
  const isEnabled = Boolean(minio.enabled)
  const isDocumentStorageEnabled = Boolean(minio.documents_enabled)
  const isSslEnabled = Boolean(minio.use_ssl)

  return (
    <section className="grid gap-3 xl:grid-cols-2">
      <StorageCard
        icon={Archive}
        label="MinIO"
        title="对象存储开关"
        description="控制图片、解析产物和可选文档对象存储；Docker MinIO 已启动时仍需打开这里的应用开关"
        action={
          <SettingsSwitch
            checked={isEnabled}
            onCheckedChange={() => updateMinIO({ enabled: !isEnabled })}
            className="shrink-0"
            aria-label="切换 MinIO 对象存储"
          />
        }
      >
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Endpoint" hint="本机启动后端通常为 localhost:9000，容器内为 mimirq-minio:9000">
            <Input
              value={minio.endpoint}
              onChange={(event) => updateMinIO({ endpoint: event.target.value })}
              placeholder="localhost:9000"
              className={STORAGE_INPUT}
            />
          </Field>
          <Field label="Bucket">
            <Input
              value={minio.bucket_name}
              onChange={(event) => updateMinIO({ bucket_name: event.target.value })}
              placeholder="mimirq"
              className={STORAGE_INPUT}
            />
          </Field>
        </div>
      </StorageCard>

      <StorageCard
        icon={LockKeyhole}
        label="凭证"
        title="访问凭证"
        description="已保存的密钥会脱敏显示；留着脱敏值保存不会覆盖真实密钥"
      >
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Access Key">
            <Input
              value={minio.access_key}
              onChange={(event) => updateMinIO({ access_key: event.target.value })}
              placeholder="minioadmin"
              className={STORAGE_INPUT}
            />
          </Field>
          <Field label="Secret Key">
            <Input
              type="password"
              value={minio.secret_key}
              onChange={(event) => updateMinIO({ secret_key: event.target.value })}
              placeholder="minioadmin"
              className={STORAGE_INPUT}
            />
          </Field>
        </div>
      </StorageCard>

      <StorageCard
        icon={Server}
        label="传输"
        title="连接与 TLS"
        description="本地 Docker MinIO 默认 HTTP；生产 S3/OSS/COS 通常需要启用 SSL"
      >
        <ToggleRow
          title="使用 SSL"
          description="打开后以 HTTPS/S3 secure 模式连接 endpoint"
          checked={isSslEnabled}
          onToggle={() => updateMinIO({ use_ssl: !isSslEnabled })}
          label="切换 MinIO SSL"
        />
      </StorageCard>

      <StorageCard
        icon={FileText}
        label="文档"
        title="文档对象存储"
        description="启用后文档下载、对象引用和大文件生命周期会依赖 MinIO"
      >
        <ToggleRow
          title="存储文档对象"
          description="关闭时仍可使用本地文件路径；开启后需要 bucket 可写"
          checked={isDocumentStorageEnabled}
          onToggle={() => updateMinIO({ documents_enabled: !isDocumentStorageEnabled })}
          label="切换 MinIO 文档对象存储"
        />
      </StorageCard>

      <StorageCard
        icon={ImageIcon}
        label="图片"
        title="图片读取上限"
        description="限制通过 MinIO 读取图片字节，0 表示不额外限制"
      >
        <Field label="图片最大字节">
          <Input
            type="number"
            min={0}
            value={minio.image_max_bytes}
            onChange={(event) =>
              updateMinIO({
                image_max_bytes: Math.max(0, Number.parseInt(event.target.value || '0', 10)),
              })
            }
            className={STORAGE_INPUT}
          />
        </Field>
      </StorageCard>
    </section>
  )
}
