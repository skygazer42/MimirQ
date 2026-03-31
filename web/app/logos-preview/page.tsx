/**
 * Logo 预览页面 - 用于测试和查看所有品牌图标
 */
import { AppFrame } from '@/components/app-frame'
import { ProviderIcon } from '@/components/provider-icon'
import { Card, CardContent } from '@/components/ui/card'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Grid3X3 } from 'lucide-react'

const providers = [
  { id: 'openai', name: 'OpenAI', color: '#10A37F' },
  { id: 'openai-embedding', name: 'OpenAI Embedding', color: '#10A37F' },
  { id: 'anthropic', name: 'Anthropic', color: '#CC785C' },
  { id: 'deepseek', name: 'DeepSeek', color: '#0066FF' },
  { id: 'zhipu', name: '智谱 AI', color: '#9333EA' },
  { id: 'qwen', name: '通义千问', color: '#0EA5E9' },
  { id: 'moonshot', name: 'Moonshot AI', color: '#4F46E5' },
  { id: 'ollama', name: 'Ollama', color: '#000000' },
  { id: 'ark', name: '火山引擎', color: '#FF6A00' },
  { id: 'lingyiwanwu', name: '零一万物', color: '#3B82F6' },
  { id: 'qianfan', name: '百度千帆', color: '#2563EB' },
  { id: 'siliconflow', name: 'SiliconFlow', color: '#7C3AED' },
  { id: 'openrouter', name: 'OpenRouter', color: '#6366F1' },
  { id: 'together', name: 'Together AI', color: '#0EA5E9' },
  { id: 'cohere-reranker', name: 'Cohere Reranker', color: '#0EA5E9' },
  { id: 'jina-reranker', name: 'Jina Reranker', color: '#8B5CF6' },
  { id: 'local-embedding', name: '本地 Embedding', color: '#10B981' },
  { id: 'local-reranker', name: '本地 Reranker', color: '#F97316' },
]

export default function LogosPreviewPage() {
  return (
    <AppFrame>
      <PageScaffold
        title="品牌 Logo 预览"
        badge="LOGOS"
        icon={Grid3X3}
        iconColor="text-accent"
        description="查看所有模型提供商的图标展示与适配效果"
      >

        {/* Logo 网格 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
          {providers.map((provider) => (
            <Card
              key={provider.id}
              className="rounded-xl border border-border bg-card shadow-soft hover:shadow-strong transition-shadow"
            >
              <CardContent className="p-6">
                <div className="flex flex-col items-center text-center">
                  {/* Logo 大尺寸 */}
                  <div className="w-24 h-24 flex items-center justify-center mb-4 rounded-lg bg-muted/40 border border-border/60">
                    <ProviderIcon providerId={provider.id} className="w-16 h-16" />
                  </div>
                  <h3 className="text-lg font-semibold text-foreground mb-1">
                    {provider.name}
                  </h3>
                  <p className="text-sm text-muted-foreground mb-3">{provider.id}</p>
                  <div className="flex items-center gap-2">
                    <div
                      className="w-6 h-6 rounded border border-border"
                      style={{ backgroundColor: provider.color }}
                    />
                    <span className="text-xs font-mono text-muted-foreground">
                      {provider.color}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* 不同尺寸预览 */}
        <Card className="rounded-xl border border-border bg-card shadow-soft">
          <CardContent className="p-8">
          <h2 className="text-2xl font-bold text-foreground mb-6">
            尺寸对比
          </h2>
          <div className="space-y-8">
            {[
              { size: 'w-6 h-6', label: '小 (24px)', px: '24px' },
              { size: 'w-8 h-8', label: '中 (32px)', px: '32px' },
              { size: 'w-12 h-12', label: '大 (48px)', px: '48px' },
              { size: 'w-16 h-16', label: '特大 (64px)', px: '64px' },
            ].map((sizeConfig) => (
              <div key={sizeConfig.size}>
                <h3 className="text-sm font-medium text-foreground/80 mb-3">
                  {sizeConfig.label}
                </h3>
                <div className="flex items-center gap-4 flex-wrap">
                  {providers.map((provider) => (
                    <div
                      key={provider.id}
                      className="flex flex-col items-center gap-2"
                    >
                      <div className="p-2 bg-muted/40 border border-border/60 rounded-lg">
                        <ProviderIcon
                          providerId={provider.id}
                          className={sizeConfig.size}
                        />
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {provider.name}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          </CardContent>
        </Card>

        {/* 背景对比 */}
        <Card className="mt-6 rounded-xl border border-border bg-card shadow-soft">
          <CardContent className="p-8">
          <h2 className="text-2xl font-bold text-foreground mb-6">
            背景对比
          </h2>
          <div className="grid grid-cols-3 gap-6">
            {/* 白色背景 */}
            <div>
              <h3 className="text-sm font-medium text-foreground/80 mb-3">
                白色背景
              </h3>
              <div className="bg-background p-4 rounded-lg border border-border">
                <div className="flex flex-wrap gap-3">
                  {providers.map((provider) => (
                    <ProviderIcon
                      key={provider.id}
                      providerId={provider.id}
                      className="w-10 h-10"
                    />
                  ))}
                </div>
              </div>
            </div>

            {/* 灰色背景 */}
            <div>
              <h3 className="text-sm font-medium text-foreground/80 mb-3">
                灰色背景
              </h3>
              <div className="bg-muted/60 p-4 rounded-lg border border-border/60">
                <div className="flex flex-wrap gap-3">
                  {providers.map((provider) => (
                    <ProviderIcon
                      key={provider.id}
                      providerId={provider.id}
                      className="w-10 h-10"
                    />
                  ))}
                </div>
              </div>
            </div>

            {/* 深色背景 */}
            <div>
              <h3 className="text-sm font-medium text-foreground/80 mb-3">
                深色背景
              </h3>
              <div className="bg-slate-950 p-4 rounded-lg border border-border/60">
                <div className="flex flex-wrap gap-3">
                  {providers.map((provider) => (
                    <ProviderIcon
                      key={provider.id}
                      providerId={provider.id}
                      className="w-10 h-10"
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>
          </CardContent>
        </Card>

        {/* 说明 */}
        <Card className="mt-6 rounded-xl border border-border bg-card shadow-soft">
          <CardContent className="p-6">
            <h3 className="text-lg font-semibold text-foreground mb-2">
              使用说明
            </h3>
            <ul className="text-sm text-muted-foreground space-y-1">
              <li>• ProviderIcon 优先使用 LobeHub SVG：<code className="bg-muted px-1 rounded">/public/logos/lobehub/</code></li>
              <li>• 旧资源兜底：<code className="bg-muted px-1 rounded">/public/logos/</code>（PNG/SVG）</li>
              <li>• 同步脚本：<code className="bg-muted px-1 rounded">node web/scripts/sync-lobehub-icons.mjs</code></li>
              <li>• 组件: <code className="bg-muted px-1 rounded">&lt;ProviderIcon providerId=&quot;openai&quot; /&gt;</code></li>
              <li>• 建议尺寸: 24px (小)、32px (中)、48px (大)</li>
              <li>• 如需替换,访问 <code className="bg-muted px-1 rounded">/public/logos/README.md</code> 查看指南</li>
            </ul>
          </CardContent>
        </Card>
      </PageScaffold>
    </AppFrame>
  )
}
