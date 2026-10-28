'use client'
import { FeedbackToast } from '@/components/feedback-toast'
import { toast } from 'sonner'

import { useEffect, useState, type ReactNode } from 'react'
import Image from 'next/image'
import { User, Mail, LockKeyhole, ArrowRight, Loader2, Copy, Eye, EyeOff, AlertCircle } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useRouter } from '@/i18n/navigation'
import { authApi } from '@/lib/api/auth'
import { setAuthSession } from '@/lib/auth-storage'
import { startOidcLogin } from '@/lib/oidc'
import { getOidcPublicProvidersFromEnv } from '@/lib/oidc-providers'
import { toApiErrorInfo, type ApiErrorInfo } from '@/lib/api-errors'
import { FullScreenFrame } from '@/components/full-screen-frame'
import { cn, detachPromise } from '@/lib/utils'
import type { AuthPolicy } from '@/types/backend'
import { AuthBrandPanel } from './auth-brand-panel'
import styles from './auth.module.css'

type Mode = 'login' | 'register'

const DEFAULT_ADMIN_CONTACT_URL = 'https://github.com/skygazer42/MimirQ/issues'
const SAFE_ADMIN_CONTACT_PROTOCOLS = new Set(['http:', 'https:', 'mailto:', 'tel:'])

function getAdminContactHref(): string {
    const configuredUrl = (process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL || '').trim()
    if (!configuredUrl) return DEFAULT_ADMIN_CONTACT_URL

    try {
        const parsedUrl = new URL(configuredUrl)
        return SAFE_ADMIN_CONTACT_PROTOCOLS.has(parsedUrl.protocol)
            ? configuredUrl
            : DEFAULT_ADMIN_CONTACT_URL
    } catch {
        return DEFAULT_ADMIN_CONTACT_URL
    }
}

function getAuthSsoProviderLabel(provider?: { id?: string; name?: string }): string {
    if (provider?.name) return `使用 ${provider.name} 登录`
    if (provider?.id) return `使用 ${provider.id} 登录`
    return '使用 SSO 登录'
}

