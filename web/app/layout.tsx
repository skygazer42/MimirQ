import type { Metadata } from 'next'
import './globals.css'
import { ParserBackendProvider } from "@/contexts/parser-backend-context"
import { ChunkStrategyProvider } from "@/contexts/chunk-strategy-context"
import { PipelineOptionsProvider } from "@/contexts/pipeline-options-context"
import { PipelineCapabilitiesProvider } from "@/contexts/pipeline-capabilities-context"
import { ThemeProvider } from "@/components/theme-provider"
import { SonnerToaster } from "@/components/sonner-toaster"
import { CommandMenu } from "@/components/command-menu"
import { ThemeCustomizer } from "@/components/theme-customizer"

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
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="font-sans">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <SonnerToaster />
          <CommandMenu />
          <ThemeCustomizer />
          <PipelineCapabilitiesProvider>
            <ParserBackendProvider>
              <ChunkStrategyProvider>
                <PipelineOptionsProvider>{children}</PipelineOptionsProvider>
              </ChunkStrategyProvider>
            </ParserBackendProvider>
          </PipelineCapabilitiesProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
