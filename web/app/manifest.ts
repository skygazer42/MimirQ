import type { MetadataRoute } from 'next'
import { BRAND_ASSETS, BRAND_DESCRIPTION, BRAND_NAME } from '@/lib/brand'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: BRAND_NAME,
    short_name: BRAND_NAME,
    description: BRAND_DESCRIPTION,
    start_url: '/',
    display: 'standalone',
    background_color: '#f6f7f8',
    theme_color: '#20262e',
    icons: [
      {
        src: BRAND_ASSETS.icon192,
        sizes: '192x192',
        type: 'image/png',
      },
      {
        src: BRAND_ASSETS.icon512,
        sizes: '512x512',
        type: 'image/png',
      },
      {
        src: BRAND_ASSETS.maskableIcon,
        sizes: 'any',
        type: 'image/svg+xml',
        purpose: 'maskable',
      },
    ],
  }
}
