'use client'

/**
 * 主页面 - 对话界面
 */
import { useState } from 'react'
import { Navbar } from '@/components/navbar'
import { ChatArea } from '@/components/chat-area'

export default function Home() {
  const [isSidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <Navbar isSidebarOpen={isSidebarOpen} setSidebarOpen={setSidebarOpen} />
      <div className={`flex-1 flex flex-col ${isSidebarOpen ? 'ml-64' : 'ml-0'}`}>
        <ChatArea />
      </div>
    </div>
  )
}