function AuthPasswordInput({ id, label, value, onChange, autoComplete, minLength }: {
    id: string
    label: string
    value: string
    onChange: (value: string) => void
    autoComplete: 'current-password' | 'new-password'
    minLength?: number
}) {
    const [visible, setVisible] = useState(false)

    return (
        <div className="space-y-2">
            <Label htmlFor={id} className="text-sm font-medium text-foreground">{label}</Label>
            <div className="relative">
                <LockKeyhole className={styles.inputIcon} aria-hidden="true" />
                <Input
                    id={id}
                    name={id}
                    type={visible ? 'text' : 'password'}
                    placeholder={id === 'confirmPassword' ? '再次输入密码' : '请输入密码'}
                    className={cn(styles.input, 'pr-12')}
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    autoComplete={autoComplete}
                    minLength={minLength}
                    maxLength={72}
                    required
                />
                <button
                    type="button"
                    className={cn('focus-ring', styles.revealButton)}
                    aria-label={`${visible ? '隐藏' : '显示'}${id === 'confirmPassword' ? '确认密码' : '密码'}`}
                    aria-controls={id}
                    aria-pressed={visible}
                    onClick={() => setVisible((current) => !current)}
                >
                    {visible ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
                </button>
            </div>
        </div>
    )
}

function getAuthSubmitContent(isSubmitting: boolean, mode: Mode): ReactNode {
    if (isSubmitting) {
        return (
            <>
                <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                {mode === 'login' ? '登录中…' : '注册中…'}
            </>
        )
    }

    return (
        <>
            {mode === 'login' ? '登录' : '注册'}
        </>
    )
}

function AuthNotice({ info, isSubmitError, onRetry }: {
    info: ApiErrorInfo
    isSubmitError: boolean
    onRetry?: () => void
}) {

    const copyRequestId = async () => {
        try {
            if (!navigator.clipboard || !info.requestId) throw new Error('Clipboard unavailable')
            await navigator.clipboard.writeText(info.requestId)
            toast.success('已复制请求编号。')
        } catch {
            toast.error('无法复制，请手动选择请求编号。')
        }
    }

    if (isSubmitError) return <><FeedbackToast type="error" message={info.message} id="auth-submit-feedback" /><span id="auth-error" className="sr-only">{info.message}</span>{info.requestId && <details className={styles.errorDetails}><summary className="focus-ring">错误详情</summary><div className={styles.errorReference}><span>请求编号</span><code>{info.requestId}</code><Button type="button" variant="ghost" size="sm" onClick={() => detachPromise(copyRequestId())}><Copy className="size-3.5" aria-hidden="true" />复制编号</Button></div></details>}</>

    return (
        <div
            id="auth-service-notice"
            role={isSubmitError ? 'alert' : 'status'}
            className={styles.notice}
            data-tone={isSubmitError ? 'error' : 'service'}
        >
            <AlertCircle className={styles.noticeIcon} aria-hidden="true" />
            <div className={styles.noticeBody}>
                <p className={styles.noticeMessage}>{info.message}</p>
                <div className={styles.noticeActions}>
                    {onRetry && (
                        <button type="button" className={cn('focus-ring', styles.noticeRetry)} onClick={onRetry}>
                            重试
                        </button>
                    )}
                    {info.requestId && (
                        <details className={styles.errorDetails}>
                            <summary className="focus-ring">错误详情</summary>
                            <div className={styles.errorReference}>
                                <span>请求编号</span>
                                <code>{info.requestId}</code>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="h-11 justify-start px-0 text-muted-foreground sm:h-11"
                                    onClick={() => detachPromise(copyRequestId())}
                                >
                                    <Copy className="size-3.5" aria-hidden="true" />
                                    复制编号
                                </Button>
                            </div>
                        </details>
                    )}
                </div>
            </div>
        </div>
    )
}

function toAuthPageError(err: unknown, mode?: Mode): ApiErrorInfo {
    const info = toApiErrorInfo(err, '请求失败，请重试')
    if (
        (info.status !== undefined && info.status >= 500 && info.status < 600)
        || /internal server error|service unavailable|bad gateway|gateway timeout|backend returned html|无法连接后端|请求超时/i.test(info.message)
    ) {
        return { ...info, message: '服务暂时不可用，请稍后重试。' }
    }
    if (mode === 'login' && info.status === 401) {
        return { ...info, message: '账号或密码不正确，请重试。' }
    }
    if (mode !== 'register') return info

    if (info.status === 403) {
        return {
            ...info,
            message: '当前暂未开放注册，请联系管理员。',
        }
    }

    if (info.status === 409) {
        return {
            ...info,
            message: '暂时无法注册，请重试或联系管理员。',
        }
    }

    return info
}

export default function AuthPage() {
    const router = useRouter()
    const oidcProviders = getOidcPublicProvidersFromEnv()
    const oidcEnabled = oidcProviders.length > 0
    const [selectedMode, setMode] = useState<Mode>(() =>
        typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('mode') === 'register'
            ? 'register'
            : 'login'
    )
    const [policy, setPolicy] = useState<AuthPolicy | null>(null)
    const [policyError, setPolicyError] = useState<ApiErrorInfo | null>(null)
    const [policyAttempt, setPolicyAttempt] = useState(0)
    const [email, setEmail] = useState('')
    const [username, setUsername] = useState('')
    const [identifier, setIdentifier] = useState('')
    const [password, setPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [ssoProviderWorkingId, setSsoProviderWorkingId] = useState<string | null>(null)
    const [error, setError] = useState<ApiErrorInfo | null>(null)
    const [registrationSucceeded, setRegistrationSucceeded] = useState(false)
    const contactAdminHref = getAdminContactHref()

    const isSsoSubmitting = ssoProviderWorkingId !== null
    const canRegister = Boolean(policy?.registration_enabled)
    const mode = canRegister ? selectedMode : 'login'

    useEffect(() => {
        let active = true
        authApi.policy().then(
            (value) => { if (active) setPolicy(value) },
            (err: unknown) => { if (active) setPolicyError(toAuthPageError(err)) },
        )
        return () => { active = false }
    }, [policyAttempt])

    const refreshPolicy = () => {
        setPolicyError(null)
        setPolicyAttempt((attempt) => attempt + 1)
    }

    const notice = error ?? (isSubmitting ? null : policyError ?? (
        policy && !policy.initialized ? { message: '账号服务尚未准备好，请稍后重试。' } : null
    ))

    const handleModeChange = (nextMode: Mode) => {
        if (nextMode === mode || (nextMode === 'register' && !canRegister)) return
        setMode(nextMode)
        setError(null)
        setRegistrationSucceeded(false)
        setPassword('')
        setConfirmPassword('')
    }

    const handleSso = async (providerId: string) => {
        setError(null)
        setRegistrationSucceeded(false)
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
        setRegistrationSucceeded(false)

        if (mode === 'register' && password !== confirmPassword) {
            setError({ message: '两次输入的密码不一致' })
            return
        }

        setIsSubmitting(true)
        try {
            if (mode === 'register') {
                const registeredEmail = email.trim()
                await authApi.signup({ email: registeredEmail, username: username.trim(), password })
                setIdentifier(registeredEmail)
                setEmail('')
                setUsername('')
                setPassword('')
                setConfirmPassword('')
                setMode('login')
                setRegistrationSucceeded(true)
                router.replace('/auth')
                return
            }

            const response = await authApi.login({ identifier: identifier.trim(), password })
            setAuthSession({ token: response.token, user: response.user })
            router.push('/')
        } catch (err: unknown) {
            const info = toAuthPageError(err, mode)
            setError(info)
            if (mode === 'register' && (info.status === 409 || info.status === 403)) {
                refreshPolicy()
            }
        } finally {
            setIsSubmitting(false)
        }
    }

    let ssoSectionContent: ReactNode = null
    if (oidcProviders.length > 1) {
        ssoSectionContent = (
            <div className="space-y-2">
                <div className="text-sm text-muted-foreground">选择 SSO 提供方</div>
                {oidcProviders.map((provider) => {
                    const label = getAuthSsoProviderLabel(provider)
                    const working = ssoProviderWorkingId === provider.id
                    return (
                        <Button
                            key={provider.id}
                            type="button"
                            variant="outline"
                            className={cn(styles.submit, 'justify-between hover:bg-muted hover:text-foreground')}
                            disabled={isSubmitting || isSsoSubmitting}
                            onClick={() => detachPromise(handleSso(provider.id))}
                        >
                            <span className="inline-flex items-center">
                                {working ? (
                                    <Loader2 className="mr-2 size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                                ) : null}
                                {working ? '正在登录...' : label}
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
                variant="outline"
                className={cn(styles.submit, 'hover:bg-muted hover:text-foreground')}
                disabled={isSubmitting || isSsoSubmitting}
                onClick={() => detachPromise(handleSso(provider?.id || 'default'))}
            >
                {isSsoSubmitting ? (
                    <>
                        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                        正在登录...
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
            className={cn('w-full', styles.frame)}
            mainClassName="items-start p-0"
            showBackground={false}
        >
            <div className={styles.shell} data-auth-layout="centered">
                <AuthBrandPanel />
                <section className={styles.formPanel} data-auth-panel="ruled" aria-labelledby="auth-title">
                    <Image
                        src="/brand/explorations/ragvia/logo.svg"
                        alt="Ragvia"
                        width={144}
                        height={44}
                        priority
                        unoptimized
                        className={styles.brand}
                    />
                    <div className={styles.formContent}>
                        <header className={styles.heading}>
                            <h1 id="auth-title" className={styles.title}>
                                {mode === 'login' ? '欢迎回来' : '创建账号'}
                            </h1>
                            <p className={styles.subtitle}>
                                {mode === 'login' ? '登录 Ragvia' : '使用邮箱注册'}
                            </p>
                        </header>
                        <FeedbackToast type="success" message={registrationSucceeded ? '注册成功，请登录。' : null} id="registration-feedback" />

                        {!policy && !policyError && (
                            <p role="status" className="sr-only">正在检查账号服务…</p>
                        )}

                        {oidcEnabled && (
                            <div className="mt-7 space-y-5">
                                {ssoSectionContent}
                                <div className="flex items-center gap-3 text-sm text-muted-foreground">
                                    <div className="h-px flex-1 bg-border" />
                                    <span>或使用账号登录</span>
                                    <div className="h-px flex-1 bg-border" />
                                </div>
                            </div>
                        )}

                        <form id="auth-form" onSubmit={handleSubmit} className={styles.form} aria-busy={isSubmitting} aria-describedby={notice ? error ? 'auth-error' : 'auth-service-notice' : undefined}>
                            <fieldset className={styles.fields} disabled={isSubmitting || isSsoSubmitting}>
                                {mode === 'register' && (
                                    <div className="space-y-5">
                                        <div className="space-y-2">
                                            <Label htmlFor="email" className="text-sm font-medium text-foreground">邮箱地址</Label>
                                            <div className="relative group">
                                                <Mail className={styles.inputIcon} aria-hidden="true" />
                                                <Input
                                                    id="email"
                                                    name="email"
                                                    type="email"
                                                    autoComplete="email"
                                                    placeholder="请输入邮箱"
                                                    className={cn(styles.input, 'pl-10')}
                                                    value={email}
                                                    onChange={(e) => setEmail(e.target.value)}
                                                    required
                                                />
                                            </div>
                                        </div>
                                        <div className="space-y-2">
                                            <Label htmlFor="username" className="text-sm font-medium text-foreground">用户名</Label>
                                            <div className="relative group">
                                                <User className={styles.inputIcon} aria-hidden="true" />
                                                <Input
                                                    id="username"
                                                    name="username"
                                                    autoComplete="username"
                                                    minLength={3}
                                                    maxLength={64}
                                                    placeholder="设置用户名"
                                                    className={cn(styles.input, 'pl-10')}
                                                    value={username}
                                                    onChange={(e) => setUsername(e.target.value)}
                                                    required
                                                />
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {mode === 'login' && (
                                    <div className="space-y-2">
                                        <Label htmlFor="identifier" className="text-sm font-medium text-foreground">账号</Label>
                                        <div className="relative group">
                                            <User className={styles.inputIcon} aria-hidden="true" />
                                            <Input
                                                id="identifier"
                                                name="identifier"
                                                autoComplete="username"
                                                autoCapitalize="none"
                                                spellCheck={false}
                                                placeholder="输入邮箱或用户名"
                                                className={cn(styles.input, 'pl-10')}
                                                value={identifier}
                                                onChange={(e) => setIdentifier(e.target.value)}
                                                required
                                            />
                                        </div>
                                    </div>
                                )}

                                <AuthPasswordInput
                                    key={mode}
                                    id="password"
                                    label={mode === 'login' ? '密码' : '设置密码'}
                                    value={password}
                                    onChange={setPassword}
                                    autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                                    minLength={mode === 'register' ? policy?.password_min_length : undefined}
                                />

                                {mode === 'register' && (
                                    <>
                                        <AuthPasswordInput
                                            id="confirmPassword"
                                            label="确认密码"
                                            value={confirmPassword}
                                            onChange={setConfirmPassword}
                                            autoComplete="new-password"
                                            minLength={policy?.password_min_length}
                                        />
                                    </>
                                )}

                                {notice && (
                                    <AuthNotice
                                        key={`${Boolean(error)}:${notice.requestId || notice.message}`}
                                        info={notice}
                                        isSubmitError={Boolean(error)}
                                        onRetry={error ? undefined : refreshPolicy}
                                    />
                                )}

                                <Button
                                    type="submit"
                                    className={cn(styles.submit, 'font-medium motion-reduce:transform-none motion-reduce:transition-none')}
                                    disabled={isSubmitting || isSsoSubmitting}
                                >
                                    {getAuthSubmitContent(isSubmitting, mode)}
                                </Button>
                            </fieldset>
                        </form>
                        {canRegister && (
                            <div data-auth-mode-switch="true" className={styles.modeSwitch} role="group" aria-label="账号选项">
                                <span>{mode === 'login' ? '还没有账号？' : '已有账号？'}</span>
                                <button
                                    type="button"
                                    className={cn('focus-ring disabled:opacity-50', styles.modeButton)}
                                    aria-controls="auth-form"
                                    disabled={isSubmitting || isSsoSubmitting}
                                    onClick={() => handleModeChange(mode === 'login' ? 'register' : 'login')}
                                >
                                    {mode === 'login' ? '注册' : '登录'}
                                </button>
                            </div>
                        )}
                        {policy && (!canRegister || error) && (
                            <p className={styles.help}>
                                <a
                                    href={contactAdminHref}
                                    className="focus-ring mt-1 inline-flex min-h-11 items-center rounded-sm text-sm font-medium text-foreground underline underline-offset-4 transition-colors hover:text-info"
                                >
                                    联系管理员
                                </a>
                            </p>
                        )}
                    </div>
                </section>
            </div>
        </FullScreenFrame>
    )
}
