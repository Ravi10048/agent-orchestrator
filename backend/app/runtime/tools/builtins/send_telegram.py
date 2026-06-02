"""Send a message to the current Telegram chat (channel-aware via ctx.chat_id).
Intended for workflow nodes (e.g. the Notifier agent) — the channel registry is
imported lazily so this module has no hard dependency on LLD 07."""
from app.runtime.tools.registry import builtin


@builtin("send_telegram")
async def send_telegram(args, ctx):
    from app.channels import get_channel

    # target: explicit arg wins, else the current chat (1:1) / the run's chat_id (workflow input)
    target = args.get("chat_id") or ctx.chat_id
    if not target:
        raise ValueError("send_telegram needs a chat_id (pass it in the run input or as a tool arg)")
    await get_channel("telegram").send(target, args["text"])
    return {"sent": True, "chat_id": target}
