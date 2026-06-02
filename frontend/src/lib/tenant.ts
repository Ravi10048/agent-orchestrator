import { create } from "zustand";

// The active tenant (multi-tenant SaaS). Persisted to localStorage; the api client sends it as the
// `X-Tenant-Id` header on every request. null → the backend uses its default tenant.
const KEY = "tenantId";
const stored = (typeof localStorage !== "undefined" && localStorage.getItem(KEY)) || null;

export const useTenant = create<{ tenantId: number | null; setTenantId: (id: number | null) => void }>(
  (set) => ({
    tenantId: stored ? Number(stored) : null,
    setTenantId: (id) => {
      try {
        if (id == null) localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, String(id));
      } catch {
        /* ignore */
      }
      set({ tenantId: id });
    },
  }),
);
