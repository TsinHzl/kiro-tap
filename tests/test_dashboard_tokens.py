"""Tests for session token summaries and per-turn breakdowns."""

from __future__ import annotations

import sqlite3

import pytest

from kiro_tap.dashboard import (
    _summarize_session,
    _turn_stats,
    list_trace_sessions,
    load_trace_session,
)
from kiro_tap.trace_store import get_trace_store, reset_trace_store


def _record(*, turn=1, usage=None, duration_ms=0, model="", timestamp="2026-10-29T00:00:00+00:00"):
    record = {"turn": turn, "duration_ms": duration_ms, "timestamp": timestamp}
    if model:
        record["request"] = {"body": {"model": model}}
    if usage is not None:
        record["response"] = {"body": {"usage": usage}}
    return record


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("KIROTAP_DB", str(tmp_path / "traces.sqlite3"))
    reset_trace_store()
    yield get_trace_store()
    reset_trace_store()


def _full_summary(session_id, records):
    return _summarize_session(
        session_id=session_id,
        date_key="2026-10-29",
        legacy_rel_path=None,
        records=records,
        manifest_entry={"client": "", "proxy_mode": ""},
        status="active",
        started_at="",
        updated_at="",
        is_current=True,
        record_count=len(records),
    )


def test_turn_stats_extracts_fields() -> None:
    stats = _turn_stats(
        _record(
            turn=2,
            usage={
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 2,
                "thinking_tokens": 1,
            },
            duration_ms=100,
            model="claude-sonnet-5",
        )
    )
    assert stats["turn"] == 2
    assert stats["input_tokens"] == 10
    assert stats["output_tokens"] == 5
    assert stats["cache_read_tokens"] == 3
    assert stats["cache_create_tokens"] == 2
    assert stats["thinking_tokens"] == 1
    assert stats["duration_ms"] == 100
    assert stats["model"] == "claude-sonnet-5"


@pytest.mark.parametrize("turn", ["3", 1.5, None, True])
def test_turn_stats_non_integer_turn(turn) -> None:
    record = _record(turn=turn)
    if turn is None:
        record.pop("turn")
    assert _turn_stats(record)["turn"] is None


