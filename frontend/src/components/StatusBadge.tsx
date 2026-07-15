import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

import type { JobStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const CONFIG: Record<
  JobStatus,
  { label: string; className: string; icon: typeof Clock; spin?: boolean }
> = {
  queued: {
    label: "Queued",
    className: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
    icon: Clock,
  },
  processing: {
    label: "Processing",
    className: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
    icon: Loader2,
    spin: true,
  },
  done: {
    label: "Done",
    className: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
    icon: CheckCircle2,
  },
  failed: {
    label: "Failed",
    className: "bg-destructive/15 text-destructive",
    icon: XCircle,
  },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const { label, className, icon: Icon, spin } = CONFIG[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        className,
      )}
    >
      <Icon className={cn("size-3.5", spin && "animate-spin")} />
      {label}
    </span>
  );
}
