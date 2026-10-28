'use client'

import { Loader2, ShieldAlert, ShieldCheck } from '@/components/icons'
import { BrandLogo } from '@/components/brand-logo'
import { FullScreenFrame } from '@/components/full-screen-frame'
import { Button } from '@/components/ui/button'

export function AuthCallbackState({ status, error, detail, onBack }: { status: 'working' | 'success' | 'error'; error: string | null; detail?: string | null; onBack: () => void }) {
  const failed = status === 'error'
  const Icon = failed ? ShieldAlert : status === 'success' ? ShieldCheck : Loader2
  return <FullScreenFrame showBackground={false} mainClassName="px-6 py-12">
    <section className="w-full max-w-[420px]" aria-labelledby="auth-callback-title">
      <BrandLogo className="mb-10 w-32" priority />
      <div role={failed ? 'alert' : 'status'} aria-live={failed ? 'assertive' : 'polite'} className="border-t border-border pt-7">
        <Icon aria-hidden="true" className={`mb-5 size-7 ${failed ? 'text-destructive' : 'text-foreground'} ${status === 'working' ? 'animate-spin motion-reduce:animate-none' : ''}`} />
        <h1 id="auth-callback-title" className="text-[22px] font-semibold leading-8">{failed ? '单点登录未完成' : status === 'success' ? '登录成功' : '正在验证登录信息'}</h1>
        <p className="mt-3 break-words text-sm leading-6 text-muted-foreground">{failed ? error || '请返回登录页，重新发起单点登录。' : status === 'success' ? '正在进入工作区…' : '验证完成后将自动进入工作区。'}</p>
        {failed && detail && detail !== error ? <details className="mt-4 text-[13px] leading-6 text-muted-foreground"><summary className="cursor-pointer">错误详情</summary><p className="mt-2 break-words">{detail}</p></details> : null}
      </div>
      {failed ? <Button className="mt-7" onClick={onBack}>返回登录</Button> : null}
    </section>
  </FullScreenFrame>
}
