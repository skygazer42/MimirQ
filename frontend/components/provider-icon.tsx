/**
 * 模型提供商图标组件
 * 使用 SVG 渲染官方品牌图标
 */

interface ProviderIconProps {
  providerId: string
  className?: string
}

export function ProviderIcon({ providerId, className = 'w-8 h-8' }: ProviderIconProps) {
  const icons: Record<string, JSX.Element> = {
    openai: (
      <svg className={className} viewBox="0 0 24 24" fill="none">
        <path
          d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z"
          fill="currentColor"
        />
      </svg>
    ),
    anthropic: (
      <svg className={className} viewBox="0 0 24 24" fill="none">
        <path
          d="M13.9074 0.667969L23.2074 23.332H18.9741L16.1741 16.332H7.84076L5.04076 23.332H0.807617L10.1076 0.667969H13.9074ZM14.8741 12.332L12.0074 5.33203L9.14076 12.332H14.8741Z"
          fill="currentColor"
        />
      </svg>
    ),
    deepseek: (
      <div className={className} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', fontSize: '1.2em' }}>
        <span style={{ color: '#2563eb' }}>D</span>
        <span style={{ color: '#1e40af' }}>S</span>
      </div>
    ),
    zhipu: (
      <div className={className} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', fontSize: '1.1em', background: 'linear-gradient(135deg, #a855f7 0%, #7c3aed 100%)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
        智谱
      </div>
    ),
    qwen: (
      <svg className={className} viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="10" fill="#0ea5e9" />
        <path
          d="M12 6L14.5 11.5H17.5L15 14L16 18L12 15.5L8 18L9 14L6.5 11.5H9.5L12 6Z"
          fill="white"
        />
      </svg>
    ),
    moonshot: (
      <svg className={className} viewBox="0 0 24 24" fill="none">
        <path
          d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"
          fill="currentColor"
        />
      </svg>
    ),
    ollama: (
      <svg className={className} viewBox="0 0 24 24" fill="none">
        <path
          d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z"
          fill="currentColor"
        />
      </svg>
    ),
    local: (
      <svg className={className} viewBox="0 0 24 24" fill="none">
        <path
          d="M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-2 8h-3v3h-2v-3h-3v-2h3V9h2v3h3v2z"
          fill="currentColor"
        />
      </svg>
    ),
  }

  return icons[providerId] || (
    <div className={className} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold' }}>
      {providerId.charAt(0).toUpperCase()}
    </div>
  )
}
