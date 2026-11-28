import { getLocale } from 'next-intl/server'

import { redirect } from '@/i18n/navigation'

export default async function GroupDetailPage({ params }: Readonly<{ params: Promise<{ id: string }> }>) {
  const { id } = await params
  redirect({ href: `/settings/groups?group=${encodeURIComponent(id)}`, locale: await getLocale() })
}
