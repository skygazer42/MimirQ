/**
 * 主页面
 */
import { Sidebar } from '@/components/sidebar'
import { ChatArea } from '@/components/chat-area'

export default function Home() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <ChatArea />
    </div>
  )
}
