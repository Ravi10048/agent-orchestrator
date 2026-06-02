"""Seed DEMO RUNS so the UI is populated out of the box (Runs / Graph / Agents tab).

Unlike `python -m app.seed` (which seeds tools/agents/templates), this drives the RUNNING API to
instantiate + execute the seeded templates a few times, producing real runs to explore in the UI:

  • Support Router ×3  — one billing, one tech, one sales query → shows the Supervisor routing
                         ANY request to the right specialist (the `n`/`r` decision in the Graph view).
  • Collaborative Brief — Coordinator `send_message`s an Editor peer → populates the Agents tab.
  • Research → Report → Notify — the pipeline + feedback-loop template.

Idempotent: if any non-template runs already exist, it does nothing (so re-running won't pile up).
Key-gated: needs a live LLM key (the runs call the model); skips with a clear message if absent.

Usage:  make demo            (server must be running on :8000)
        BASE_URL=http://host:8000/api python scripts/seed_demo.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://localhost:8000/api")


def req(method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.load(resp)


def items(d):
    return d.get("items", d) if isinstance(d, dict) else d


# representative inputs per template (the Support Router gets 3, to show routing variety)
DEMO = [
    ("Support Router", "I was charged twice for my subscription this month and need a refund."),
    ("Support Router", "Our production API returns 502 Bad Gateway intermittently after the last deploy."),
    ("Support Router", "What's the difference between the Pro and Enterprise plans, and can I get a trial?"),
    ("Collaborative Brief", "the impact of AI on developer productivity"),
    ("Research → Report → Notify", "the rise of small language models in 2025"),
]


def main() -> int:
    try:
        health = req("GET", "/health", timeout=5)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"✗ API not reachable at {BASE} ({e}). Start the backend first (uvicorn / docker compose up).")
        return 1
    if not health.get("llm_key_present"):
        print("✗ No LLM key present (set GROQ_API_KEY in backend/.env). Demo runs need the model — skipping.")
        return 0

    existing = items(req("GET", "/runs"))
    if existing:
        print(f"✓ {len(existing)} run(s) already exist — demo data is present; nothing to do (idempotent).")
        return 0

    templates = {w["name"]: w for w in items(req("GET", "/workflows?is_template=true"))}
    print(f"Seeding {len(DEMO)} demo runs into the UI…\n")
    for name, text in DEMO:
        tmpl = templates.get(name)
        if not tmpl:
            print(f"  ! template {name!r} not found — run `make seed` first; skipping")
            continue
        wf = req("POST", f"/workflows/{tmpl['id']}/instantiate", {"name": f"{name} (demo)"})
        run = req("POST", "/runs", {"workflow_id": wf["id"], "input": {"text": text}, "trigger": "manual"})
        rid = run["id"]
        final = None
        for _ in range(60):
            r = req("GET", f"/runs/{rid}")
            if r["status"] in ("completed", "failed"):
                final = r
                break
            time.sleep(2)
        final = final or req("GET", f"/runs/{rid}")
        print(f"  ✓ run #{rid:<3} {name:<28} {final['status']:<10} {final['total_tokens']} tok  — {text[:48]}…")

    print("\nDone. Open the UI → Runs (and click Graph on a Support Router run to see the routing).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
