"""台帳の柵。atomic_replace・file_lock（スレッド・入れ子・timeout・別プロセス）・JsonlLedger の重複鍵と畳み。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from direct_box import JsonlLedger, atomic_replace, file_lock, fold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── atomic_replace ──────────────────────────────────────────────────────────────

def test_atomic_replace_writes_then_replaces_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "state.json"
    atomic_replace(str(p), "one\n")
    assert p.read_text(encoding="utf-8") == "one\n"
    atomic_replace(str(p), "two\n")
    assert p.read_text(encoding="utf-8") == "two\n"
    assert [x.name for x in tmp_path.iterdir()] == ["state.json"]     # 一時ファイルは残らない


def test_atomic_replace_creates_parent_dirs_and_accepts_bytes(tmp_path):
    p = tmp_path / "deep" / "er" / "blob.bin"
    atomic_replace(str(p), b"\x00\x01")
    assert p.read_bytes() == b"\x00\x01"


# ── file_lock ───────────────────────────────────────────────────────────────────

def test_file_lock_nested_in_same_thread_passes(tmp_path):
    p = str(tmp_path / "ledger.jsonl")
    with file_lock(p):
        with file_lock(p):          # 入れ子は通る
            with file_lock(p, timeout=0.1):
                pass
    with file_lock(p, timeout=0.1):  # 出たあとは、また取れる（深さが 0 に戻って錠が返っている）
        pass
    assert os.path.exists(p + ".lock")


def test_file_lock_times_out_when_another_thread_holds_it(tmp_path):
    p = str(tmp_path / "ledger.jsonl")
    held = threading.Event()
    release = threading.Event()

    def holder():
        with file_lock(p):
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder, daemon=True)
    t.start()
    assert held.wait(5)
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        with file_lock(p, timeout=0.2):
            pass
    assert time.monotonic() - t0 < 3
    release.set()
    t.join(5)
    with file_lock(p, timeout=1.0):   # 返されたら取れる
        pass


CHILD = """
import sys, time
sys.path.insert(0, sys.argv[1])
from direct_box.ledger import file_lock
with file_lock(sys.argv[2], 5.0):
    print("locked", flush=True)
    time.sleep(1.5)
print("released", flush=True)
"""


def test_file_lock_times_out_when_another_process_holds_it(tmp_path):
    p = str(tmp_path / "ledger.jsonl")
    child = subprocess.Popen([sys.executable, "-X", "utf8", "-c", CHILD, ROOT, p],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        line = child.stdout.readline().strip()
        assert line == "locked", (line, child.stderr.read())
        with pytest.raises(TimeoutError):          # 別プロセスが持っている間は取れない（黙って書かない）
            with file_lock(p, timeout=0.3):
                pass
        out, err = child.communicate(timeout=20)
        assert "released" in out, (out, err)
        with file_lock(p, timeout=2.0):            # 返されたら取れる
            pass
    finally:
        if child.poll() is None:
            child.kill()


def test_two_threads_appending_fifty_each_lose_no_lines(tmp_path):
    led = JsonlLedger(str(tmp_path / "ledger.jsonl"))

    def worker(name: str):
        for i in range(50):
            led.append({"kind": "sent", "key": f"{name}-{i}", "text": "x", "n": i, "who": name})

    ts = [threading.Thread(target=worker, args=(n,)) for n in ("t1", "t2")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    rows = led.read()
    assert len(rows) == 100
    assert {(r["who"], r["n"]) for r in rows} == {(n, i) for n in ("t1", "t2") for i in range(50)}
    with open(led.path, encoding="utf-8") as f:
        for line in f:
            json.loads(line)   # 行が混ざっていない


# ── JsonlLedger ─────────────────────────────────────────────────────────────────

def test_arrived_same_key_is_written_once(tmp_path):
    led = JsonlLedger(str(tmp_path / "box.jsonl"))
    assert led.arrived("M-1", "hello", sender="muse", origin="mail") is True
    assert led.arrived("M-1", "hello again", sender="muse", origin="mail") is False
    rows = led.read()
    assert len(rows) == 1 and rows[0]["kind"] == "arrived" and rows[0]["text"] == "hello"
    assert led.has("M-1") and led.has("M-1", "arrived") and not led.has("M-1", "replied")


def test_append_requires_kind_and_key(tmp_path):
    led = JsonlLedger(str(tmp_path / "box.jsonl"))
    with pytest.raises(ValueError):
        led.append({"key": "k"})
    with pytest.raises(ValueError):
        led.append({"kind": "sent"})
    with pytest.raises(ValueError):
        led.arrived("", "x")
    assert led.read() == []


def test_list_folds_by_key_newest_first_and_drops_headless(tmp_path):
    led = JsonlLedger(str(tmp_path / "box.jsonl"))
    led.arrived("K-1", "first", time="2026-01-01 10:00:00")
    led.replied("K-1", "ok", by="fio", time="2026-01-01 10:00:05")
    led.replied("K-1", "and more", by="fio", time="2026-01-01 10:00:09")
    led.arrived("K-2", "second", time="2026-01-01 10:01:00")
    led.replied("K-3", "reply without a head", by="fio")      # 頭の無い鍵は並べない
    out = led.list()
    assert [e["key"] for e in out] == ["K-2", "K-1"]
    assert out[1]["replies"] == [
        {"time": "2026-01-01 10:00:05", "kind": "replied", "by": "fio", "text": "ok"},
        {"time": "2026-01-01 10:00:09", "kind": "replied", "by": "fio", "text": "and more"},
    ]
    assert out[0]["replies"] == []
    assert led.list(limit=1)[0]["key"] == "K-2"
    assert len(led.list(limit=None)) == 2


def test_fold_ties_on_time_put_the_later_written_first():
    rows = [
        {"kind": "sent", "key": "A", "time": "2026-01-01 10:00:00"},
        {"kind": "sent", "key": "B", "time": "2026-01-01 10:00:00"},
        {"kind": "not_delivered", "key": "C", "time": "2026-01-01 10:00:00", "reason": "relation: no"},
        {"kind": "returned", "key": "A", "time": "2026-01-01 10:00:01", "result": "delivered"},
    ]
    out = fold(rows)
    assert [e["key"] for e in out] == ["C", "B", "A"]
    assert out[2]["replies"] == [{"time": "2026-01-01 10:00:01", "kind": "returned", "by": "", "text": "delivered"}]
    assert out[0]["reason"] == "relation: no"


def test_text_fields_are_truncated_to_text_limit(tmp_path):
    led = JsonlLedger(str(tmp_path / "box.jsonl"), text_limit=10)
    led.arrived("K", "x" * 50)
    led.replied("K", "y" * 50, by="me")
    rows = led.read()
    assert rows[0]["text"] == "x" * 10 and rows[1]["reply"] == "y" * 10


def test_read_skips_broken_and_keyless_lines(tmp_path):
    p = tmp_path / "box.jsonl"
    p.write_text('not json\n{"kind": "sent"}\n{"kind": "sent", "key": "ok", "time": "t"}\n\n', encoding="utf-8")
    led = JsonlLedger(str(p))
    assert [r["key"] for r in led.read()] == ["ok"]
    assert led.find("ok")["time"] == "t"
    assert led.find("missing") is None
