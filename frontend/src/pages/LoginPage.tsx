import { zodResolver } from '@hookform/resolvers/zod'
import { Shield } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { Button, Card, Field, Input } from '@/components/ui/primitives'
import { problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'

const schema = z.object({
  email: z.string().min(3, 'Enter your email').regex(/^[^@\s]+@[^@\s]+$/, 'Enter a valid email'),
  password: z.string().min(1, 'Enter your password'),
  otp: z.union([z.literal(''), z.string().regex(/^\d{6}$/, 'Six digits')]).optional(),
})
type Form = z.infer<typeof schema>

export default function LoginPage() {
  const { login, user } = useAuth()
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string } }
  const [err, setErr] = useState<string | null>(null)
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { email: '', password: '', otp: '' } })
  if (user) return <Navigate to={loc.state?.from ?? '/'} replace />

  const onSubmit = handleSubmit(async (v) => {
    setErr(null)
    try {
      await login(v.email, v.password, v.otp || undefined)
      nav(loc.state?.from ?? '/', { replace: true })
    } catch (e) {
      setErr(problemMessage(e))
    }
  })

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-5 flex items-center gap-2">
          <Shield className="text-accent" />
          <div>
            <h1 className="text-base font-bold">BITGUARD AI</h1>
            <p className="text-xs text-muted">Bitcoin transaction intelligence · authorised use only</p>
          </div>
        </div>
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          <Field label="Email" error={formState.errors.email?.message}>
            <Input type="email" autoComplete="username" {...register('email')} />
          </Field>
          <Field label="Password" error={formState.errors.password?.message}>
            <Input type="password" autoComplete="current-password" {...register('password')} />
          </Field>
          <Field label="One-time code (if MFA enabled)" error={formState.errors.otp?.message}>
            <Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} {...register('otp')} />
          </Field>
          {err && <p role="alert" className="rounded border border-crit/40 bg-crit/10 p-2 text-xs text-crit">{err}</p>}
          <Button type="submit" variant="primary" className="w-full" disabled={formState.isSubmitting}>
            {formState.isSubmitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
        <p className="mt-4 text-[11px] leading-relaxed text-muted">
          All activity is audited. Outputs are investigative leads, not legal conclusions.
        </p>
      </Card>
    </div>
  )
}
