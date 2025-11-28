/**
 * 问答历史页面
 */
import { Navbar } from '@/components/navbar'

export default function HistoryPage() {
  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar />
      <main className="flex-1 overflow-y-auto p-8">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">问答历史</h1>
          <p className="text-gray-600 mb-8">查看所有历史对话记录</p>

          <div className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-200">
            {/* 示例历史记录 */}
            {[1, 2, 3].map((i) => (
              <div key={i} className="p-6 hover:bg-gray-50 transition-colors cursor-pointer">
                <div className="flex items-start justify-between mb-2">
                  <h3 className="text-lg font-medium text-gray-900">
                    对话标题示例 {i}
                  </h3>
                  <span className="text-sm text-gray-500">
                    2024-11-28
                  </span>
                </div>
                <p className="text-gray-600 text-sm line-clamp-2">
                  这是一段对话摘要，展示了这次对话的主要内容...
                </p>
                <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
                  <span>10 条消息</span>
                  <span>•</span>
                  <span>5 个引用</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </main>
    </div>
  )
}
