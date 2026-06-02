import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { ApiError } from "@/api/client";
import { Tools } from "@/api/resources";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { toast } from "@/lib/toast";

/** Import HTTP tools from an OpenAPI/Swagger spec — one tool per operation, into the current tenant.
 *  Give a spec URL (…/openapi.json, or a /docs page) or paste a spec. */
export function ImportToolsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [spec, setSpec] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  const imp = useMutation({
    mutationFn: () => {
      const body: { url?: string; spec?: Record<string, unknown>; base_url?: string } = {};
      if (spec.trim()) body.spec = JSON.parse(spec); // SyntaxError → handled in onError
      else body.url = url.trim();
      if (baseUrl.trim()) body.base_url = baseUrl.trim();
      return Tools.importSpec(body);
    },
    onSuccess: (tools) => {
      qc.invalidateQueries(); // refetch the tools list (current tenant)
      toast.success(`Imported ${tools.length} tool${tools.length === 1 ? "" : "s"}`);
      setSpec("");
      setBaseUrl("");
      onClose();
    },
    onError: (e) => {
      const msg = e instanceof SyntaxError ? "Pasted spec isn't valid JSON" : (e as unknown as ApiError).message;
      toast.error(msg ?? "Import failed");
    },
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import tools from an API spec"
      description="Creates one HTTP tool per operation, in the current tenant. Give a spec URL, or paste a spec."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => imp.mutate()} disabled={imp.isPending || (!url.trim() && !spec.trim())}>
            {imp.isPending ? "Importing…" : "Import"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label>Spec URL</Label>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.example.com/openapi.json" />
          <p className="text-xs text-muted">
            Point at the spec itself (e.g. <code className="font-mono">…/openapi.json</code>), not the Swagger UI
            page (<code className="font-mono">…/docs</code>) — though a <code className="font-mono">/docs</code> URL is
            followed to the spec automatically.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label>
            …or paste a spec <span className="font-normal text-muted">(JSON — used instead of the URL)</span>
          </Label>
          <Textarea
            value={spec}
            onChange={(e) => setSpec(e.target.value)}
            placeholder='{ "openapi": "3.0.0", "servers": [...], "paths": { ... } }'
            className="min-h-[120px] font-mono text-xs"
          />
        </div>

        <div className="space-y-1.5">
          <Label>
            Base URL override <span className="font-normal text-muted">(optional)</span>
          </Label>
          <Input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="point the generated tools at a different host"
          />
        </div>
      </div>
    </Modal>
  );
}
