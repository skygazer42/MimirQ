'use client'

import { useState, type ReactNode } from 'react'
import Image from 'next/image'
import { User, Mail, Lock, ArrowRight, Loader2, Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useRouter } from '@/i18n/navigation'
import { authApi } from '@/lib/api'
import { setAuthSession } from '@/lib/auth-storage'
import { startOidcLogin } from '@/lib/oidc'
import { getOidcPublicProvidersFromEnv } from '@/lib/oidc-providers'
import { formatRequestId, toApiErrorInfo, type ApiErrorInfo } from '@/lib/api-errors'
import { FullScreenFrame } from '@/components/full-screen-frame'
import { cn, detachPromise } from '@/lib/utils'

type Mode = 'login' | 'register'

function getAuthSsoProviderLabel(provider?: { id?: string; name?: string }): string {
    if (provider?.name) return `Continue with ${provider.name}`
    if (provider?.id) return `Continue with ${provider.id}`
    return 'Continue with SSO'
}

function getAuthSubmitContent(isSubmitting: boolean, mode: Mode): ReactNode {
    if (isSubmitting) {
        return (
            <>
                <Loader2 className="mr-2 size-4 animate-spin motion-reduce:animate-none" />
                处理中...
            </>
        )
    }

    return (
        <>
            {mode === 'login' ? '登 录' : '创建初始管理员'}
            <ArrowRight className="ml-2 size-4 opacity-70" />
        </>
    )
}

function toAuthPageError(err: unknown, mode: Mode): ApiErrorInfo {
    const info = toApiErrorInfo(err, '请求失败，请重试')
    if (mode !== 'register') return info

    if (info.status === 403) {
        return {
            ...info,
            message: '首次 owner 注册需要 bootstrap token。请填写部署时配置的 bootstrap token 后重试。',
        }
    }

    if (info.status === 409) {
        return {
            ...info,
            message: '首次初始化已关闭，后续注册不能再自助创建 owner，请联系管理员开通账号。',
        }
    }

    return info
}

