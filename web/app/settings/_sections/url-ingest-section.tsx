'use client'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { DangerZonePanel } from '@/components/settings/danger-zone-panel'
import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Input } from '@/components/ui/input'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'
import type { SystemSettings } from '@/lib/api'
import { cn } from '@/lib/utils'

type UrlIngestSettings = NonNullable<SystemSettings['url_ingest']>

type UrlIngestSectionProps = {
  urlIngest: UrlIngestSettings
  updateUrlIngest: (patch: Partial<UrlIngestSettings>) => void
}

export function UrlIngestSection({
  urlIngest,
  updateUrlIngest,
}: Readonly<UrlIngestSectionProps>) {
  const isUrlIngestEnabled = urlIngest.enabled
  const allowsPrivateIps = urlIngest.allow_private_ips
  const followsRedirects = urlIngest.follow_redirects

  return (
    <section>
      <DangerZonePanel
        title="网页采集外联"
        impact="服务端外联抓取，存在 SSRF 与资源消耗风险；建议默认关闭或配置允许列表"
        badge="SSRF 风险"
        compact
        tone="neutral"
        icon="help"
      >
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-3 rounded-lg border border-info/15 bg-info/[0.025] px-3 py-2.5">
            <div>
              <div className={settingsTextTokens.panelTitle}>网页采集入口</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                允许通过网页地址拉取内容并写入知识库；知识库页面的网页采集会依赖此开关
              </div>
            </div>
            {isUrlIngestEnabled ? (
              <SettingsSwitch
                checked
                onClick={() => updateUrlIngest({ enabled: false })}
                className="shrink-0"
                aria-label="切换网页采集开关"
              />
            ) : (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <SettingsSwitch
                    checked={false}
                    className="shrink-0"
                    aria-label="切换网页采集开关"
                  />
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>启用网页采集？</AlertDialogTitle>
                    <AlertDialogDescription>
                      启用后端网页采集会让服务端对外发起网络请求，存在服务端请求伪造风险生产环境建议保持关闭，或配置出口防火墙与允许列表
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>取消</AlertDialogCancel>
                    <AlertDialogAction onClick={() => updateUrlIngest({ enabled: true })}>
                      启用
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <div className={cn(settingsTextTokens.fieldLabel, 'mb-1')}>
                最大下载大小（字节）
              </div>
              <Input
                type="number"
                min={0}
                value={urlIngest.max_bytes}
                className="h-8 border-info/15 bg-info/[0.025] text-[12px]"
                onChange={(event) =>
                  updateUrlIngest({
                    max_bytes: Math.max(0, Number.parseInt(event.target.value || '0', 10)),
                  })
                }
              />
            </div>
            <div>
              <div className={cn(settingsTextTokens.fieldLabel, 'mb-1')}>
                下载超时（秒）
              </div>
              <Input
                type="number"
                min={0}
                step="0.5"
                value={urlIngest.timeout_sec}
                className="h-8 border-info/15 bg-info/[0.025] text-[12px]"
                onChange={(event) =>
                  updateUrlIngest({
                    timeout_sec: Math.max(0, Number.parseFloat(event.target.value || '0')),
                  })
                }
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="flex items-start justify-between gap-3 rounded-lg border border-info/15 bg-info/[0.025] px-3 py-2.5">
              <div>
                <div className={settingsTextTokens.panelTitle}>允许访问内网/私网 IP</div>
                <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                  高风险：网页采集与 LLM 连通测试可能访问内网服务
                </div>
              </div>
              {allowsPrivateIps ? (
                <SettingsSwitch
                  checked
                  onClick={() => updateUrlIngest({ allow_private_ips: false })}
                  className="shrink-0"
                  aria-label="切换允许私网 IP 访问"
                />
              ) : (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <SettingsSwitch
                      checked={false}
                      className="shrink-0"
                      aria-label="切换允许私网 IP 访问"
                    />
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>允许访问内网/私网 IP？</AlertDialogTitle>
                      <AlertDialogDescription>
                        风险极高：开启后，网页采集与 LLM 连通测试可能访问内网/私网地址
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>取消</AlertDialogCancel>
                      <AlertDialogAction onClick={() => updateUrlIngest({ allow_private_ips: true })}>
                        开启
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>

            <div className="flex items-start justify-between gap-3 rounded-lg border border-info/15 bg-info/[0.025] px-3 py-2.5">
              <div>
                <div className={settingsTextTokens.panelTitle}>跟随重定向</div>
                <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                  可能重定向到内网/大文件；建议保持关闭
                </div>
              </div>
              {followsRedirects ? (
                <SettingsSwitch
                  checked
                  onClick={() => updateUrlIngest({ follow_redirects: false })}
                  className="shrink-0"
                  aria-label="切换跟随重定向"
                />
              ) : (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <SettingsSwitch
                      checked={false}
                      className="shrink-0"
                      aria-label="切换跟随重定向"
                    />
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>跟随重定向？</AlertDialogTitle>
                      <AlertDialogDescription>
                        开启后，网页采集可能跟随重定向到内网地址或大文件，存在服务端请求伪造和资源消耗风险确认开启吗？
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>取消</AlertDialogCancel>
                      <AlertDialogAction onClick={() => updateUrlIngest({ follow_redirects: true })}>
                        开启
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>
          </div>
        </div>
      </DangerZonePanel>
    </section>
  )
}
