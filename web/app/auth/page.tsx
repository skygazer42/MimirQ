'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { User, Mail, Lock, Sparkles, ArrowRight, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authApi } from '@/lib/api-client'
import { setAuthSession } from '@/lib/auth-storage'
import { formatApiError } from '@/lib/api-errors'
import { ParticleBackground } from '@/components/ui/particle-background'
import { FullScreenFrame } from '@/components/full-screen-frame'
import { cn } from '@/lib/utils'

type Mode = 'login' | 'register'

export default function AuthPage() {
    const router = useRouter()
    const [mode, setMode] = useState<Mode>('login')
    const [email, setEmail] = useState('')
    const [username, setUsername] = useState('')
    const [identifier, setIdentifier] = useState('')
    const [password, setPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault()
        setError(null)

        if (mode === 'register' && password !== confirmPassword) {
            setError('两次输入的密码不一致')
            return
        }

        setIsSubmitting(true)
        try {
            const response =
                mode === 'login'
                    ? await authApi.login({ identifier: identifier.trim(), password })
                    : await authApi.register({ email: email.trim(), username: username.trim(), password })
            setAuthSession({ token: response.token, user: response.user })
            router.push('/')
        } catch (err: any) {
            setError(formatApiError(err, '请求失败，请重试'))
        } finally {
            setIsSubmitting(false)
        }
    }

    return (
        <FullScreenFrame
            showBackground={false}
            className="relative w-full overflow-hidden bg-gradient-to-br from-background via-background to-card text-foreground"
        >
            {/* 3D 粒子背景 */}
            <ParticleBackground />

            {/* 光效装饰 */}
            <div className="pointer-events-none absolute inset-0 bg-hero-glow opacity-40 motion-reduce:opacity-25" />
            <div className="absolute top-[-20%] left-[-10%] w-[500px] h-[500px] bg-primary/20 rounded-full blur-[120px] motion-safe:animate-pulse-subtle pointer-events-none" />
            <div className="absolute bottom-[-20%] right-[-10%] w-[500px] h-[500px] bg-info/15 rounded-full blur-[120px] motion-safe:animate-pulse-subtle pointer-events-none" style={{ animationDelay: '1s' }} />

            <div className="relative z-10 w-full max-w-md p-6 motion-safe:animate-fade-in-up">
                {/* Logo / Brand */}
                <div className="flex flex-col items-center mb-8 space-y-4">
                    <div className="relative group">
                        <div className="absolute -inset-1 bg-gradient-to-r from-primary to-info rounded-xl blur opacity-40 group-hover:opacity-75 transition duration-500 motion-reduce:transition-none"></div>
                        <div className="relative w-16 h-16 glass rounded-xl flex items-center justify-center border border-border/60 shadow-glow">
                            <Sparkles className="w-8 h-8 text-primary motion-safe:animate-pulse" />
                        </div>
                    </div>
                    <div className="text-center">
                        <h1 className="text-3xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-b from-foreground to-muted-foreground">
                            MimirQ
                        </h1>
                        <p className="text-sm text-muted-foreground mt-2 font-medium tracking-wide">
                            下一代智能知识库平台
                        </p>
                    </div>
                </div>

                {/* 玻璃拟态卡片 */}
                <div className="glass rounded-3xl p-8 shadow-strong ring-1 ring-border/40">
                    {/* Tab Switcher */}
                    <div className="flex p-1 bg-background/40 rounded-xl mb-8 border border-border/50">
                        <button
                            type="button"
                            className={cn(
                                "focus-ring flex-1 py-2 text-sm font-medium rounded-lg transition-colors duration-200 motion-reduce:transition-none",
                                mode === 'login'
                                    ? "bg-card/60 text-foreground shadow-sm"
                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/40"
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
                                    : "text-muted-foreground hover:text-foreground hover:bg-accent/40"
                            )}
                            onClick={() => setMode('register')}
                        >
                            注册
                        </button>
                    </div>

                    <form onSubmit={handleSubmit} className="space-y-5">
                        {mode === 'register' && (
                            <div className="space-y-4 motion-safe:animate-fade-in">
                                <div className="space-y-2">
                                    <Label htmlFor="email" className="text-xs text-muted-foreground">邮箱地址</Label>
                                    <div className="relative group">
                                        <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
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
                                        <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
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
                            </div>
                        )}

                        {mode === 'login' && (
                            <div className="space-y-2 motion-safe:animate-fade-in">
                                <Label htmlFor="identifier" className="text-xs text-muted-foreground">账号</Label>
                                <div className="relative group">
                                    <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
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
                                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
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
                                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-focus-within:text-primary transition-colors motion-reduce:transition-none" />
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
                            <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 flex items-start gap-2 motion-safe:animate-fade-in">
                                <div className="w-1 h-1 mt-2 rounded-full bg-destructive shrink-0" />
                                <p className="text-xs text-destructive">{error}</p>
                            </div>
                        )}

                        <Button
                            type="submit"
                            className="w-full h-11 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl shadow-lg shadow-primary/20 transition-colors duration-200 motion-reduce:transition-none motion-safe:hover:scale-[1.02] motion-safe:active:scale-[0.98]"
                            disabled={isSubmitting}
                        >
	                            {isSubmitting ? (
	                                <>
	                                    <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
	                                    处理中...
	                                </>
	                            ) : (
                                <>
                                    {mode === 'login' ? '登 录' : '创建账户'}
                                    <ArrowRight className="ml-2 h-4 w-4 opacity-70" />
                                </>
                            )}
                        </Button>
                    </form>
                </div>

                <div className="mt-8 text-center">
                    <p className="text-xs text-muted-foreground">
                        遇到问题？{" "}
                        <a
                            href="#"
                            className="focus-ring text-foreground/80 hover:text-foreground underline underline-offset-4 transition-colors motion-reduce:transition-none"
                        >
                            联系管理员
                        </a>
                    </p>
                </div>
            </div>
        </FullScreenFrame>
    )
}
