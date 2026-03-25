'use client'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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
import { Input } from '@/components/ui/input'
import type { SystemSettings } from '@/lib/api'
import { AlertCircle, Network, ToggleLeft, ToggleRight } from 'lucide-react'

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
      <div className="mb-6 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Network className="h-5 w-5 text-primary" />
          URL 导入
        </h2>
        <div className="flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
          <span>保存后通常可立即生效</span>
        </div>
      </div>

      <div className="space-y-6 rounded-2xl border border-border bg-card p-6 shadow-sm">
        <Alert variant="destructive" className="shadow-soft/40">
          <AlertCircle className="h-4 w-4" />
          <div>
            <AlertTitle>安全提示</AlertTitle>
            <AlertDescription className="text-foreground/80">
              URL 导入会由后端发起网络请求，存在 SSRF 风险。生产环境建议保持关闭，或配置 egress 防火墙/allowlist。
            </AlertDescription>
          </div>
        </Alert>

        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-semibold text-foreground">启用 URL 导入</div>
            <div className="mt-1 text-xs text-muted-foreground">
              允许通过 URL 拉取内容并入库（知识库页面的“URL 导入”会依赖此开关）
            </div>
          </div>
          {isUrlIngestEnabled ? (
            <button
              type="button"
              onClick={() => updateUrlIngest({ enabled: false })}
              className="shrink-0"
              aria-label="Toggle URL ingest"
            >
              <ToggleRight className="h-10 w-10 text-primary" />
            </button>
          ) : (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button type="button" className="shrink-0" aria-label="Toggle URL ingest">
                  <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>启用 URL 导入？</AlertDialogTitle>
                  <AlertDialogDescription>
                    启用后端 URL 导入会让服务端对外发起网络请求，存在 SSRF 风险。生产环境建议保持关闭，或配置 egress 防火墙/allowlist。
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

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <div className="mb-1 text-xs text-muted-foreground">最大下载大小（字节）</div>
            <Input
              type="number"
              min={0}
              value={urlIngest.max_bytes}
              onChange={(event) =>
                updateUrlIngest({
                  max_bytes: Math.max(0, Number.parseInt(event.target.value || '0', 10)),
                })
              }
            />
          </div>
          <div>
            <div className="mb-1 text-xs text-muted-foreground">下载超时（秒）</div>
            <Input
              type="number"
              min={0}
              step="0.5"
              value={urlIngest.timeout_sec}
              onChange={(event) =>
                updateUrlIngest({
                  timeout_sec: Math.max(0, Number.parseFloat(event.target.value || '0')),
                })
              }
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/30 p-4">
            <div>
              <div className="text-sm font-semibold text-foreground">允许访问内网/私网 IP</div>
              <div className="mt-1 text-xs text-muted-foreground">
                高风险：可能导致 SSRF 打到内网服务（强烈不建议）
              </div>
            </div>
            {allowsPrivateIps ? (
              <button
                type="button"
                onClick={() => updateUrlIngest({ allow_private_ips: false })}
                className="shrink-0"
                aria-label="Toggle allow private IPs"
              >
                <ToggleRight className="h-10 w-10 text-primary" />
              </button>
            ) : (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <button type="button" className="shrink-0" aria-label="Toggle allow private IPs">
                    <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
                  </button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>允许访问内网/私网 IP？</AlertDialogTitle>
                    <AlertDialogDescription>
                      风险极高：可能导致 SSRF 打到内网服务（强烈不建议）。确认开启后，后端 URL 导入可能访问内网/私网地址。
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

          <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/30 p-4">
            <div>
              <div className="text-sm font-semibold text-foreground">跟随重定向</div>
              <div className="mt-1 text-xs text-muted-foreground">
                可能重定向到内网/大文件；建议保持关闭
              </div>
            </div>
            {followsRedirects ? (
              <button
                type="button"
                onClick={() => updateUrlIngest({ follow_redirects: false })}
                className="shrink-0"
                aria-label="Toggle follow redirects"
              >
                <ToggleRight className="h-10 w-10 text-primary" />
              </button>
            ) : (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <button type="button" className="shrink-0" aria-label="Toggle follow redirects">
                    <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
                  </button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>跟随重定向？</AlertDialogTitle>
                    <AlertDialogDescription>
                      开启后，URL 导入可能跟随重定向到内网地址或大文件，存在 SSRF/资源消耗风险。确认开启吗？
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
    </section>
  )
}
