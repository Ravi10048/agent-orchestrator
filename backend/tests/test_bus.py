"""LLD 04 — Message Bus tests."""
from app.runtime.bus import BusMessage, new_bus


def _msg(i, frm="A", to="B", content="x"):
    return BusMessage(id=str(i), from_agent=frm, to_agent=to, content=content)


async def test_publish_receive_roundtrip():
    bus = new_bus()
    await bus.publish(_msg(1, content="hello"))
    got = await bus.receive("B", timeout=0.5)
    assert got is not None
    assert got.content == "hello" and got.from_agent == "A"


async def test_broadcast_excludes_sender():
    bus = new_bus()
    for a in ("A", "B", "C"):
        bus.has_pending(a)  # materialize inboxes so broadcast can target them
    await bus.publish(BusMessage(id="1", from_agent="A", to_agent="*", content="hi"))
    assert bus.has_pending("B") and bus.has_pending("C")
    assert not bus.has_pending("A")  # sender excluded
    assert bus.drain("B")[0].content == "hi"
    assert bus.drain("C")[0].content == "hi"


async def test_drain_empties_queue_and_has_pending():
    bus = new_bus()
    assert bus.has_pending("B") is False
    await bus.publish(_msg(1))
    await bus.publish(_msg(2))
    assert bus.has_pending("B") is True
    drained = bus.drain("B")
    assert [m.id for m in drained] == ["1", "2"]
    assert bus.has_pending("B") is False
    assert bus.drain("B") == []


async def test_receive_timeout_returns_none():
    bus = new_bus()
    assert await bus.receive("Z", timeout=0.05) is None


async def test_fifo_ordering():
    bus = new_bus()
    for i in range(5):
        await bus.publish(_msg(i, content=str(i)))
    out = [(await bus.receive("B", timeout=0.2)).content for _ in range(5)]
    assert out == ["0", "1", "2", "3", "4"]
