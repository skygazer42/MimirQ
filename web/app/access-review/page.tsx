import { getLocale } from 'next-intl/server'

import { redirect } from '@/i18n/navigation'

export default async function AccessReviewPage() {
  redirect({ href: '/audit', locale: await getLocale() })
}
