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
        src: '/icon.svg',
        sizes: 'any',
        type: 'image/svg+xml',
      },
      {
        src: '/favicon-light.svg',
        sizes: 'any',
        type: 'image/svg+xml',
      },
    ],
  }
}
