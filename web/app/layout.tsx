import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import { headers } from 'next/headers'
import { connection } from 'next/server'
import { NextIntlClientProvider } from 'next-intl'
import { getLocale, getMessages } from 'next-intl/server'
import './globals.css'

const inter = Inter({
  subsets: ['latin', 'latin-ext'],
  display: 'swap',
  variable: '--font-sans',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin', 'latin-ext'],
  display: 'swap',
  variable: '--font-mono',
})
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
import { resolveRequestDocumentSettings } from '@/lib/document-language'

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

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  await connection()

  const enableFluidCursor = process.env.NEXT_PUBLIC_ENABLE_FLUID_CURSOR === "1"
  const locale = await getLocale()
  const messages = await getMessages()
  const requestHeaders = await headers()
  const cspNonce = requestHeaders.get('x-nonce') || undefined
  const { lang: documentLang, dir: documentDir } = resolveRequestDocumentSettings(
    requestHeaders,
    locale || process.env.NEXT_PUBLIC_APP_LANG?.trim() || undefined
  )

  return (
    <html lang={documentLang} dir={documentDir} suppressHydrationWarning className="h-full overflow-hidden">
      {/* Lock window scrolling: the app uses panel-internal scrolling for better UX. */}
      <body className={`${inter.variable} ${jetbrainsMono.variable} font-sans h-dvh overflow-hidden`}>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <ThemeProvider
            attribute="class"
            defaultTheme="system"
            enableSystem
            disableTransitionOnChange
            nonce={cspNonce}
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
        </NextIntlClientProvider>
      </body>
    </html>
  )
}
