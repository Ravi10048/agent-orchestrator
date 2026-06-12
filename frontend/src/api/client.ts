import axios from "axios";

import { useTenant } from "@/lib/tenant";

/** Normalised error matching the LLD 09 envelope `{error:{code,message,details}}`. */
export interface ApiError {
  status: number;
  code: string;
  message: string;
  details?: unknown;
  /** 422 field errors flattened to `{field: message}` for forms. */
  fieldErrors?: Record<string, string>;
}

// VITE_API_URL is set for split deploys (frontend + backend on different hosts); empty locally,
// where nginx (Docker) / Vite (dev) proxy /api → backend on the same origin.
export const api = axios.create({ baseURL: (import.meta.env.VITE_API_URL ?? "") + "/api" });

// scope every request to the active tenant (multi-tenant SaaS)
api.interceptors.request.use((config) => {
  const id = useTenant.getState().tenantId;
  if (id != null) config.headers["X-Tenant-Id"] = String(id);
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    const status: number = err.response?.status ?? 0;
    const body = err.response?.data;
    if (body?.error) {
      const e: ApiError = { status, code: body.error.code, message: body.error.message, details: body.error.details };
      if (status === 422 && Array.isArray(body.error.details)) {
        e.fieldErrors = {};
        for (const d of body.error.details) {
          const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : String(d.loc);
          e.fieldErrors[String(field)] = d.msg ?? "invalid";
        }
      }
      return Promise.reject(e);
    }
    return Promise.reject({ status, code: "network_error", message: err.message ?? "Network error" } as ApiError);
  },
);
