'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type SyntheticEvent } from 'react'
import Image from 'next/image'
import { FeedbackToast } from '@/components/feedback-toast'
import { ArrowRight, Loader2, Eye, EyeOff, AlertCircle } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useRouter } from '@/i18n/navigation'
import { authApi } from '@/lib/api/auth'
import { getAuthSessionRevision, setAuthSession } from '@/lib/auth-storage'
import { prepareOidcLogin } from '@/lib/oidc'
import { getOidcPublicProvidersFromEnv, type OidcProviderPublic } from '@/lib/oidc-providers'
import { toApiErrorInfo, type ApiErrorInfo } from '@/lib/api-errors'
import { reportClientWarning } from '@/lib/client-logging'
import { FullScreenFrame } from '@/components/full-screen-frame'
import { cn, detachPromise } from '@/lib/utils'
import type { AuthPolicy } from '@/types/backend'
import { AuthBrandPanel } from './auth-brand-panel'
import styles from './auth.module.css'

type Mode = 'login' | 'register'

const DEFAULT_ADMIN_CONTACT_URL = 'https://github.com/skygazer42/MimirQ/issues'
const SAFE_ADMIN_CONTACT_PROTOCOLS = new Set(['http:', 'https:', 'mailto:', 'tel:'])

function getAdminContactHref(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_ADMIN_CONTACT_URL?.trim()
  if (!configuredUrl) return DEFAULT_ADMIN_CONTACT_URL

  try {
    const parsedUrl = new URL(configuredUrl)
    return SAFE_ADMIN_CONTACT_PROTOCOLS.has(parsedUrl.protocol) ? configuredUrl : DEFAULT_ADMIN_CONTACT_URL
  } catch {
    return DEFAULT_ADMIN_CONTACT_URL
  }
}

function getAuthSsoProviderLabel(provider: OidcProviderPublic): string {
  return `使用 ${provider.name ?? provider.id} 登录`
}

