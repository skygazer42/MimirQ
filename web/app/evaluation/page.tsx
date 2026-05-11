import { redirect } from '@/i18n/navigation'
import { routing } from '@/i18n/routing'

export default function EvaluationRedirectPage() {
  redirect({ href: '/evaluations', locale: routing.defaultLocale })
}
