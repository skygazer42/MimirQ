import { redirect } from '@/i18n/navigation'

export default async function LocaleEvaluationRedirectPage({
  params,
}: Readonly<{
  params: Promise<{ locale: string }>
}>) {
  const { locale } = await params

  redirect({ href: '/evaluations', locale })
}
