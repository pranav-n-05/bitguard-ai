import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { Check, Copy, X } from 'lucide-react'
import { forwardRef, useState, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/utils/cn'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap',
  {
    variants: {
      variant: {
        primary: 'bg-accent text-bg hover:bg-accent/90',
        secondary: 'bg-bg-2 text-text border border-line hover:bg-card',
        ghost: 'text-muted hover:text-text hover:bg-card',
        danger: 'bg-crit/90 text-white hover:bg-crit',
        link: 'text-accent-2 underline-offset-2 hover:underline px-0',
      },
      size: { sm: 'h-7 px-2.5 text-xs', md: 'h-9 px-3.5', icon: 'h-8 w-8' },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
)

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button'
  return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
})
Button.displayName = 'Button'

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-lg border border-line bg-card', className)} {...p} />
}
export function CardHeader({ title, actions, subtitle }: { title: ReactNode; actions?: ReactNode; subtitle?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
export function CardBody({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-4', className)} {...p} />
}

const badgeVariants = cva('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide border', {
  variants: {
    tone: {
      neutral: 'border-line text-muted bg-bg-2',
      info: 'border-accent-2/40 text-accent-2 bg-accent-2/10',
      ok: 'border-ok/40 text-ok bg-ok/10',
      warn: 'border-warn/40 text-warn bg-warn/10',
      crit: 'border-crit/40 text-crit bg-crit/10',
      accent: 'border-accent/40 text-accent bg-accent/10',
    },
  },
  defaultVariants: { tone: 'neutral' },
})
export function Badge({ tone, className, ...p }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...p} />
}

const fieldCls = 'h-9 w-full rounded-md border border-line bg-bg-2 px-2.5 text-sm text-text placeholder:text-muted/70 focus:border-accent-2 focus:outline-none'
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn(fieldCls, className)} {...p} />
))
Input.displayName = 'Input'
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...p }, ref) => (
  <select ref={ref} className={cn(fieldCls, 'pr-7', className)} {...p} />
))
Select.displayName = 'Select'
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn(fieldCls, 'h-auto min-h-20 py-2', className)} {...p} />
))
Textarea.displayName = 'Textarea'

export function Field({ label, error, children, hint }: { label: string; error?: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && !error && <span className="block text-xs text-muted/80">{hint}</span>}
      {error && <span role="alert" className="block text-xs text-crit">{error}</span>}
    </label>
  )
}

export function Table({ className, ...p }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto">
      <table className={cn('w-full border-collapse text-sm', className)} {...p} />
    </div>
  )
}
export const Th = ({ className, ...p }: HTMLAttributes<HTMLTableCellElement>) => (
  <th className={cn('border-b border-line px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted', className)} {...p} />
)
export const Td = ({ className, ...p }: HTMLAttributes<HTMLTableCellElement> & { colSpan?: number }) => (
  <td className={cn('border-b border-line/60 px-3 py-2 align-top', className)} {...p} />
)

export function KV({ items, cols = 2 }: { items: [string, ReactNode][]; cols?: 1 | 2 | 3 }) {
  return (
    <dl className={cn('grid gap-x-6 gap-y-2', cols === 1 ? 'grid-cols-1' : cols === 2 ? 'sm:grid-cols-2' : 'sm:grid-cols-3')}>
      {items.map(([k, v]) => (
        <div key={k} className="min-w-0">
          <dt className="text-xs text-muted">{k}</dt>
          <dd className="truncate text-sm">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function CopyText({ value, display, className }: { value: string; display?: string; className?: string }) {
  const [done, setDone] = useState(false)
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1', className)}>
      <span className="mono truncate" title={value}>{display ?? value}</span>
      <button
        type="button"
        aria-label="Copy to clipboard"
        className="shrink-0 text-muted hover:text-text"
        onClick={() => {
          void navigator.clipboard?.writeText(value)
          setDone(true)
          setTimeout(() => setDone(false), 1200)
        }}
      >
        {done ? <Check size={13} /> : <Copy size={13} />}
      </button>
    </span>
  )
}

export function Sheet({ open, onOpenChange, title, children, wide }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; children: ReactNode; wide?: boolean }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <DialogPrimitive.Content className={cn('fixed right-0 top-0 z-50 flex h-full w-full flex-col border-l border-line bg-bg-2 shadow-xl', wide ? 'max-w-4xl' : 'max-w-2xl')}>
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <DialogPrimitive.Title className="text-sm font-semibold">{title}</DialogPrimitive.Title>
            <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
            <DialogPrimitive.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close"><X size={16} /></Button>
            </DialogPrimitive.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-4">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

export function Modal({ open, onOpenChange, title, children }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; children: ReactNode }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 w-[min(560px,94vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-bg-2 p-5 shadow-xl">
          <DialogPrimitive.Title className="mb-1 text-base font-semibold">{title}</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { id: T; label: ReactNode }[] }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={cn('-mb-px border-b-2 px-3 py-2 text-sm', value === t.id ? 'border-accent text-text' : 'border-transparent text-muted hover:text-text')}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
