import type { Metadata } from 'next'
import { Fira_Code, Fira_Sans } from 'next/font/google'
import './globals.css'
import { ParserBackendProvider } from "@/contexts/parser-backend-context"
import { ChunkStrategyProvider } from "@/contexts/chunk-strategy-context"
import { PipelineOptionsProvider } from "@/contexts/pipeline-options-context"
import { PipelineCapabilitiesProvider } from "@/contexts/pipeline-capabilities-context"
import { ThemeProvider } from "@/components/theme-provider"
import { SonnerToaster } from "@/components/sonner-toaster"
import { CommandMenu } from "@/components/command-menu"
import { FluidCursor } from "@/components/ui/fluid-cursor"
import { TaskCenter } from "@/components/task-center"
import { QueryProvider } from "@/components/providers/query-provider"

const fontSans = Fira_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-sans',
})

const fontMono = Fira_Code({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-mono',
})

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
      <body className={`${fontSans.variable} ${fontMono.variable} font-sans`}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <QueryProvider>
            <SonnerToaster />
            <CommandMenu />
            <FluidCursor />
            <TaskCenter />
            <PipelineCapabilitiesProvider>
              <ParserBackendProvider>
                <ChunkStrategyProvider>
                  <PipelineOptionsProvider>{children}</PipelineOptionsProvider>
                </ChunkStrategyProvider>
              </ParserBackendProvider>
            </PipelineCapabilitiesProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
