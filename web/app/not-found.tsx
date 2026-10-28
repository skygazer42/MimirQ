import Link from 'next/link'
import { Compass } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { FullScreenFrame } from '@/components/full-screen-frame'
import { PageStatus, pageStatusActionClass } from '@/components/ui/page-status'

export default function NotFound() {
  const t = useTranslations('RouteBoundaries')

  return (
    <FullScreenFrame showBackground={false} mainClassName="p-0">
      <PageStatus title={t('notFound.title')} description={t('notFound.description')} icon={<Compass />} showBrand className="min-h-dvh" actions={<><Button asChild className={pageStatusActionClass}><Link href="/">{t('notFound.goHome')}</Link></Button><Button variant="outline" asChild className={pageStatusActionClass}><Link href="/knowledge">{t('notFound.goKnowledge')}</Link></Button></>} />
    </FullScreenFrame>
  )
}
