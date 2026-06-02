import { useCallback, useEffect, useRef, useState } from "react";

import { Runs } from "@/api/resources";
import type { EventEnvelope } from "@/api/types";

export type SocketStatus = "connecting" | "open" | "closed";

/**
 * Live run monitor (LLD 09 protocol): connect /ws/monitor → subscribe → receive EventEnvelopes.
 * Dedupes + orders by (run_id, seq); auto-reconnects with backoff+jitter; on reconnect closes the
 * gap via GET /runs/{id}/events?after_seq=<lastSeq>. One renderer for live + replay.
 */
export function useMonitorSocket(runId: number | null) {
  const [status, setStatus] = useState<SocketStatus>("closed");
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const seen = useRef<Set<number>>(new Set());
  const lastSeq = useRef(0);
  const ws = useRef<WebSocket | null>(null);
  const retry = useRef(0);
  const stopped = useRef(false);

  const add = useCallback(
    (incoming: EventEnvelope[]) => {
      // Dedup + ref bookkeeping happen HERE (called once per batch), NOT inside the setState
      // updater — an updater that mutates refs is impure and gets double-run by React StrictMode
      // / concurrent mode, which silently drops events (esp. a backfill burst on a finished run).
      const fresh: EventEnvelope[] = [];
      for (const e of incoming) {
        if (e.run_id !== runId || seen.current.has(e.seq)) continue;
        seen.current.add(e.seq);
        if (e.seq > lastSeq.current) lastSeq.current = e.seq;
        fresh.push(e);
      }
      if (fresh.length === 0) return;
      setEvents((prev) => [...prev, ...fresh].sort((a, b) => a.seq - b.seq)); // pure updater
    },
    [runId],
  );

  useEffect(() => {
    if (!runId) return;
    stopped.current = false;
    seen.current = new Set();
    lastSeq.current = 0;
    setEvents([]);

    // Initial load from the REST mirror — reliable for FINISHED runs (which have no live tail to
    // populate them). The WS subscribe below layers live updates on top; both are deduped by seq.
    Runs.events(runId, 0)
      .then((evs) => {
        if (!stopped.current) add(evs);
      })
      .catch(() => {
        /* the WS backfill is the fallback */
      });

    const connect = () => {
      if (stopped.current) return;
      setStatus("connecting");
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${proto}//${location.host}/ws/monitor`);
      ws.current = socket;

      socket.onopen = async () => {
        retry.current = 0;
        setStatus("open");
        if (lastSeq.current > 0) {
          try {
            add(await Runs.events(runId, lastSeq.current)); // close the gap on reconnect
          } catch {
            /* the live tail + next reconnect will recover */
          }
        }
        socket.send(JSON.stringify({ action: "subscribe", run_id: runId }));
      };
      socket.onmessage = (m) => {
        try {
          add([JSON.parse(m.data) as EventEnvelope]);
        } catch {
          /* ignore malformed frame */
        }
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        setStatus("closed");
        if (stopped.current) return;
        const delay = Math.min(1000 * 2 ** retry.current, 15000) + Math.random() * 300;
        retry.current += 1;
        setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped.current = true;
      ws.current?.close();
    };
  }, [runId, add]);

  return { status, events, lastEvent: events.length ? events[events.length - 1] : null };
}
