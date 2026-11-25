"""柵の共通の世界。

    root（統括・階層 0）
    ├ a（階層 1・Claude Code）  席 a1（控え）・a2（[Handoff]＝同じ人）
    │   └ c1（階層 2・a の部下・走っている）
    │        └ d1（階層 3・c1 の部下）
    └ b（階層 1・Codex）        席 b1（控え）
    x1 … 札の無い席（系図に載らない）／ y1 … 親が系図に居ない席（載らない）
"""
from __future__ import annotations

import copy

import pytest

ROSTER = {"a": {"name": "A", "engine": "Claude Code"}, "b": {"name": "B", "engine": "Codex"}}
SEATS = {"a": {"agent_id": "a1-aaaaaaaaaa", "key": "S-a"}, "b": {"agent_id": "b1-bbbbbbbbbb", "key": "S-b"}}
AGENTS = [
    # 孫を先に並べる: 親が後ろに居ても固定点まで回して拾えることを見る
    {"id": "d1-dddddddddd", "title": "孫の作業", "provider": "codex", "status": "idle",
     "updated": "2026-01-01T00:04:00Z", "labels": {"parent-agent-id": "c1-cccccccccc"}},
    {"id": "a1-aaaaaaaaaa", "title": "A の席", "provider": "claude", "status": "idle",
     "updated": "2026-01-01T00:01:00Z", "labels": {"from": "staff", "staff": "a", "key": "S-a"}},
    {"id": "b1-bbbbbbbbbb", "title": "B の席", "provider": "codex", "status": "idle",
     "updated": "2026-01-01T00:02:00Z", "labels": {"from": "bypass", "staff": "b", "key": "S-b"}},
    {"id": "c1-cccccccccc", "title": "素材づくり", "provider": "codex", "status": "running",
     "updated": "2026-01-01T00:03:00Z", "labels": {"parent-agent-id": "a1-aaaaaaaaaa", "key": "K-c"}},
    {"id": "a2-handoff0000", "title": "[Handoff] A の続き", "provider": "claude", "status": "idle",
     "updated": "2026-01-01T00:05:00Z", "labels": {"parent-agent-id": "a1-aaaaaaaaaa"}},
    {"id": "x1-untagged000", "title": "所有者が直に立てた席", "provider": "claude", "status": "running",
     "updated": "2026-01-01T00:06:00Z", "labels": {}},
    {"id": "y1-orphan00000", "title": "親が系図に居ない席", "provider": "codex", "status": "idle",
     "updated": "2026-01-01T00:07:00Z", "labels": {"parent-agent-id": "zzz-unknown"}},
]


@pytest.fixture
def roster():
    return copy.deepcopy(ROSTER)


@pytest.fixture
def seats():
    return copy.deepcopy(SEATS)


@pytest.fixture
def agents():
    return copy.deepcopy(AGENTS)
