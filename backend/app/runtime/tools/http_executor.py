"""Generic HTTP tool execution — user-defined REST calls with URL templates, auth, and
body mapping. Secrets come from env (token_env/value_env), never stored plaintext (LLD 03)."""
import os
import re

import httpx

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


async def http_execute(tool, args: dict, ctx, timeout: float) -> dict:
    url = _render(tool.endpoint or "", args)  # "{placeholders}" filled from args
    method = (tool.http_method or "GET").upper()
    headers = dict(tool.headers or {})
    _apply_auth(headers, tool.auth or {})  # bearer/header — secrets via env
    json_body = _render_body(tool.body_template, args) if method in ("POST", "PUT", "PATCH") else None
    params = _leftover_args(tool, args) if method == "GET" else None
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.request(method, url, headers=headers, params=params, json=json_body)
    return {"status": r.status_code, "ok": r.is_success, "body": _safe_body(r)}


def _render(template: str, args: dict) -> str:
    return _PLACEHOLDER.sub(lambda m: str(args.get(m.group(1), m.group(0))), template)


def _used_keys(template: str) -> set[str]:
    return set(_PLACEHOLDER.findall(template or ""))


def _leftover_args(tool, args: dict) -> dict:
    used = _used_keys(tool.endpoint or "")
    return {k: v for k, v in args.items() if k not in used}


def _render_body(body_template, args: dict) -> dict:
    if not body_template:
        return dict(args)  # no template → send the args as the JSON body

    def render(v):
        if isinstance(v, str):
            return _render(v, args)
        if isinstance(v, dict):
            return {k: render(x) for k, x in v.items()}
        if isinstance(v, list):
            return [render(x) for x in v]
        return v

    return {k: render(v) for k, v in body_template.items()}


def _apply_auth(headers: dict, auth: dict) -> None:
    t = auth.get("type")
    if t == "bearer":
        token = os.getenv(auth["token_env"]) if auth.get("token_env") else auth.get("token")
        headers["Authorization"] = f"Bearer {token}"
    elif t == "header":
        val = os.getenv(auth["value_env"]) if auth.get("value_env") else auth.get("value")
        headers[auth["name"]] = val
    # type == "none"/missing → no auth ; "basic" → httpx BasicAuth (omitted for brevity)


def _safe_body(r: httpx.Response):
    try:
        return r.json()
    except Exception:
        return (r.text or "")[:4000]  # truncated text if not JSON
