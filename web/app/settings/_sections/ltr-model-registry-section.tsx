'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
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
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import type { LTRModelInfo } from '@/lib/api'
import { cn } from '@/lib/utils'
import { AlertCircle, CheckCircle2, Layers, RefreshCw, XCircle } from 'lucide-react'

type LtrMessage = { type: 'success' | 'error'; text: string } | null

type LtrModelRegistrySectionProps = {
  ltrError: string | null
  ltrMessage: LtrMessage
  ltrUploading: boolean
  ltrUploadReady: boolean
  ltrUploadResetKey: number
  ltrLoading: boolean
  ltrBusyModelId: string | null
  ltrModels: LTRModelInfo[]
  onRegister: () => void
  onRefreshList: () => void
  onRollback: () => void
  onActivate: (modelId: string) => void
  onModelFileChange: (file: File | null) => void
  onManifestFileChange: (file: File | null) => void
  formatBytes: (value: unknown) => string
  formatTime: (value: unknown) => string
  shortId: (value: unknown, keep?: number) => string
}

export function LtrModelRegistrySection({
  ltrError,
  ltrMessage,
  ltrUploading,
  ltrUploadReady,
  ltrUploadResetKey,
  ltrLoading,
  ltrBusyModelId,
  ltrModels,
  onRegister,
  onRefreshList,
  onRollback,
  onActivate,
  onModelFileChange,
  onManifestFileChange,
  formatBytes,
  formatTime,
  shortId,
}: Readonly<LtrModelRegistrySectionProps>) {
  return (
    <section>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Layers className="h-5 w-5 text-primary" />
          LTR 模型注册表
        </h2>
        <div className="flex items-center gap-2 rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          <span>支持激活与一键回滚</span>
        </div>
      </div>

      <div className="space-y-4">
        {ltrError ? (
          <Alert variant="destructive" className="shadow-soft/40">
            <XCircle className="h-4 w-4" />
            <div>
              <AlertTitle>LTR 注册表加载失败</AlertTitle>
              <AlertDescription className="text-foreground/80">{ltrError}</AlertDescription>
            </div>
          </Alert>
        ) : null}

        {ltrMessage ? (
          <Alert
            variant={ltrMessage.type === 'success' ? 'success' : 'destructive'}
            className="shadow-soft/40"
          >
            {ltrMessage.type === 'success' ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              <XCircle className="h-4 w-4" />
            )}
            <div>
              <AlertTitle>{ltrMessage.type === 'success' ? '操作成功' : '操作失败'}</AlertTitle>
              <AlertDescription className="text-foreground/80">{ltrMessage.text}</AlertDescription>
            </div>
          </Alert>
        ) : null}

        <Panel padding="lg" className="space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-sm font-semibold text-foreground">上传并注册</div>
              <div className="mt-1 text-xs text-pretty text-muted-foreground">
                需要上传 XGBoost JSON 模型文件与 sidecar manifest（会校验 sha256 与 feature schema）。
              </div>
            </div>
            <Button
              onClick={onRegister}
              disabled={!ltrUploadReady || ltrUploading}
              className="gap-2"
            >
              <RefreshCw
                className={cn('h-4 w-4', ltrUploading && 'animate-spin motion-reduce:animate-none')}
              />
              {ltrUploading ? '注册中...' : '注册模型'}
            </Button>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">模型文件（JSON）</div>
              <Input
                key={`ltr-model-${ltrUploadResetKey}`}
                type="file"
                accept=".json,application/json"
                onChange={(event) => onModelFileChange(event.target.files?.[0] || null)}
              />
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground/80">Manifest（JSON）</div>
              <Input
                key={`ltr-manifest-${ltrUploadResetKey}`}
                type="file"
                accept=".json,application/json"
                onChange={(event) => onManifestFileChange(event.target.files?.[0] || null)}
              />
            </div>
          </div>
        </Panel>

        <Panel padding="lg" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-foreground">已注册模型</div>
              <div className="mt-1 text-xs text-muted-foreground">
                激活后会在后端运行时使用该模型进行 LTR 重排序（失败时 fail-closed）。
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                onClick={onRefreshList}
                disabled={ltrLoading || ltrBusyModelId !== null}
                className="gap-2"
              >
                <RefreshCw
                  className={cn('h-4 w-4', ltrLoading && 'animate-spin motion-reduce:animate-none')}
                />
                刷新列表
              </Button>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="outline"
                    disabled={ltrLoading || ltrModels.length === 0 || ltrBusyModelId !== null}
                    className="gap-2"
                  >
                    <AlertCircle className="h-4 w-4" />
                    回滚
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>回滚 LTR 模型？</AlertDialogTitle>
                    <AlertDialogDescription className="text-pretty">
                      这会将当前激活模型切换回上一版本（仅支持一步回滚）。如果没有上一版本，会返回错误。
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>取消</AlertDialogCancel>
                    <AlertDialogAction onClick={onRollback} className="gap-2">
                      确认回滚
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>

          {ltrModels.length === 0 ? (
            <div className="rounded-xl border border-border bg-muted/30 p-6">
              <div className="text-sm font-medium text-foreground">暂无已注册模型</div>
              <div className="mt-1 text-xs text-muted-foreground">
                先在上方上传并注册一个模型，再进行激活或回滚。
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-border">
              <table aria-label="LTR 模型注册表" className="w-full text-sm">
                <thead className="bg-muted/40">
                  <tr className="text-left">
                    <th className="px-3 py-2 font-medium text-muted-foreground">状态</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">模型 ID</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">sha256</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">特征</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground tabular-nums">大小</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">创建时间</th>
                    <th className="px-3 py-2 font-medium text-muted-foreground">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {ltrModels.map((model) => {
                    const isActive = Boolean(model.active)
                    const isBusy = ltrBusyModelId === String(model.model_id || '').trim()

                    return (
                      <tr
                        key={model.model_id}
                        className={cn(
                          'border-t border-border',
                          isActive && 'bg-success/10'
                        )}
                      >
                        <td className="px-3 py-2">
                          {isActive ? (
                            <span className="inline-flex items-center gap-1.5 rounded-full border border-success/20 bg-success/10 px-2 py-0.5 text-xs text-success">
                              <CheckCircle2 className="h-3 w-3" />
                              ACTIVE
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                              idle
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs tabular-nums">
                          <span title={model.model_id}>{shortId(model.model_id, 16)}</span>
                        </td>
                        <td className="px-3 py-2 font-mono text-xs tabular-nums">
                          <span title={model.model_sha256}>{shortId(model.model_sha256, 12)}</span>
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground">
                          <div className="tabular-nums">v{model.feature_spec_version}</div>
                          <div className="max-w-[18rem] truncate" title={model.feature_schema || ''}>
                            {model.feature_schema || '-'}
                          </div>
                          <div className="tabular-nums">
                            {Array.isArray(model.feature_names) ? model.feature_names.length : 0} dims
                          </div>
                        </td>
                        <td className="px-3 py-2 text-xs tabular-nums">
                          {formatBytes(model.size_bytes)}
                        </td>
                        <td className="px-3 py-2 text-xs tabular-nums">
                          {formatTime(model.created_at)}
                        </td>
                        <td className="px-3 py-2">
                          {isActive ? (
                            <Button variant="outline" disabled className="h-8 px-3 text-xs">
                              已激活
                            </Button>
                          ) : (
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button
                                  variant="outline"
                                  disabled={ltrBusyModelId !== null}
                                  className="h-8 gap-2 px-3 text-xs"
                                >
                                  <RefreshCw
                                    className={cn(
                                      'h-3.5 w-3.5',
                                      isBusy && 'animate-spin motion-reduce:animate-none'
                                    )}
                                  />
                                  激活
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>激活该 LTR 模型？</AlertDialogTitle>
                                  <AlertDialogDescription className="text-pretty">
                                    将切换当前在线重排序模型到该版本。你可以使用“回滚”退回到上一版本。
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <div className="space-y-1 rounded-lg border border-border bg-muted/30 p-3 text-xs">
                                  <div className="font-mono">model_id: {String(model.model_id || '')}</div>
                                  <div className="font-mono">sha256: {String(model.model_sha256 || '')}</div>
                                </div>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>取消</AlertDialogCancel>
                                  <AlertDialogAction
                                    onClick={() => onActivate(String(model.model_id || ''))}
                                  >
                                    确认激活
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </section>
  )
}
