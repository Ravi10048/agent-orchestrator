"""Telegram adapter — long-poll (getUpdates), no public webhook, fully local (LLD 07).

Delivery: the offset advances AFTER an update is handled, inside `finally` — so a poison
update can't wedge the loop, and (since the offset is in-memory) a process restart makes
Telegram redeliver recent updates (at-least-once across restarts). Survives network
errors with exponential backoff + auto-reconnect; clears any webhook + backs off on 409.
"""
import asyncio
import logging
import re

import httpx

from app.channels.base import Channel, ChannelNotConfigured, InboundMessage

log = logging.getLogger("channels.telegram")
_API = "https://api.telegram.org/bot{token}/{method}"
# the bot token is embedded in every request URL; httpx errors echo that URL back, so scrub it
# before it can reach a tool error / RunEvent payload / the live monitor / logs.
_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


def _url(token: str, method: str) -> str:
    return _API.format(token=token, method=method)


def _scrub(text: str, token: str | None = None) -> str:
    """Strip the bot token from any string (exact value + the generic bot<id>:<secret> URL form)."""
    if token:
        text = text.replace(token, "<redacted>")
    return _TOKEN_RE.sub("bot<redacted>", text)


def _split(text: str, limit: int) -> list[str]:
    text = text or ""
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, token, dispatcher, *, poll_timeout: int = 30, http_timeout: float = 40.0):
        self._token = token
        self._dispatch = dispatcher
        self._poll_timeout = poll_timeout
        self._http_timeout = http_timeout  # MUST exceed poll_timeout
        self._offset: int | None = None
        self._task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._client = httpx.AsyncClient(timeout=self._http_timeout)
        await self._delete_webhook()  # clear any webhook so getUpdates won't 409
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="telegram-poll")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("telegram poll task error during stop")
            self._task = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send(self, chat_id, text) -> dict:
        if self._client is None:  # registered but not started (or stopped) → clear, catchable error
            raise ChannelNotConfigured(self.name)
        result: dict = {}
        try:
            for chunk in _split(text, 4096):  # Telegram hard cap
                r = await self._client.post(_url(self._token, "sendMessage"),
                                            json={"chat_id": chat_id, "text": chunk})
                r.raise_for_status()
                result = r.json()
        except httpx.HTTPError as e:
            # re-raise WITHOUT the token-bearing URL — this error becomes a tool result / RunEvent
            raise RuntimeError(f"telegram sendMessage failed: {_scrub(str(e), self._token)}") from None
        return result

    async def handle_update(self, update) -> InboundMessage | None:
        msg = update.get("message")
        if not msg or not msg.get("text"):
            return None  # skip edits/non-text/callbacks
        frm = msg.get("from", {})
        if frm.get("is_bot"):
            return None
        return InboundMessage(
            "telegram", str(msg["chat"]["id"]), msg["text"],
            frm.get("first_name") or frm.get("username") or "", update,
        )

    async def _delete_webhook(self) -> None:
        try:
            await self._client.get(_url(self._token, "deleteWebhook"))
        except Exception:
            log.warning("deleteWebhook failed (continuing)")

    async def _process_updates(self, updates) -> None:
        for u in updates:
            inb = await self.handle_update(u)
            try:
                if inb:
                    await self._dispatch(inb)  # dispatcher persists inbound first
            except Exception:
                log.exception("update %s failed; skipping", u.get("update_id"))
            finally:
                uid = u.get("update_id")
                if uid is not None:  # guard: a malformed update must not raise here and wedge the loop
                    self._offset = uid + 1  # advance AFTER handling

    async def _poll_loop(self) -> None:
        backoff = 1.0
        while self._running:
            try:
                params = {"timeout": self._poll_timeout, "allowed_updates": ["message"]}
                if self._offset is not None:
                    params["offset"] = self._offset  # ACK cursor
                r = await self._client.get(_url(self._token, "getUpdates"), params=params)
                if r.status_code == 409:  # webhook set OR a 2nd poller (uvicorn --reload)
                    log.error("getUpdates 409 — deleteWebhook / run a single poller")
                    await asyncio.sleep(5)
                    continue
                r.raise_for_status()
                body = r.json()
                if not body.get("ok"):
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)  # escalate on API-level errors too
                    continue
                backoff = 1.0
                await self._process_updates(body["result"])
            except asyncio.CancelledError:
                raise
            except (httpx.TimeoutException, httpx.TransportError):
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)  # network blip → backoff + reconnect
            except httpx.HTTPError as e:  # incl. HTTPStatusError — its message carries the token URL
                log.error("getUpdates failed: %s", _scrub(str(e), self._token))  # scrubbed, no traceback
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            except Exception:
                log.exception("poll loop error")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
