import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Check, ChevronsUpDown, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import type { ApiError } from "@/api/client";
import { Tenants } from "@/api/resources";
import { cn } from "@/lib/cn";
import { useTenant } from "@/lib/tenant";
import { toast } from "@/lib/toast";

/** Org/tenant switcher (multi-tenant SaaS). Switching re-scopes every list to the chosen tenant
 *  (sets the X-Tenant-Id header + invalidates the query cache). Also creates new tenants — each is
 *  auto-bootstrapped server-side with a Supervisor + the default tools. */
export function TenantSwitcher() {
  const qc = useQueryClient();
  const { tenantId, setTenantId } = useTenant();
  const { data: tenants } = useQuery({ queryKey: ["tenants"], queryFn: Tenants.list });
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  // on first load, default to the backend's default tenant so the header is always set
  useEffect(() => {
    if (tenants && tenantId == null) {
      const def = tenants.find((t) => t.is_default) ?? tenants[0];
      if (def) setTenantId(def.id);
    }
  }, [tenants, tenantId, setTenantId]);

  const current = tenants?.find((t) => t.id === tenantId) ?? tenants?.find((t) => t.is_default);

  const switchTo = (id: number) => {
    setTenantId(id);
    setOpen(false);
    qc.invalidateQueries(); // refetch every list for the newly-selected tenant
  };

  const create = useMutation({
    mutationFn: () => Tenants.create(name.trim()),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      setName("");
      setCreating(false);
      switchTo(t.id);
      toast.success(`Created "${t.name}" — starts with the default tools; add your own agents`);
    },
    onError: (e) => toast.error((e as unknown as ApiError).message ?? "Failed to create tenant"),
  });

  return (
    <div className="relative px-3 pb-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-2 text-left transition hover:border-border-strong"
      >
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
          <Building2 className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[10px] uppercase tracking-wider text-muted/70">Tenant</span>
          <span className="block truncate text-sm font-medium">{current?.name ?? "Select org"}</span>
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute left-3 right-3 z-20 mt-1 overflow-hidden rounded-lg border border-border bg-card shadow-pop">
            <div className="max-h-60 overflow-y-auto scroll-thin py-1">
              {tenants?.map((t) => (
                <button
                  key={t.id}
                  onClick={() => switchTo(t.id)}
                  className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-sm transition hover:bg-surface"
                >
                  <Building2 className="h-4 w-4 shrink-0 text-muted" />
                  <span className="min-w-0 flex-1 truncate">{t.name}</span>
                  {t.is_default && <span className="text-[10px] text-muted">default</span>}
                  {t.id === current?.id && <Check className="h-4 w-4 shrink-0 text-primary" />}
                </button>
              ))}
            </div>

            <div className="border-t border-border p-1">
              {creating ? (
                <div className="flex items-center gap-1">
                  <input
                    autoFocus
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && name.trim() && create.mutate()}
                    placeholder="New org name…"
                    className="h-8 min-w-0 flex-1 rounded-md border border-border bg-bg px-2 text-sm outline-none focus:border-primary"
                  />
                  <button
                    onClick={() => create.mutate()}
                    disabled={!name.trim() || create.isPending}
                    className="rounded-md bg-primary px-2.5 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    Add
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setCreating(true)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-muted transition hover:bg-surface hover:text-fg",
                  )}
                >
                  <Plus className="h-4 w-4" /> New tenant
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