function AuthPasswordInput({
  id,
  label,
  value,
  onChange,
  autoComplete,
  minLength,
  recoveryHref,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  autoComplete: 'current-password' | 'new-password'
  minLength?: number
  recoveryHref?: string
}) {
  const [visible, setVisible] = useState(false)
  const [recoveryOpen, setRecoveryOpen] = useState(false)

  return (
    <div className="space-y-2">
      <div className={styles.passwordHeading}>
        <Label htmlFor={id} className="text-sm font-medium text-foreground">
          {label}
        </Label>
        {recoveryHref && (
          <button
            type="button"
            className={cn('focus-ring', styles.recoveryButton)}
            aria-expanded={recoveryOpen}
            aria-controls={`${id}-recovery`}
            onClick={() => setRecoveryOpen((current) => !current)}
          >
            忘记密码？
          </button>
        )}
      </div>
      <div className="relative">
        <Input
          id={id}
          name={id}
          type={visible ? 'text' : 'password'}
          placeholder={
            id === 'confirmPassword'
              ? '再次输入密码'
              : autoComplete === 'new-password'
                ? '设置登录密码'
                : '输入登录密码'
          }
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
      {recoveryOpen && (
        <p id={`${id}-recovery`} className={styles.recoveryHelp}>
          请联系管理员重置密码。
          <a href={recoveryHref} className={cn('focus-ring', styles.helpLink)}>
            联系管理员
          </a>
        </p>
      )}
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

  return <>{mode === 'login' ? '登录' : '注册'}</>
}

function AuthNotice({ info, isSubmitError }: { info: ApiErrorInfo; isSubmitError: boolean }) {
  return (
    <div
      id={isSubmitError ? 'auth-error' : 'auth-service-notice'}
      role={isSubmitError ? 'alert' : 'status'}
      className={styles.notice}
      data-tone={isSubmitError ? 'error' : 'service'}
    >
      <AlertCircle className={styles.noticeIcon} aria-hidden="true" />
      <p className={styles.noticeMessage}>{info.message}</p>
    </div>
  )
}

function toAuthPageError(err: unknown, mode?: Mode): ApiErrorInfo {
  const info = toApiErrorInfo(err, '请求失败')
  if (mode === undefined || info.status === 404 || (info.status !== undefined && info.status >= 500)) {
    return { ...info, message: '服务暂时不可用，请稍后重试。' }
  }
  if (info.status === 429) {
    return { ...info, message: '尝试次数过多，请稍后再试。' }
  }
  if (info.status === undefined) {
    return { ...info, message: '网络连接异常，请检查网络后重试。' }
  }
  if (mode === 'login') {
    if (info.status === 400 || info.status === 401) {
      return { ...info, message: '账号或密码不正确，请核对后重新输入。' }
    }
    if (info.status === 403) {
      return { ...info, message: '暂时无法登录，请联系管理员。' }
    }
    return { ...info, message: '登录失败，请稍后重试或联系管理员。' }
  }

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

  return { ...info, message: '暂时无法注册，请检查注册信息或联系管理员。' }
}

function reportAuthFailure(info: ApiErrorInfo, operation: string) {
  reportClientWarning('Authentication request failed', new Error(`Authentication ${operation} failed`), {
    tags: { operation, http_status: String(info.status ?? 'network'), request_id: info.requestId ?? '' },
  })
}

export default function AuthPage() {
  const router = useRouter()
  const oidcProviders = getOidcPublicProvidersFromEnv()
  const oidcEnabled = oidcProviders.length > 0
  const [selectedMode, setMode] = useState<Mode>(() =>
    typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('mode') === 'register'
      ? 'register'
      : 'login',
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
  const isSsoSubmitting = ssoProviderWorkingId !== null
  const canRegister = Boolean(policy?.registration_enabled)
  const mode = canRegister ? selectedMode : 'login'
  const authVisit = useMemo(() => ({ mode }), [mode])
  const authVisitRef = useRef<typeof authVisit | null>(null)
  const submitRequestRef = useRef<object | null>(null)
  const contactAdminHref = getAdminContactHref()
  const hasRequiredFields =
    mode === 'login'
      ? Boolean(identifier.trim() && password)
      : Boolean(email.trim() && username.trim() && password && confirmPassword)

  useLayoutEffect(() => {
    authVisitRef.current = authVisit
    return () => {
      authVisitRef.current = null
    }
  }, [authVisit])

  useEffect(() => {
    let active = true
    authApi.policy().then(
      (value) => {
        if (active) setPolicy(value)
      },
      (err: unknown) => {
        if (!active) return
        const info = toAuthPageError(err)
        reportAuthFailure(info, 'policy')
        setPolicyError(info)
      },
    )
    return () => {
      active = false
    }
  }, [policyAttempt])

  const refreshPolicy = () => {
    setPolicyError(null)
    setPolicyAttempt((attempt) => attempt + 1)
  }

  const notice =
    error ??
    (isSubmitting
      ? null
      : (policyError ?? (policy && !policy.initialized ? { message: '账号服务尚未准备好，请稍后重试。' } : null)))

  const handleModeChange = (nextMode: Mode) => {
    if (submitRequestRef.current || nextMode === mode || (nextMode === 'register' && !canRegister)) return
    setMode(nextMode)
    setError(null)
    setRegistrationSucceeded(false)
    setPassword('')
    setConfirmPassword('')
  }

  const ownsSubmission = (request: object, sessionRevision: number) =>
    submitRequestRef.current === request &&
    authVisitRef.current === authVisit &&
    getAuthSessionRevision() === sessionRevision

  const handleSso = async (provider: OidcProviderPublic) => {
    if (submitRequestRef.current) return
    const request = {}
    const sessionRevision = getAuthSessionRevision()
    submitRequestRef.current = request
    setError(null)
    setRegistrationSucceeded(false)
    setSsoProviderWorkingId(provider.id)
    try {
      const redirect = await prepareOidcLogin(provider)
      if (ownsSubmission(request, sessionRevision)) {
        redirect()
        return
      }
    } catch (err: unknown) {
      if (ownsSubmission(request, sessionRevision)) {
        const info = { ...toApiErrorInfo(err, '单点登录失败'), message: '单点登录暂时不可用，请稍后重试或联系管理员。' }
        reportAuthFailure(info, 'sso')
        setError(info)
      }
    }
    submitRequestRef.current = null
    if (authVisitRef.current) setSsoProviderWorkingId(null)
  }

  const handleSubmit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitRequestRef.current || !hasRequiredFields) return
    setError(null)
    setRegistrationSucceeded(false)

    if (mode === 'register' && password !== confirmPassword) {
      setError({ message: '两次输入的密码不一致' })
      return
    }

    const request = {}
    const sessionRevision = getAuthSessionRevision()
    submitRequestRef.current = request
    setIsSubmitting(true)
    try {
      if (mode === 'register') {
        const registeredEmail = email.trim()
        await authApi.signup({ email: registeredEmail, username: username.trim(), password })
        if (!ownsSubmission(request, sessionRevision)) return
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
      if (!ownsSubmission(request, sessionRevision)) return
      setAuthSession({ token: response.token, user: response.user })
      router.push('/')
    } catch (err: unknown) {
      if (!ownsSubmission(request, sessionRevision)) return
      const info = toAuthPageError(err, mode)
      reportAuthFailure(info, mode)
      setError(info)
      if (mode === 'register' && (info.status === 409 || info.status === 403)) {
        refreshPolicy()
      }
    } finally {
      if (submitRequestRef.current === request) {
        submitRequestRef.current = null
        if (authVisitRef.current) setIsSubmitting(false)
      }
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
              onClick={() => detachPromise(handleSso(provider))}
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
        onClick={() => detachPromise(handleSso(provider))}
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
    <FullScreenFrame className={cn('w-full', styles.frame)} mainClassName="items-start p-0">
      <div className={styles.shell} data-auth-layout="centered">
        <AuthBrandPanel />
        <section className={styles.formPanel} data-auth-panel="ruled" aria-labelledby="auth-title">
          <Image
            src="/brand/explorations/ragvia/logo.svg"
            alt="ragvia"
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
              <p className={styles.subtitle}>{mode === 'login' ? '登录 ragvia' : '使用邮箱注册'}</p>
            </header>
            <FeedbackToast
              type="success"
              message={registrationSucceeded ? '注册成功，请登录。' : null}
              id="registration-feedback"
            />

            {!policy && !policyError && (
              <p role="status" className="sr-only">
                正在检查账号服务…
              </p>
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

            <form
              id="auth-form"
              onSubmit={handleSubmit}
              className={styles.form}
              aria-busy={isSubmitting}
              aria-describedby={notice ? (error ? 'auth-error' : 'auth-service-notice') : undefined}
            >
              <fieldset className={styles.fields} disabled={isSubmitting || isSsoSubmitting}>
                {mode === 'register' && (
                  <div className="space-y-5">
                    <div className="space-y-2">
                      <Label htmlFor="email" className="text-sm font-medium text-foreground">
                        邮箱地址
                      </Label>
                      <div className="relative group">
                        <Input
                          id="email"
                          name="email"
                          type="email"
                          autoComplete="email"
                          placeholder="邮箱地址"
                          className={styles.input}
                          value={email}
                          onChange={(e) => setEmail(e.target.value)}
                          required
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="username" className="text-sm font-medium text-foreground">
                        用户名
                      </Label>
                      <div className="relative group">
                        <Input
                          id="username"
                          name="username"
                          autoComplete="username"
                          minLength={3}
                          maxLength={64}
                          placeholder="设置用户名"
                          className={styles.input}
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
                    <Label htmlFor="identifier" className="text-sm font-medium text-foreground">
                      账号
                    </Label>
                    <div className="relative group">
                      <Input
                        id="identifier"
                        name="identifier"
                        autoComplete="username"
                        autoCapitalize="none"
                        spellCheck={false}
                        placeholder="邮箱或用户名"
                        className={styles.input}
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
                  recoveryHref={mode === 'login' ? contactAdminHref : undefined}
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
                  />
                )}

                <Button
                  type="submit"
                  className={cn(
                    styles.submit,
                    'font-medium motion-reduce:transform-none motion-reduce:transition-none',
                  )}
                  disabled={isSubmitting || isSsoSubmitting || !hasRequiredFields}
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
            {policy && !canRegister && (
              <p className={styles.help}>
                还没有账号？
                <a href={contactAdminHref} className={cn('focus-ring', styles.helpLink)}>
                  联系管理员开通
                </a>
              </p>
            )}
          </div>
        </section>
      </div>
    </FullScreenFrame>
  )
}
