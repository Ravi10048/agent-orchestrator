import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { useRunMutations } from "@/hooks/queries";
import { getLastChatId, saveLastChatId } from "@/lib/prefs";
import { toast } from "@/lib/toast";

/** Confirm/edit input then start a run — used by Templates + the Workflow Builder. */
export function RunModal({
  open,
  onClose,
  workflowId,
  workflowName,
  defaultInput = "",
}: {
  open: boolean;
  onClose: () => void;
  workflowId: number;
  workflowName: string;
  defaultInput?: string;
}) {
  const [text, setText] = useState(defaultInput);
  const [chatId, setChatId] = useState("");
  const { create } = useRunMutations();
  const navigate = useNavigate();

  useEffect(() => {
    if (open) {
      setText(defaultInput);
      setChatId(getLastChatId()); // pre-fill the last Telegram chat id used
    }
  }, [open, defaultInput]);

  const run = async () => {
    try {
      const input: Record<string, unknown> = { text };
      if (chatId.trim()) {
        input.chat_id = chatId.trim();
        saveLastChatId(chatId); // remember it for next time
      }
      const r = await create.mutateAsync({ workflowId, input });
      toast.success(`Run #${r.id} started`);
      onClose();
      navigate(`/runs?run=${r.id}`);
    } catch (e) {
      toast.error((e as ApiError).message ?? "Failed to start run");
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Run · ${workflowName}`}
      description="Edit the input, then run. You can watch it live in the monitor."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={run} disabled={create.isPending}>
            {create.isPending ? "Starting…" : "Run workflow"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="run-input">Input</Label>
          <Textarea
            id="run-input"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Research the latest on small language models and write a short brief."
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="run-chat">
            Telegram chat id <span className="font-normal text-muted">— optional, lets the Notifier push there</span>
          </Label>
          <Input
            id="run-chat"
            value={chatId}
            onChange={(e) => setChatId(e.target.value)}
            placeholder="e.g. 123456789"
          />
        </div>
      </div>
    </Modal>
  );
}
