'use client'

import { Input } from '@/components/ui/input'
import type { CacheConfig, ChatConfig, LangGraphConfig, SafetyConfig } from '@/lib/api'
import { Database, EyeOff, Network, Server, ToggleLeft, ToggleRight } from 'lucide-react'

type RuntimeControlsSectionProps = {
  chat: ChatConfig
  updateChat: (patch: Partial<ChatConfig>) => void
  cache: CacheConfig
  updateCache: (patch: Partial<CacheConfig>) => void
  safety: SafetyConfig
  updateSafety: (patch: Partial<SafetyConfig>) => void
  langgraph: LangGraphConfig
  updateLangGraph: (patch: Partial<LangGraphConfig>) => void
}

export function RuntimeControlsSection({
  chat,
  updateChat,
  cache,
  updateCache,
  safety,
  updateSafety,
  langgraph,
  updateLangGraph,
}: Readonly<RuntimeControlsSectionProps>) {
  const isCancelOnDisconnectEnabled = chat.stream_cancel_on_disconnect ?? true
  const isUploadDedupEnabled = cache.upload_dedup_enabled ?? false
  const isChatResponseCacheEnabled = cache.chat_response_cache_enabled ?? false
  const isPiiRedactionEnabled = safety.pii_redaction_enabled ?? false
  const isSubgraphEnabled = langgraph.use_subgraphs ?? false

  return (
    <section>
      <div className="space-y-8 rounded-2xl border border-border bg-card p-6 shadow-sm">
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Server className="h-4 w-4 text-muted-foreground" />
                对话流式稳定性（SSE）
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                心跳用于保活连接；断连自动取消可减少资源浪费（保存后通常可立即生效）
              </div>
            </div>
            <button
              type="button"
              onClick={() =>
                updateChat({
                  stream_cancel_on_disconnect: !isCancelOnDisconnectEnabled,
                })
              }
              className="shrink-0"
              aria-label="切换断连自动取消（chat.stream_cancel_on_disconnect）"
            >
              {isCancelOnDisconnectEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4 pt-2 md:grid-cols-3">
            <div>
              <div className="mb-1 text-xs text-muted-foreground">心跳间隔（heartbeat，秒）</div>
              <Input
                type="number"
                min={0}
                max={120}
                step={1}
                value={chat.stream_heartbeat_sec ?? 10}
                onChange={(event) =>
                  updateChat({ stream_heartbeat_sec: Number.parseFloat(event.target.value || '0') })
                }
              />
            </div>
            <div className="flex items-center text-xs text-muted-foreground md:col-span-2">
              设为 0 将禁用心跳（不推荐，可能被代理/负载均衡断开）
            </div>
          </div>
        </div>

        <div className="space-y-3 border-t pt-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Database className="h-4 w-4 text-muted-foreground" />
                性能与缓存
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                去重/缓存属于“尽力而为（best-effort）”，依赖 Redis 时会“失败放行（fail-open）”（不可用时不影响主流程）
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 pt-2 md:grid-cols-2">
            <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/30 p-4">
              <div>
                <div className="text-sm font-semibold text-foreground">上传去重（数据集内，upload_dedup）</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  同 file_sha256 + pipeline_hash 时直接复用已存在文档，减少重复入库/embedding
                </div>
              </div>
              <button
                type="button"
                onClick={() => updateCache({ upload_dedup_enabled: !isUploadDedupEnabled })}
                className="shrink-0"
                aria-label="切换上传去重（cache.upload_dedup_enabled）"
              >
                {isUploadDedupEnabled ? (
                  <ToggleRight className="h-10 w-10 text-primary" />
                ) : (
                  <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
                )}
              </button>
            </div>

            <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-muted/30 p-4">
              <div>
                <div className="text-sm font-semibold text-foreground">对话响应缓存（Redis）</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  相同问题+相同文档范围+相同配置命中后直接返回，降低大语言模型（LLM）/检索成本
                </div>
              </div>
              <button
                type="button"
                onClick={() =>
                  updateCache({ chat_response_cache_enabled: !isChatResponseCacheEnabled })
                }
                className="shrink-0"
                aria-label="切换对话响应缓存（cache.chat_response_cache_enabled）"
              >
                {isChatResponseCacheEnabled ? (
                  <ToggleRight className="h-10 w-10 text-primary" />
                ) : (
                  <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
                )}
              </button>
            </div>
          </div>

          {isChatResponseCacheEnabled ? (
            <div className="grid grid-cols-1 gap-4 pt-2 md:grid-cols-3">
              <div>
                <div className="mb-1 text-xs text-muted-foreground">过期时间（TTL，秒）</div>
                <Input
                  type="number"
                  min={0}
                  max={86400}
                  value={cache.chat_response_cache_ttl_sec ?? 300}
                  onChange={(event) =>
                    updateCache({
                      chat_response_cache_ttl_sec: Number.parseInt(event.target.value || '0', 10),
                    })
                  }
                />
              </div>
              <div>
                <div className="mb-1 text-xs text-muted-foreground">最大值字节数（max_value_bytes）</div>
                <Input
                  type="number"
                  min={0}
                  max={5000000}
                  value={cache.chat_response_cache_max_value_bytes ?? 200000}
                  onChange={(event) =>
                    updateCache({
                      chat_response_cache_max_value_bytes: Number.parseInt(
                        event.target.value || '0',
                        10
                      ),
                    })
                  }
                />
              </div>
              <div className="flex items-center gap-2 pt-5">
                <input
                  type="checkbox"
                  checked={cache.chat_response_cache_require_empty_history ?? true}
                  onChange={(event) =>
                    updateCache({ chat_response_cache_require_empty_history: event.target.checked })
                  }
                  className="h-4 w-4 accent-primary"
                />
                <span className="text-sm text-foreground/80">仅缓存无历史请求</span>
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-3 border-t pt-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <EyeOff className="h-4 w-4 text-muted-foreground" />
                PII 脱敏
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                对模型输入/输出与工具调用做脱敏（流式输出会做延迟缓冲 holdback，以减少漏出）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateSafety({ pii_redaction_enabled: !isPiiRedactionEnabled })}
              className="shrink-0"
              aria-label="切换 PII 脱敏（safety.pii_redaction_enabled）"
            >
              {isPiiRedactionEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>

          {isPiiRedactionEnabled ? (
            <div className="grid grid-cols-1 gap-4 pt-2 md:grid-cols-3">
              <div>
                <div className="mb-1 text-xs text-muted-foreground">脱敏占位符</div>
                <Input
                  value={safety.pii_redaction_mask ?? '[REDACTED]'}
                  onChange={(event) => updateSafety({ pii_redaction_mask: event.target.value })}
                />
              </div>
              <div>
                <div className="mb-1 text-xs text-muted-foreground">流式延迟缓冲字符数（holdback）</div>
                <Input
                  type="number"
                  min={0}
                  max={2048}
                  value={safety.pii_stream_holdback_chars ?? 128}
                  onChange={(event) =>
                    updateSafety({
                      pii_stream_holdback_chars: Number.parseInt(event.target.value || '0', 10),
                    })
                  }
                />
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-3 border-t pt-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Network className="h-4 w-4 text-muted-foreground" />
                LangGraph 子图组合（Subgraph）
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                将检索/生成作为子图节点组合（更模块化，便于后续扩展）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateLangGraph({ use_subgraphs: !isSubgraphEnabled })}
              className="shrink-0"
              aria-label="切换子图组合（langgraph.use_subgraphs）"
            >
              {isSubgraphEnabled ? (
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
