import { useTranslations } from 'next-intl'
import { PageSkeleton } from '@/components/ui/page-skeleton'

export default function Loading() {
  const t = useTranslations('RouteBoundaries')
  return <PageSkeleton layout="neutral" label={t('loading.pageSr')} />
}
