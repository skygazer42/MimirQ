'use client'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
import type { SystemSettings } from '@/lib/api'
import { cn } from '@/lib/utils'
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
  const toggleIconClass = 'h-7 w-7'

  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-[-0.01em] text-foreground">
          <EyeOff className="h-4 w-4 text-primary" />
          数据治理
        </h2>
        <div className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
          <span>保存后通常可立即生效</span>
        </div>
      </div>

      <div className={cn(systemWorkbenchTokens.panel, 'space-y-3 p-3.5')}>
        <Alert className="p-3 shadow-none [&>svg]:left-3 [&>svg]:top-3 [&>svg~*]:pl-6">
          <AlertCircle className="h-3.5 w-3.5" />
          <div>
            <AlertTitle className="text-xs">默认治理规则</AlertTitle>
            <AlertDescription className="text-[11px] leading-4 text-foreground/80">
              这些开关会影响“入库前清洗/脱敏”，用于没有单独配置管线（dataset/document pipeline overrides）时的默认行为。
            </AlertDescription>
          </div>
        </Alert>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>启用数据治理</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>打开后才会应用下方治理项（对新入库文档生效）</div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ enabled: !isGovernanceEnabled })}
              className="shrink-0"
              aria-label="切换数据治理开关（governance.enabled）"
            >
              {isGovernanceEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>PII 脱敏</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                尝试识别并匿名化手机号/邮箱等个人信息（可能影响检索/可读性）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ pii_anonymize: !isPiiAnonymizeEnabled })}
              className="shrink-0"
              aria-label="切换 PII 脱敏（governance.pii_anonymize）"
            >
              {isPiiAnonymizeEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>密钥信息脱敏（secrets）</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                尝试识别并遮蔽 API 密钥（API Key）/令牌（Token）等敏感信息
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ secrets_redact: !isSecretsRedactEnabled })}
              className="shrink-0"
              aria-label="切换密钥信息脱敏（governance.secrets_redact）"
            >
              {isSecretsRedactEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>质量过滤触发时隔离</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                当触发“低密度/仅目录”等过滤时，将文档标记为“已隔离（quarantined）”（便于排查）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ quarantine_on_drop: !isQuarantineOnDropEnabled })}
              className="shrink-0"
              aria-label="切换过滤后隔离（governance.quarantine_on_drop）"
            >
              {isQuarantineOnDropEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
