import { type LucideIcon } from "lucide-react";
import { type ReactNode } from "react";

import { Card } from "@/components/ui/card";

export function StatCard({ label, value, icon: Icon }: { label: string; value: ReactNode; icon?: LucideIcon }) {
  return (
    <Card className="p-4 transition hover:border-border-strong">
      <div className="flex items-center gap-2.5">
        {Icon && (
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
            <Icon className="h-4 w-4" />
          </span>
        )}
        <span className="text-sm text-muted">{label}</span>
      </div>
      <div className="mt-3 text-[28px] font-semibold leading-none tabular-nums">{value}</div>
    </Card>
  );
}