def test_summary_includes_thinking_and_breakdown(store) -> None:
    session_id = store.create_session()
    store.append_record(session_id, _record(turn=1, usage={"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 2}))
    store.append_record(session_id, _record(turn=2, usage={"input_tokens": 20, "output_tokens": 7, "thinking_tokens": 1}))
    summary = load_trace_session(session_id)["session"]
    assert summary["input_tokens"] == 30
    assert summary["output_tokens"] == 12
    assert summary["thinking_tokens"] == 3
    assert summary["total_tokens"] == 42
    assert [entry["turn"] for entry in summary["turn_breakdown"]] == [1, 2]
    assert summary["turn_count"] == 2


def test_incremental_matches_full_summary(store) -> None:
    session_id = store.create_session()
    records = [
        _record(turn=1, usage={"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 2}, duration_ms=100, model="a"),
        _record(turn=2, usage={"input_tokens": 20, "output_tokens": 7}, duration_ms=250, model="b"),
        _record(turn=1, usage={"input_tokens": 4}, duration_ms=30),
    ]
    for record in records:
        store.append_record(session_id, record)
    incremental = load_trace_session(session_id)["session"]
    full = _full_summary(session_id, records)
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_create_tokens",
        "thinking_tokens",
        "total_tokens",
        "turn_count",
        "turn_breakdown",
    ):
        assert incremental[key] == full[key], key


def test_thinking_not_in_total(store) -> None:
    session_id = store.create_session()
    store.append_record(session_id, _record(turn=1, usage={"input_tokens": 100, "output_tokens": 50, "thinking_tokens": 20}))
    summary = load_trace_session(session_id)["session"]
    assert summary["total_tokens"] == 150
    assert summary["thinking_tokens"] == 20


def test_same_turn_records_merge(store) -> None:
    session_id = store.create_session()
    store.append_record(session_id, _record(turn=1, usage={"input_tokens": 10}, duration_ms=100, model="claude-sonnet-5"))
    store.append_record(session_id, _record(turn=1, usage={"input_tokens": 20}, duration_ms=250, model="claude-opus-5"))
    store.append_record(session_id, _record(turn=1, duration_ms=0, model=""))
    entry = load_trace_session(session_id)["session"]["turn_breakdown"][0]
    assert entry["input_tokens"] == 30
    assert entry["record_count"] == 3
    assert entry["duration_ms"] == 350
    assert entry["model"] == "claude-opus-5"


def test_null_turn_grouped_last(store) -> None:
    session_id = store.create_session()
    store.append_record(session_id, _record(turn=2))
    store.append_record(session_id, _record(turn=1))
    record_no_turn = _record()
    record_no_turn.pop("turn")
    store.append_record(session_id, record_no_turn)
    store.append_record(session_id, _record(turn="3"))
    store.append_record(session_id, _record(turn=1.5))
    breakdown = load_trace_session(session_id)["session"]["turn_breakdown"]
    assert [entry["turn"] for entry in breakdown] == [1, 2, None]
    assert breakdown[-1]["record_count"] == 3


def test_turn_count_equals_breakdown_len(store) -> None:
    session_id = store.create_session()
    for _ in range(3):
        store.append_record(session_id, _record(turn=1))
    summary = load_trace_session(session_id)["session"]
    assert summary["record_count"] == 3
    assert summary["turn_count"] == 1


def test_invalid_token_types_count_as_zero(store) -> None:
    session_id = store.create_session()
    store.append_record(
        session_id,
        _record(
            turn=1,
            usage={
                "input_tokens": "100",
                "output_tokens": 5.5,
                "cache_read_input_tokens": None,
                "cache_creation_input_tokens": "1.5",
                "thinking_tokens": True,
            },
            duration_ms="88",
        ),
    )
    summary = load_trace_session(session_id)["session"]
    for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_create_tokens", "thinking_tokens"):
        assert summary[key] == 0, key
    assert summary["duration_ms"] == 0


def test_legacy_summary_defaults(store) -> None:
    session_id = store.create_session()
    store.append_record(session_id, _record(turn=1, usage={"input_tokens": 10}))
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET summary_json = ?, status = 'complete' WHERE id = ?",
            ('{"id": "' + session_id + '", "record_count": 1}', session_id),
        )
        conn.commit()
    summary = load_trace_session(session_id)["session"]
    assert summary["thinking_tokens"] == 0
    assert summary["turn_count"] == 1


def test_lazy_backfill_only_on_detail_path(store, monkeypatch) -> None:
    session_id = store.create_session()
    store.append_record(session_id, _record(turn=1, usage={"input_tokens": 10, "thinking_tokens": 3}))
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET summary_json = ?, status = 'complete' WHERE id = ?",
            ('{"id": "' + session_id + '", "record_count": 1, "turn_count": 0}', session_id),
        )
        conn.commit()

    calls = []
    original = store.store_summary

    def counting(session_id_, summary_):
        calls.append(session_id_)
        return original(session_id_, summary_)

    monkeypatch.setattr(store, "store_summary", counting)

    listed = list_trace_sessions()[0]
    assert listed["turn_breakdown"] == []
    assert calls == []

    detailed = load_trace_session(session_id)["session"]
    assert detailed["thinking_tokens"] == 3
    assert detailed["turn_breakdown"][0]["turn"] == 1
    assert len(calls) == 1

    load_trace_session(session_id)
    assert len(calls) == 1


def test_empty_session_no_scan(store, monkeypatch) -> None:
    session_id = store.create_session()
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE sessions SET summary_json = ?, status = 'complete' WHERE id = ?",
            ('{"id": "' + session_id + '", "record_count": 0}', session_id),
        )
        conn.commit()
    calls = []
    monkeypatch.setattr(store, "store_summary", lambda *a: calls.append(a))
    summary = load_trace_session(session_id)["session"]
    assert summary["turn_breakdown"] == []
    assert summary["thinking_tokens"] == 0
    assert calls == []

def test_viewer_stub_meta_thinking() -> None:
    import json as _json

    from kiro_tap.viewer import _extract_metadata

    record = {
        "turn": 1,
        "request": {"method": "POST", "path": "/v1/messages", "body": {"model": "claude-sonnet-5"}},
        "response": {
            "status": 200,
            "body": {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "output_tokens_details": {"thinking_tokens": 7},
                }
            },
        },
    }
    meta = _extract_metadata(_json.dumps(record))
    assert meta is not None
    assert meta["thinking_tokens"] == 7
