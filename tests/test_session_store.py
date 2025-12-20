from __future__ import annotations

from typing import cast

from yathaavat.core.session import SessionSnapshot, SessionState, SessionStore


def test_session_store_subscribe_and_unsubscribe() -> None:
    store = SessionStore()
    seen: list[SessionState] = []

    def listener(snapshot: SessionSnapshot) -> None:
        seen.append(snapshot.state)

    unsubscribe = store.subscribe(listener)
    assert seen[-1] == SessionState.DISCONNECTED

    store.update(state=SessionState.RUNNING)
    assert cast(SessionState, seen[-1]) == SessionState.RUNNING

    unsubscribe()
    store.update(state=SessionState.PAUSED)
    assert cast(SessionState, seen[-1]) == SessionState.RUNNING


def test_session_store_append_transcript_truncates() -> None:
    store = SessionStore()
    for i in range(10):
        store.append_transcript(f"line {i}", max_lines=5)
    assert len(store.snapshot().transcript) == 5
    assert store.snapshot().transcript[0] == "line 5"
