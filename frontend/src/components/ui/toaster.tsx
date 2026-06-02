import { CheckCircle2, Info, XCircle } from "lucide-react";

import { cn } from "@/lib/cn";
import { useToasts } from "@/lib/toast";

const ICON = { success: CheckCircle2, error: XCircle, info: Info } as const;
const TONE = {
  success: "border-success/30 text-success",
  error: "border-destructive/30 text-destructive",
  info: "border-info/30 text-info",
} as const;

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="fixed bottom-4 right-4 z-[80] flex flex-col gap-2">
      {toasts.map((t) => {
        const Icon = ICON[t.tone];
        return (
          <div
            key={t.id}
            onClick={() => dismiss(t.id)}
            role="status"
            className={cn(
              "flex min-w-[240px] max-w-sm cursor-pointer items-center gap-2.5 rounded-lg border bg-card px-4 py-3",
              "text-sm shadow-pop animate-fade-in",
              TONE[t.tone],
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="text-fg">{t.title}</span>
          </div>
        );
      })}
    </div>
  );
}
