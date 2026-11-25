"""合札（seat token）の柵。差出人は名乗りではなく、器の印か合札で決める。"""
from __future__ import annotations

import json

from direct_box import SeatTokens


def test_issue_is_stable_per_agent(tmp_path):
    st = SeatTokens(str(tmp_path / "seats.json"))
    t1 = st.issue("agent-1")
    assert t1.startswith("ds-") and len(t1) == 3 + 16
    assert st.issue("agent-1") == t1            # 同じ席には同じ合札
    assert st.issue("agent-2") != t1            # 別の席には別の合札
    assert st.seat_of(t1) == "agent-1"


def test_issue_before_seat_exists_then_bind(tmp_path):
    st = SeatTokens(str(tmp_path / "seats.json"))
    t = st.issue()                              # 席が立つ前の合札
    assert st.seat_of(t) == ""
    st.bind(t, "agent-z")
    assert st.seat_of(t) == "agent-z"
    assert st.issue("agent-z") == t             # 結んだあとは、その席の合札として引ける


def test_unknown_or_empty_token_has_no_seat(tmp_path):
    st = SeatTokens(str(tmp_path / "seats.json"))
    assert st.seat_of("ds-nope") == ""
    assert st.seat_of("") == ""
    assert st.seat_of("  ") == ""


def test_sender_seat_prefers_env_mark_then_token(tmp_path):
    st = SeatTokens(str(tmp_path / "seats.json"))
    t = st.issue("agent-7")
    assert st.sender_seat("env-mark-1", t) == "env-mark-1"   # 器の印が先
    assert st.sender_seat("", t) == "agent-7"                # 無ければ合札
    assert st.sender_seat("", "ds-unknown") == ""            # どちらも無ければ空（送れない）
    assert st.sender_seat("", "") == ""


def test_file_is_plain_json_mapping(tmp_path):
    p = tmp_path / "deep" / "seats.json"
    st = SeatTokens(str(p))
    t = st.issue("agent-1")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    assert d == {t: "agent-1"}
    assert t in st.hint(t)
