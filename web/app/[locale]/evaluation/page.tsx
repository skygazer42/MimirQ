import { redirect } from '@/i18n/navigation'
import type { AppLocale } from '@/i18n/routing'

type LocaleEvaluationRedirectPageProps = {
  params: Promise<{ locale: AppLocale }>
}

export default async function LocaleEvaluationRedirectPage({ params }: Readonly<LocaleEvaluationRedirectPageProps>) {
  const { locale } = await params
  redirect({ href: '/evaluations', locale })
}
