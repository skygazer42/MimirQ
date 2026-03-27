import type { Metadata } from 'next'
import './globals.css'
import { ThemeProvider } from "@/components/theme-provider"
import { SonnerToaster } from "@/components/sonner-toaster"
import { CommandMenu } from "@/components/command-menu"
import { FluidCursor } from "@/components/ui/fluid-cursor"
import { TaskCenter } from "@/components/task-center"
import { QueryProvider } from "@/components/providers/query-provider"
import { ServiceWorkerRegistrar } from "@/components/providers/service-worker-registrar"
import { WebVitalsReporter } from "@/components/providers/web-vitals-reporter"
import { RouteScrollReset } from "@/components/route-scroll-reset"
import { AuthGuard } from "@/components/auth-guard"
import { getDocumentDirection } from '@/lib/document-direction'

export const metadata: Metadata = {
  title: "MimirQ - AI 知识库助手",
  description: "基于 RAG 的智能知识库问答系统",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/favicon-light.svg", media: "(prefers-color-scheme: light)" },
      { url: "/favicon-dark.svg", media: "(prefers-color-scheme: dark)" },
    ],
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const enableFluidCursor = process.env.NEXT_PUBLIC_ENABLE_FLUID_CURSOR === "1"
  const documentLang = process.env.NEXT_PUBLIC_APP_LANG?.trim() || 'zh-CN'
  const documentDir = getDocumentDirection(documentLang)

  return (
    <html lang={documentLang} dir={documentDir} suppressHydrationWarning className="h-full overflow-hidden">
      {/* Lock window scrolling: the app uses panel-internal scrolling for better UX. */}
      <body className="font-sans h-dvh overflow-hidden">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <QueryProvider>
            <ServiceWorkerRegistrar />
            <WebVitalsReporter />
            <SonnerToaster />
            <CommandMenu />
            <RouteScrollReset />
            {enableFluidCursor ? <FluidCursor /> : null}
            <TaskCenter />
            <AuthGuard>{children}</AuthGuard>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
