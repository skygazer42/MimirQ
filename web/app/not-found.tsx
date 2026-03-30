import Link from 'next/link'
import { Compass } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { FullScreenFrame } from '@/components/full-screen-frame'

export default function NotFound() {
  const t = useTranslations('RouteBoundaries')

  return (
    <FullScreenFrame>
      <Card className="w-full max-w-lg rounded-3xl shadow-strong">
        <CardContent className="p-8 text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Compass className="h-6 w-6" />
          </div>
          <h1 className="text-xl font-semibold text-foreground">{t("notFound.title")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {t("notFound.description")}
          </p>
          <div className="mt-6 flex items-center justify-center gap-3">
            <Button asChild>
              <Link href="/">{t("notFound.goHome")}</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link href="/knowledge">{t("notFound.goKnowledge")}</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </FullScreenFrame>
  )
}
