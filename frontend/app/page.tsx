/**
 * 主页面 - 对话界面
 */
import { Navbar } from '@/components/navbar'
import { ChatArea } from '@/components/chat-area'

export default function Home() {
  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar />
      <ChatArea />
    </div>
  )
}
