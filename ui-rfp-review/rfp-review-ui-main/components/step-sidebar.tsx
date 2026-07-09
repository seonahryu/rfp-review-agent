"use client"

import { Check, Lock } from "lucide-react"
import { STEPS, type StepKey, stepIndexOf } from "@/lib/steps"
import { cn } from "@/lib/utils"

type StepSidebarProps = {
  current: StepKey
  maxReached: StepKey
  onNavigate: (key: StepKey) => void
}

export function StepSidebar({ current, maxReached, onNavigate }: StepSidebarProps) {
  const currentIdx = stepIndexOf(current)
  const reachedIdx = stepIndexOf(maxReached)

  return (
    <nav aria-label="검토 단계" className="flex w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="border-b border-sidebar-border px-5 py-4">
        <h1 className="text-sm font-semibold text-sidebar-foreground">RFP 법제도 검토</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">검토결과 확인과 최종 복사 흐름</p>
      </div>
      <ol className="flex flex-1 flex-col gap-1 p-3">
        {STEPS.map((step, idx) => {
          const isCurrent = idx === currentIdx
          const isDone = idx < reachedIdx
          const isReachable = idx <= reachedIdx
          const isLocked = !isReachable

          return (
            <li key={step.key}>
              <button
                type="button"
                disabled={isLocked}
                onClick={() => isReachable && onNavigate(step.key)}
                aria-current={isCurrent ? "step" : undefined}
                className={cn(
                  "flex w-full items-start gap-3 rounded-md px-3 py-2.5 text-left transition-colors",
                  isCurrent && "bg-sidebar-accent",
                  !isCurrent && isReachable && "hover:bg-sidebar-accent/60",
                  isLocked && "cursor-not-allowed opacity-55",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                    isCurrent && "border-sidebar-primary bg-sidebar-primary text-sidebar-primary-foreground",
                    isDone && "border-status-compliant bg-status-compliant text-white",
                    !isCurrent && !isDone && isReachable && "border-border bg-card text-muted-foreground",
                    isLocked && "border-border bg-muted text-muted-foreground",
                  )}
                >
                  {isDone ? <Check className="size-3.5" /> : isLocked ? <Lock className="size-3" /> : step.index}
                </span>
                <span className="min-w-0">
                  <span className={cn("block text-sm font-medium", isCurrent ? "text-sidebar-foreground" : "text-sidebar-foreground/90")}>
                    {step.title}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{step.desc}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>
      <div className="border-t border-sidebar-border px-5 py-3">
        <p className="text-xs leading-relaxed text-muted-foreground">업로드가 끝나면 바로 검토결과 확인으로 이동합니다.</p>
      </div>
    </nav>
  )
}
