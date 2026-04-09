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
import { systemDenseControls, systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
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
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-[-0.01em] text-foreground">
          <Layers className="h-4 w-4 text-primary" />
          LTR 模型注册表
        </h2>
        <div className="inline-flex items-center gap-1 rounded-full border border-border/70 bg-muted/50 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
          <span>支持激活与一键回滚</span>
        </div>
      </div>

      <div className="space-y-3">
        {ltrError ? (
          <Alert
            variant="destructive"
            className="p-3 shadow-none [&>svg]:left-3 [&>svg]:top-3 [&>svg~*]:pl-6"
          >
            <XCircle className="h-3.5 w-3.5" />
            <div>
              <AlertTitle className="text-xs">LTR 注册表加载失败</AlertTitle>
              <AlertDescription className="text-[11px] leading-4 text-foreground/80">{ltrError}</AlertDescription>
            </div>
          </Alert>
        ) : null}

        {ltrMessage ? (
          <Alert
            variant={ltrMessage.type === 'success' ? 'success' : 'destructive'}
            className="p-3 shadow-none [&>svg]:left-3 [&>svg]:top-3 [&>svg~*]:pl-6"
          >
            {ltrMessage.type === 'success' ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : (
              <XCircle className="h-3.5 w-3.5" />
            )}
            <div>
              <AlertTitle className="text-xs">{ltrMessage.type === 'success' ? '操作成功' : '操作失败'}</AlertTitle>
              <AlertDescription className="text-[11px] leading-4 text-foreground/80">{ltrMessage.text}</AlertDescription>
            </div>
          </Alert>
        ) : null}

        <Panel
          padding="none"
          className={cn(systemWorkbenchTokens.panel, 'space-y-3 p-3.5')}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className={systemPageTokens.heading}>上传并注册</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5 text-pretty')}>
                需要上传 XGBoost JSON 模型文件与配套清单（sidecar manifest，会校验 sha256 与 feature schema）。
              </div>
            </div>
            <Button
              onClick={onRegister}
              disabled={!ltrUploadReady || ltrUploading}
              className={cn(systemDenseControls.primaryButton, 'gap-1.5')}
            >
              <RefreshCw
                className={cn('h-3.5 w-3.5', ltrUploading && 'animate-spin motion-reduce:animate-none')}
              />
              {ltrUploading ? '注册中...' : '注册模型'}
            </Button>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <div className="text-[11px] font-semibold text-foreground/80">模型文件（JSON）</div>
              <Input
                key={`ltr-model-${ltrUploadResetKey}`}
                type="file"
                accept=".json,application/json"
                onChange={(event) => onModelFileChange(event.target.files?.[0] || null)}
                className="h-8 text-[11px] file:text-[11px]"
              />
            </div>
            <div className="space-y-1.5">
              <div className="text-[11px] font-semibold text-foreground/80">Manifest（JSON）</div>
              <Input
                key={`ltr-manifest-${ltrUploadResetKey}`}
                type="file"
                accept=".json,application/json"
                onChange={(event) => onManifestFileChange(event.target.files?.[0] || null)}
                className="h-8 text-[11px] file:text-[11px]"
              />
            </div>
          </div>
        </Panel>

        <Panel
          padding="none"
          className={cn(systemWorkbenchTokens.panel, 'space-y-3 p-3.5')}
        >
          <div className="flex items-center justify-between gap-2.5">
            <div>
              <div className={systemPageTokens.heading}>已注册模型</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                激活后会在后端运行时使用该模型进行 LTR 重排序（失败时关闭流程，fail-closed）。
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                onClick={onRefreshList}
                disabled={ltrLoading || ltrBusyModelId !== null}
                className={cn(systemDenseControls.outlineButton, 'gap-1.5')}
              >
                <RefreshCw
                  className={cn('h-3.5 w-3.5', ltrLoading && 'animate-spin motion-reduce:animate-none')}
                />
                刷新列表
              </Button>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="outline"
                    disabled={ltrLoading || ltrModels.length === 0 || ltrBusyModelId !== null}
                    className={cn(systemDenseControls.outlineButton, 'gap-1.5')}
                  >
                    <AlertCircle className="h-3.5 w-3.5" />
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
            <div className="rounded-lg border border-border/70 bg-muted/20 p-4">
              <div className="text-[13px] font-semibold text-foreground">暂无已注册模型</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                先在上方上传并注册一个模型，再进行激活或回滚。
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border/70">
              <table aria-label="LTR 模型注册表" className="w-full text-[11px]">
                <thead className="bg-muted/35">
                  <tr className="text-left">
                    <th className={cn(systemPageTokens.tableHead, 'px-2.5 py-1.5 whitespace-nowrap')}>状态</th>
                    <th className={cn(systemPageTokens.tableHead, 'px-2.5 py-1.5 whitespace-nowrap')}>模型 ID</th>
                    <th className={cn(systemPageTokens.tableHead, 'px-2.5 py-1.5 whitespace-nowrap')}>sha256 校验</th>
                    <th className={cn(systemPageTokens.tableHead, 'px-2.5 py-1.5 whitespace-nowrap')}>特征</th>
                    <th className={cn(systemPageTokens.tableHead, 'px-2.5 py-1.5 whitespace-nowrap tabular-nums')}>大小</th>
                    <th className={cn(systemPageTokens.tableHead, 'px-2.5 py-1.5 whitespace-nowrap')}>创建时间</th>
                    <th className={cn(systemPageTokens.tableHead, 'px-2.5 py-1.5 whitespace-nowrap')}>操作</th>
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
                          'border-t border-border/70 align-top hover:bg-muted/20',
                          isActive && 'bg-success/10'
                        )}
                      >
                        <td className="px-2.5 py-1.5">
                          {isActive ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-success/25 bg-success/10 px-1.5 py-0.5 text-[10px] font-semibold text-success">
                              <CheckCircle2 className="h-3 w-3" />
                              已激活（ACTIVE）
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full border border-border/70 bg-muted/45 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                              空闲（idle）
                            </span>
                          )}
                        </td>
                        <td className="px-2.5 py-1.5 font-mono text-[10px] tabular-nums">
                          <span title={model.model_id}>{shortId(model.model_id, 16)}</span>
                        </td>
                        <td className="px-2.5 py-1.5 font-mono text-[10px] tabular-nums">
                          <span title={model.model_sha256}>{shortId(model.model_sha256, 12)}</span>
                        </td>
                        <td className="px-2.5 py-1.5 text-[10px] text-muted-foreground">
                          <div className="tabular-nums">v{model.feature_spec_version}</div>
                          <div className="max-w-[15rem] truncate" title={model.feature_schema || ''}>
                            {model.feature_schema || '-'}
                          </div>
                          <div className="tabular-nums">
                            {Array.isArray(model.feature_names) ? model.feature_names.length : 0} 维（dims）
                          </div>
                        </td>
                        <td className="px-2.5 py-1.5 text-[10px] tabular-nums">
                          {formatBytes(model.size_bytes)}
                        </td>
                        <td className="px-2.5 py-1.5 text-[10px] tabular-nums">
                          {formatTime(model.created_at)}
                        </td>
                        <td className="px-2.5 py-1.5">
                          {isActive ? (
                            <Button
                              variant="outline"
                              disabled
                              className={cn(systemDenseControls.inlineAction, 'h-7 px-2.5 text-[11px]')}
                            >
                              已激活
                            </Button>
                          ) : (
                            <AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button
                                  variant="outline"
                                  disabled={ltrBusyModelId !== null}
                                  className={cn(systemDenseControls.inlineAction, 'h-7 gap-1.5 px-2.5 text-[11px]')}
                                >
                                  <RefreshCw
                                    className={cn(
                                      'h-3 w-3',
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
