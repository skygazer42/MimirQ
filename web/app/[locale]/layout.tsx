import { notFound } from 'next/navigation'
import { setRequestLocale } from 'next-intl/server'

import { routing, type AppLocale } from '@/i18n/routing'

type LocaleLayoutProps = {
  children: React.ReactNode
  params: Promise<{ locale: string }>
}

export default async function LocaleLayout({ children, params }: Readonly<LocaleLayoutProps>) {
  const { locale } = await params

  if (!routing.locales.includes(locale as AppLocale)) {
    notFound()
  }

  setRequestLocale(locale)
  return children
}
