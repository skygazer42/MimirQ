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
import { Input } from '@/components/ui/input'
import { systemPageTokens } from '@/components/ui/system-page-tokens'
import type { SystemSettings } from '@/lib/api'
import { cn } from '@/lib/utils'
import { ToggleLeft, ToggleRight } from 'lucide-react'

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
  const toggleIconClass = 'h-7 w-7'

  return (
    <section>
      <DangerZonePanel
        title="网页采集外联"
        impact="服务端外联抓取，存在 SSRF 与资源消耗风险；建议默认关闭或配置允许列表。"
        badge="SSRF 风险"
        compact
        tone="neutral"
        icon="help"
      >
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>网页采集入口</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                允许通过网页地址拉取内容并写入知识库；知识库页面的网页采集会依赖此开关。
              </div>
            </div>
            {isUrlIngestEnabled ? (
              <button
                type="button"
                onClick={() => updateUrlIngest({ enabled: false })}
                className="shrink-0"
                aria-label="切换网页采集开关"
              >
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              </button>
            ) : (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <button
                    type="button"
                    className="shrink-0"
                    aria-label="切换网页采集开关"
                  >
                    <ToggleLeft
                      className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')}
                    />
                  </button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>启用网页采集？</AlertDialogTitle>
                    <AlertDialogDescription>
                      启用后端网页采集会让服务端对外发起网络请求，存在服务端请求伪造风险。生产环境建议保持关闭，或配置出口防火墙与允许列表。
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
              <div className="mb-1 text-[11px] font-semibold text-foreground/80">
                最大下载大小（字节）
              </div>
              <Input
                type="number"
                min={0}
                value={urlIngest.max_bytes}
                className="h-8 text-[12px]"
                onChange={(event) =>
                  updateUrlIngest({
                    max_bytes: Math.max(0, Number.parseInt(event.target.value || '0', 10)),
                  })
                }
              />
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold text-foreground/80">
                下载超时（秒）
              </div>
              <Input
                type="number"
                min={0}
                step="0.5"
                value={urlIngest.timeout_sec}
                className="h-8 text-[12px]"
                onChange={(event) =>
                  updateUrlIngest({
                    timeout_sec: Math.max(0, Number.parseFloat(event.target.value || '0')),
                  })
                }
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
              <div>
                <div className={systemPageTokens.heading}>允许访问内网/私网 IP</div>
                <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                  高风险：可能访问到内网服务（强烈不建议）
                </div>
              </div>
              {allowsPrivateIps ? (
                <button
                  type="button"
                  onClick={() => updateUrlIngest({ allow_private_ips: false })}
                  className="shrink-0"
                  aria-label="切换允许私网 IP 访问"
                >
                  <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
                </button>
              ) : (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button
                      type="button"
                      className="shrink-0"
                      aria-label="切换允许私网 IP 访问"
                    >
                      <ToggleLeft
                        className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')}
                      />
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>允许访问内网/私网 IP？</AlertDialogTitle>
                      <AlertDialogDescription>
                        风险极高：可能访问到内网服务（强烈不建议）。确认开启后，后端网页采集可能访问内网/私网地址。
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

            <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
              <div>
                <div className={systemPageTokens.heading}>跟随重定向</div>
                <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                  可能重定向到内网/大文件；建议保持关闭
                </div>
              </div>
              {followsRedirects ? (
                <button
                  type="button"
                  onClick={() => updateUrlIngest({ follow_redirects: false })}
                  className="shrink-0"
                  aria-label="切换跟随重定向"
                >
                  <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
                </button>
              ) : (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button
                      type="button"
                      className="shrink-0"
                      aria-label="切换跟随重定向"
                    >
                      <ToggleLeft
                        className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')}
                      />
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>跟随重定向？</AlertDialogTitle>
                      <AlertDialogDescription>
                        开启后，网页采集可能跟随重定向到内网地址或大文件，存在服务端请求伪造和资源消耗风险。确认开启吗？
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
