import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import { ParserBackendProvider } from "@/contexts/parser-backend-context"
import { ChunkStrategyProvider } from "@/contexts/chunk-strategy-context"
import { ThemeProvider } from "@/components/theme-provider"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
  title: "MimirQ - AI 知识库助手",
  description: "基于 RAG 的智能知识库问答系统",
  icons: {
    icon: "/favicon.svg",
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh-CN">
      <body className={inter.className}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <ParserBackendProvider>
            <ChunkStrategyProvider>{children}</ChunkStrategyProvider>
          </ParserBackendProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
