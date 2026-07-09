import { cn } from "@/lib/utils"
import { STATUS_LABEL, type StatusKey } from "@/lib/types"

const STATUS_CLASS: Record<StatusKey, string> = {
  compliant: "bg-status-compliant-bg text-status-compliant border-status-compliant/30",
  noncompliant: "bg-status-noncompliant-bg text-status-noncompliant border-status-noncompliant/30",
  revision: "bg-status-revision-bg text-status-revision border-status-revision/40",
  na: "bg-status-na-bg text-status-na border-status-na/30",
  unknown: "bg-muted text-muted-foreground border-border",
}

export function StatusBadge({ status, className }: { status: StatusKey; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        STATUS_CLASS[status],
        className,
      )}
    >
      <span
        aria-hidden
        className={cn("size-1.5 rounded-full", {
          "bg-status-compliant": status === "compliant",
          "bg-status-noncompliant": status === "noncompliant",
          "bg-status-revision": status === "revision",
          "bg-status-na": status === "na",
          "bg-muted-foreground": status === "unknown",
        })}
      />
      {STATUS_LABEL[status]}
    </span>
  )
}

export function AttentionBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-status-attention/40 bg-status-attention-bg px-2 py-0.5 text-xs font-semibold text-status-attention whitespace-nowrap",
        className,
      )}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-status-attention" />
      확인필요
    </span>
  )
}
