import type { ReactNode } from "react"

export function StepHeader({
  step,
  title,
  description,
  actions,
}: {
  step: number
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-border bg-background/95 px-8 py-4 backdrop-blur">
      <div className="min-w-0">
        <p className="text-xs font-medium text-primary">STEP {step}</p>
        <h2 className="truncate text-lg font-semibold text-foreground">{title}</h2>
        {description && <p className="mt-0.5 truncate text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}
