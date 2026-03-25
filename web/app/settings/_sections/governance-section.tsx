'use client'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import type { SystemSettings } from '@/lib/api'
import { AlertCircle, EyeOff, ToggleLeft, ToggleRight } from 'lucide-react'

type GovernanceSettings = NonNullable<SystemSettings['governance']>

type GovernanceSectionProps = {
  isGovernanceEnabled: boolean
  isPiiAnonymizeEnabled: boolean
  isSecretsRedactEnabled: boolean
  isQuarantineOnDropEnabled: boolean
  updateGovernance: (patch: Partial<GovernanceSettings>) => void
}

export function GovernanceSection({
  isGovernanceEnabled,
  isPiiAnonymizeEnabled,
  isSecretsRedactEnabled,
  isQuarantineOnDropEnabled,
  updateGovernance,
}: Readonly<GovernanceSectionProps>) {
  return (
    <section>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <EyeOff className="h-5 w-5 text-primary" />
          数据治理
        </h2>
        <div className="flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
          <span>保存后通常可立即生效</span>
        </div>
      </div>

      <div className="space-y-6 rounded-2xl border border-border bg-card p-6 shadow-sm">
        <Alert className="shadow-soft/40">
          <AlertCircle className="h-4 w-4" />
          <div>
            <AlertTitle>默认治理规则</AlertTitle>
            <AlertDescription className="text-foreground/80">
              这些开关会影响“入库前清洗/脱敏”，用于没有单独配置管线（dataset/document pipeline overrides）的场景。
            </AlertDescription>
          </div>
        </Alert>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/30 p-4">
            <div>
              <div className="text-sm font-semibold text-foreground">启用数据治理</div>
              <div className="mt-1 text-xs text-muted-foreground">打开后才会应用下方治理项（对新入库文档生效）</div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ enabled: !isGovernanceEnabled })}
              className="shrink-0"
              aria-label="Toggle governance"
            >
              {isGovernanceEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/30 p-4">
            <div>
              <div className="text-sm font-semibold text-foreground">PII 脱敏</div>
              <div className="mt-1 text-xs text-muted-foreground">
                尝试识别并匿名化手机号/邮箱等个人信息（可能影响检索/可读性）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ pii_anonymize: !isPiiAnonymizeEnabled })}
              className="shrink-0"
              aria-label="Toggle PII anonymize"
            >
              {isPiiAnonymizeEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/30 p-4">
            <div>
              <div className="text-sm font-semibold text-foreground">Secrets 脱敏</div>
              <div className="mt-1 text-xs text-muted-foreground">尝试识别并遮蔽 API Key/Token 等敏感信息</div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ secrets_redact: !isSecretsRedactEnabled })}
              className="shrink-0"
              aria-label="Toggle secrets redact"
            >
              {isSecretsRedactEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/30 p-4">
            <div>
              <div className="text-sm font-semibold text-foreground">质量过滤触发时隔离</div>
              <div className="mt-1 text-xs text-muted-foreground">
                当触发“低密度/仅目录”等过滤时，将文档标记为 quarantined（便于排查）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ quarantine_on_drop: !isQuarantineOnDropEnabled })}
              className="shrink-0"
              aria-label="Toggle quarantine on drop"
            >
              {isQuarantineOnDropEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
