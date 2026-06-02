"""Fetch the text of a web page (truncated)."""
import httpx

from app.runtime.tools.registry import builtin


@builtin("web_fetch")
async def web_fetch(args, ctx):
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(args["url"])
    return {"status": r.status_code, "text": r.text[:4000]}
