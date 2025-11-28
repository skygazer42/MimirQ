/**
 * 文档解析页面
 */
import { Navbar } from '@/components/navbar'

export default function ParsingPage() {
  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar />
      <main className="flex-1 overflow-y-auto p-8">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">文档解析</h1>
          <p className="text-gray-600 mb-8">配置文档解析策略和参数</p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* 解析设置卡片 */}
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">分块策略</h3>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    块大小 (Chunk Size)
                  </label>
                  <input
                    type="number"
                    defaultValue={1000}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">每个文本块的字符数</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    重叠大小 (Chunk Overlap)
                  </label>
                  <input
                    type="number"
                    defaultValue={200}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">相邻块之间的重叠字符数</p>
                </div>
              </div>
            </div>

            {/* 检索设置卡片 */}
            <div className="bg-white border border-gray-200 rounded-lg p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">检索参数</h3>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Top K
                  </label>
                  <input
                    type="number"
                    defaultValue={5}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">返回的最相关文档数量</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    相似度阈值
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="1"
                    defaultValue={0.7}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">文档相关性过滤阈值 (0-1)</p>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-6 flex justify-end">
            <button className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
              保存设置
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
