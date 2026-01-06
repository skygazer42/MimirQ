'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { User, Mail, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authApi } from '@/lib/api-client'
import { setAuthSession } from '@/lib/auth-storage'

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
      setError(err?.response?.data?.detail || err?.message || '请求失败，请重试')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-6 py-10">
      <Card className="w-full max-w-md p-8">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold text-slate-900">MimirQ 账户</h1>
          <p className="text-sm text-slate-500 mt-2">
            {mode === 'login' ? '登录后管理您的知识库' : '注册新账号开始使用'}
          </p>
        </div>

        <div className="flex gap-2 mb-6">
          <Button
            type="button"
            variant={mode === 'login' ? 'default' : 'outline'}
            className="flex-1"
            onClick={() => setMode('login')}
          >
            登录
          </Button>
          <Button
            type="button"
            variant={mode === 'register' ? 'default' : 'outline'}
            className="flex-1"
            onClick={() => setMode('register')}
          >
            注册
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'register' && (
            <>
              <div className="space-y-2">
                <Label htmlFor="email">邮箱</Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    placeholder="name@example.com"
                    className="pl-9"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="username">用户名</Label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                  <Input
                    id="username"
                    placeholder="输入用户名"
                    className="pl-9"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                </div>
              </div>
            </>
          )}

          {mode === 'login' && (
            <div className="space-y-2">
              <Label htmlFor="identifier">邮箱或用户名</Label>
              <Input
                id="identifier"
                placeholder="邮箱或用户名"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                required
              />
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="password">密码</Label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                id="password"
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                placeholder="请输入密码"
                className="pl-9"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          {mode === 'register' && (
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">确认密码</Label>
              <Input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                placeholder="再次输入密码"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </div>
          )}

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600">
              {error}
            </div>
          )}

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? '处理中...' : mode === 'login' ? '登录' : '注册'}
          </Button>
        </form>

        <div className="mt-6 text-xs text-slate-500">
          开发模式下可无需登录，继续使用默认 `X-User-ID` 进行访问。
        </div>
      </Card>
    </div>
  )
}
