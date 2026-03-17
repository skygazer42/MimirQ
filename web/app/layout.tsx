import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
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
import { RouteScrollReset } from "@/components/route-scroll-reset"
import { AuthGuard } from "@/components/auth-guard"

const inter = Inter({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-sans',
  display: 'swap',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
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
  const enableFluidCursor = process.env.NEXT_PUBLIC_ENABLE_FLUID_CURSOR === "1"

  return (
    <html lang="zh-CN" suppressHydrationWarning className="h-full overflow-hidden">
      {/* Lock window scrolling: the app uses panel-internal scrolling for better UX. */}
      <body className={`${inter.variable} ${jetbrainsMono.variable} font-sans h-dvh overflow-hidden`}>
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <QueryProvider>
            <SonnerToaster />
            <CommandMenu />
            <RouteScrollReset />
            {enableFluidCursor ? <FluidCursor /> : null}
            <TaskCenter />
            <PipelineCapabilitiesProvider>
              <ParserBackendProvider>
                <ChunkStrategyProvider>
                  <PipelineOptionsProvider>
                    <AuthGuard>{children}</AuthGuard>
                  </PipelineOptionsProvider>
                </ChunkStrategyProvider>
              </ParserBackendProvider>
            </PipelineCapabilitiesProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
