/**
 * 知识库管理页面
 */
import { Navbar } from '@/components/navbar'
import { Sidebar } from '@/components/sidebar'

export default function KnowledgePage() {
  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-8">
          <div className="max-w-6xl mx-auto">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">知识库管理</h1>
            <p className="text-gray-600 mb-8">管理和查看所有文档资源</p>

            <div className="bg-gray-50 border-2 border-dashed border-gray-300 rounded-lg p-12 text-center">
              <p className="text-gray-500">知识库详细视图开发中...</p>
              <p className="text-sm text-gray-400 mt-2">可以在左侧边栏上传和管理文档</p>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
