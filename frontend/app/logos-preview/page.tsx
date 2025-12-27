/**
 * Logo 预览页面 - 用于测试和查看所有品牌图标
 */
import { ProviderIcon } from '@/components/provider-icon'

const providers = [
  { id: 'openai', name: 'OpenAI', color: '#10A37F' },
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
  { id: 'local', name: '本地 Embedding', color: '#10B981' },
]

export default function LogosPreviewPage() {
  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-4xl font-bold text-gray-900 mb-2">
          品牌 Logo 预览
        </h1>
        <p className="text-gray-600 mb-8">
          查看所有模型提供商的官方图标
        </p>

        {/* Logo 网格 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
          {providers.map((provider) => (
            <div
              key={provider.id}
              className="bg-white rounded-xl border-2 border-gray-200 p-6 hover:shadow-lg transition-shadow"
            >
              <div className="flex flex-col items-center text-center">
                {/* Logo 大尺寸 */}
                <div className="w-24 h-24 flex items-center justify-center mb-4 rounded-lg bg-gray-50">
                  <ProviderIcon providerId={provider.id} className="w-16 h-16" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-1">
                  {provider.name}
                </h3>
                <p className="text-sm text-gray-500 mb-3">{provider.id}</p>
                <div className="flex items-center gap-2">
                  <div
                    className="w-6 h-6 rounded border border-gray-300"
                    style={{ backgroundColor: provider.color }}
                  />
                  <span className="text-xs font-mono text-gray-600">
                    {provider.color}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* 不同尺寸预览 */}
        <div className="bg-white rounded-xl border-2 border-gray-200 p-8">
          <h2 className="text-2xl font-bold text-gray-900 mb-6">
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
                <h3 className="text-sm font-medium text-gray-700 mb-3">
                  {sizeConfig.label}
                </h3>
                <div className="flex items-center gap-4 flex-wrap">
                  {providers.map((provider) => (
                    <div
                      key={provider.id}
                      className="flex flex-col items-center gap-2"
                    >
                      <div className="p-2 bg-gray-50 rounded-lg">
                        <ProviderIcon
                          providerId={provider.id}
                          className={sizeConfig.size}
                        />
                      </div>
                      <span className="text-xs text-gray-500">
                        {provider.name}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 背景对比 */}
        <div className="mt-6 bg-white rounded-xl border-2 border-gray-200 p-8">
          <h2 className="text-2xl font-bold text-gray-900 mb-6">
            背景对比
          </h2>
          <div className="grid grid-cols-3 gap-6">
            {/* 白色背景 */}
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-3">
                白色背景
              </h3>
              <div className="bg-white p-4 rounded-lg border border-gray-200">
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
              <h3 className="text-sm font-medium text-gray-700 mb-3">
                灰色背景
              </h3>
              <div className="bg-gray-100 p-4 rounded-lg">
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
              <h3 className="text-sm font-medium text-gray-700 mb-3">
                深色背景
              </h3>
              <div className="bg-gray-900 p-4 rounded-lg">
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
        </div>

        {/* 说明 */}
        <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h3 className="text-lg font-semibold text-blue-900 mb-2">
            📝 使用说明
          </h3>
          <ul className="text-sm text-blue-800 space-y-1">
            <li>• 所有 Logo 使用 SVG 格式,支持任意缩放</li>
            <li>• 图标路径: <code className="bg-blue-100 px-1 rounded">/public/logos/</code></li>
            <li>• 组件: <code className="bg-blue-100 px-1 rounded">&lt;ProviderIcon providerId=&quot;openai&quot; /&gt;</code></li>
            <li>• 建议尺寸: 24px (小)、32px (中)、48px (大)</li>
            <li>• 如需替换,访问 <code className="bg-blue-100 px-1 rounded">/public/logos/README.md</code> 查看指南</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
