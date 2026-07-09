"use client"

import { useState } from "react"
import { Check, Copy } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type CopyButtonProps = {
  text?: string | null
  label: string
  size?: "sm" | "default"
  variant?: "default" | "outline" | "secondary"
  className?: string
  disabled?: boolean
}

export function CopyButton({ text, label, size = "sm", variant = "outline", className, disabled }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)
  const isEmpty = !text || !text.trim()

  async function handleCopy() {
    if (isEmpty) {
      toast.error("복사할 내용이 없습니다.")
      return
    }
    try {
      await navigator.clipboard.writeText(text as string)
      setCopied(true)
      toast.success(`${label} 완료`)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error("복사에 실패했습니다.")
    }
  }

  return (
    <Button
      type="button"
      size={size}
      variant={variant}
      onClick={handleCopy}
      disabled={disabled || isEmpty}
      className={cn("gap-1.5", className)}
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      {label}
    </Button>
  )
}
