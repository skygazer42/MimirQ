import type { MetadataRoute } from 'next'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'MimirQ',
    short_name: 'MimirQ',
    description: 'AI RAG knowledge base assistant',
    start_url: '/',
    display: 'standalone',
    background_color: '#0b1020',
    theme_color: '#0f172a',
    icons: [
      {
        src: '/brand/mimirq-logo-image2-badge.png',
        sizes: '512x512',
        type: 'image/png',
      },
      {
        src: '/brand/mimirq-logo-image2-512.png',
        sizes: '512x512',
        type: 'image/png',
      },
    ],
  }
}