export default function AuthPage() {
    const router = useRouter()
    const oidcProviders = getOidcPublicProvidersFromEnv()
    const oidcEnabled = oidcProviders.length > 0
    const [mode, setMode] = useState<Mode>('login')
    const [email, setEmail] = useState('')
    const [username, setUsername] = useState('')
    const [identifier, setIdentifier] = useState('')
    const [password, setPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [bootstrapToken, setBootstrapToken] = useState('')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [ssoProviderWorkingId, setSsoProviderWorkingId] = useState<string | null>(null)
    const [error, setError] = useState<ApiErrorInfo | null>(null)

    const isSsoSubmitting = ssoProviderWorkingId !== null

    const handleSso = async (providerId: string) => {
        setError(null)
        setSsoProviderWorkingId(providerId)
        try {
            await startOidcLogin({ providerId, returnTo: '/' })
        } catch (err: unknown) {
            setError(toApiErrorInfo(err, 'SSO login failed'))
            setSsoProviderWorkingId(null)
        }
    }

    const handleSubmit = async (event: React.SyntheticEvent<HTMLFormElement>) => {
        event.preventDefault()
        setError(null)

        if (mode === 'register' && password !== confirmPassword) {
            setError({ message: '两次输入的密码不一致' })
            return
        }

        setIsSubmitting(true)
        try {
            const response =
                mode === 'login'
                    ? await authApi.login({ identifier: identifier.trim(), password })
                    : await authApi.register({
                          email: email.trim(),
                          username: username.trim(),
                          password,
                          bootstrapToken: bootstrapToken.trim() || undefined,
                      })
            setAuthSession({ token: response.token, user: response.user })
            router.push('/')
        } catch (err: unknown) {
            setError(toAuthPageError(err, mode))
        } finally {
            setIsSubmitting(false)
        }
    }

    let ssoSectionContent: ReactNode = null
    if (oidcProviders.length > 1) {
        ssoSectionContent = (
            <div className="space-y-2">
                <div className="text-xs text-muted-foreground">选择 SSO 提供方</div>
                {oidcProviders.map((provider) => {
                    const label = getAuthSsoProviderLabel(provider)
                    const working = ssoProviderWorkingId === provider.id
                    return (
                        <Button
                            key={provider.id}
                            type="button"
                            variant="secondary"
                            className="w-full h-11 rounded-xl justify-between"
                            disabled={isSubmitting || isSsoSubmitting}
                            onClick={() => detachPromise(handleSso(provider.id))}
                        >
                            <span className="inline-flex items-center">
                                {working ? (
                                    <Loader2 className="mr-2 size-4 animate-spin motion-reduce:animate-none" />
                                ) : null}
                                {working ? 'Signing in…' : label}
                            </span>
                            <ArrowRight className="ml-2 size-4 opacity-70" aria-hidden="true" />
                        </Button>
                    )
                })}
            </div>
        )
    } else if (oidcProviders.length === 1) {
        const provider = oidcProviders[0]
        ssoSectionContent = (
            <Button
                type="button"
                variant="secondary"
                className="w-full h-11 rounded-xl"
                disabled={isSubmitting || isSsoSubmitting}
                onClick={() => detachPromise(handleSso(provider?.id || 'default'))}
            >
                {isSsoSubmitting ? (
                    <>
                        <Loader2 className="mr-2 size-4 animate-spin motion-reduce:animate-none" />
                        Signing in...
                    </>
                ) : (
                    <>
                        {getAuthSsoProviderLabel(provider)}
                        <ArrowRight className="ml-2 size-4 opacity-70" aria-hidden="true" />
                    </>
                )}
            </Button>
        )
    }

    return (
        <FullScreenFrame
            className="relative w-full overflow-hidden"
        >
            <div className="relative z-10 w-full max-w-md p-6">
                {/* Logo / Brand */}
                <div className="flex flex-col items-center mb-8 space-y-4">
                    <div className="flex size-20 items-center justify-center rounded-2xl border border-[#CAF0F8]/70 bg-card/85 shadow-[0_18px_48px_rgba(8,47,73,0.10)] backdrop-blur">
                      <Image
                        src="/brand/mimirq-mark-badge.png"
                        alt="MimirQ"
                        width={64}
                        height={64}
                        priority
                        unoptimized
                        className="size-14 select-none object-contain"
                      />
                    </div>
                    <div className="text-center">
                        <h1 className="text-balance text-3xl font-semibold text-foreground">
                            MimirQ
                        </h1>
                        <p className="mt-2 text-pretty text-sm text-muted-foreground font-medium">
                            下一代智能知识库平台
                        </p>
                    </div>
                </div>

	                <div className="rounded-3xl border border-border bg-card p-8 shadow-strong">
	                    {oidcEnabled && (
	                        <div className="mb-7 space-y-3">
                              {ssoSectionContent}
	                            <div className="flex items-center gap-3 text-xs text-muted-foreground">
	                                <div className="h-px flex-1 bg-border/60" />
	                                <span>or</span>
	                                <div className="h-px flex-1 bg-border/60" />
                            </div>
                        </div>
                    )}
                    {/* Tab Switcher */}
                    <div className="flex p-1 bg-background/40 rounded-xl mb-8 border border-border/50">
                        <button
                            type="button"
                            className={cn(
                                "focus-ring flex-1 py-2 text-sm font-medium rounded-lg transition-colors duration-200 motion-reduce:transition-none",
                                mode === 'login'
                                    ? "bg-card/60 text-foreground shadow-sm"
                                    : "text-muted-foreground hover:text-foreground hover:bg-[#CAF0F8]/55"
                            )}
                            onClick={() => setMode('login')}
                        >
                            登录
                        </button>
                        <button
                            type="button"
                            className={cn(
                                "focus-ring flex-1 py-2 text-sm font-medium rounded-lg transition-colors duration-200 motion-reduce:transition-none",
                                mode === 'register'
                                    ? "bg-card/60 text-foreground shadow-sm"
                                    : "text-muted-foreground hover:text-foreground hover:bg-[#CAF0F8]/55"
                            )}
                            onClick={() => setMode('register')}
                        >
                            首次设置
                        </button>
                    </div>

                    <form onSubmit={handleSubmit} className="space-y-5">
                        {mode === 'register' && (
                            <div className="space-y-4">
                                <p className="text-xs leading-5 text-muted-foreground">
                                    仅用于未初始化的部署。生产环境首次 owner 注册可填写 bootstrap token；已有管理员时，请联系管理员开通账号。
                                </p>
                                <div className="space-y-2">
                                    <Label htmlFor="email" className="text-xs text-muted-foreground">邮箱地址</Label>
                                    <div className="relative group">
                                        <Mail className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
                                        <Input
                                            id="email"
                                            type="email"
                                            placeholder="name@example.com"
                                            className="pl-10 bg-background/50"
                                            value={email}
                                            onChange={(e) => setEmail(e.target.value)}
                                            required
                                        />
                                    </div>
                                </div>
                                <div className="space-y-2">
                                    <Label htmlFor="username" className="text-xs text-muted-foreground">用户名</Label>
                                    <div className="relative group">
                                        <User className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
                                        <Input
                                            id="username"
                                            placeholder="设置用户名"
                                            className="pl-10 bg-background/50"
                                            value={username}
                                            onChange={(e) => setUsername(e.target.value)}
                                            required
                                        />
                                    </div>
                                </div>
                                <div className="space-y-2">
                                    <Label htmlFor="bootstrapToken" className="text-xs text-muted-foreground">
                                        Bootstrap Token（可选）
                                    </Label>
                                    <Input
                                        id="bootstrapToken"
                                        type="password"
                                        placeholder="仅首次生产注册需要"
                                        className="bg-background/50"
                                        value={bootstrapToken}
                                        onChange={(e) => setBootstrapToken(e.target.value)}
                                        autoComplete="off"
                                    />
                                </div>
                            </div>
                        )}

                        {mode === 'login' && (
                            <div className="space-y-2 motion-safe:animate-fade-in">
                                <Label htmlFor="identifier" className="text-xs text-muted-foreground">账号</Label>
                                <div className="relative group">
                                    <User className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
                                    <Input
                                        id="identifier"
                                        placeholder="输入邮箱或用户名"
                                        className="pl-10 bg-background/50"
                                        value={identifier}
                                        onChange={(e) => setIdentifier(e.target.value)}
                                        required
                                    />
                                </div>
                            </div>
                        )}

                        <div className="space-y-2">
                            <Label htmlFor="password" className="text-xs text-muted-foreground">
                                {mode === 'login' ? '密码' : '设置密码'}
                            </Label>
                            <div className="relative group">
                                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
                                <Input
                                    id="password"
                                    type="password"
                                    placeholder="••••••••"
                                    className="pl-10 bg-background/50"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                />
                            </div>
                        </div>

                        {mode === 'register' && (
                            <div className="space-y-2 motion-safe:animate-fade-in">
                                <Label htmlFor="confirmPassword" className="text-xs text-muted-foreground">确认密码</Label>
                                <div className="relative group">
                                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
                                    <Input
                                        id="confirmPassword"
                                        type="password"
                                        placeholder="••••••••"
                                        className="pl-10 bg-background/50"
                                        value={confirmPassword}
                                        onChange={(e) => setConfirmPassword(e.target.value)}
                                        required
                                    />
                                </div>
                            </div>
                        )}

                        {error && (
                            <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 flex items-start gap-2 motion-safe:animate-fade-in">
                                <div className="w-1 h-1 mt-2 rounded-full bg-destructive shrink-0" />
                                <div className="min-w-0 flex-1">
                                  <p className="text-xs text-destructive">{error.message}</p>
                                  {error.requestId ? (
                                    <div className="mt-2 flex items-center justify-between gap-2">
                                      <span className="min-w-0 truncate text-[11px] font-mono text-muted-foreground">
                                        {formatRequestId(error.requestId)}
                                      </span>
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="h-7 px-2 text-muted-foreground hover:text-foreground"
                                        aria-label="复制 request_id"
                                        onClick={() => navigator.clipboard?.writeText?.(error.requestId || '')}
                                      >
                                        <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                                      </Button>
                                    </div>
                                  ) : null}
                                </div>
                            </div>
                        )}

                        <Button
                            type="submit"
                            className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl transition-colors duration-200 motion-reduce:transition-none"
                            disabled={isSubmitting}
                        >
	                            {getAuthSubmitContent(isSubmitting, mode)}
                        </Button>
                    </form>
                </div>

                <div className="mt-8 text-center">
                    <p className="text-xs text-muted-foreground">
                        遇到问题？{" "}
                        <span className="font-medium text-foreground/80">
                            联系管理员
                        </span>
                    </p>
                </div>
            </div>
        </FullScreenFrame>
    )
}
