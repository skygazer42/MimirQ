'use client'

import { RouteError } from '@/components/route-error'

export default function ErrorPage(props: Readonly<{ error: Error & { digest?: string }; reset: () => void }>) {
  return <RouteError {...props} />
}
