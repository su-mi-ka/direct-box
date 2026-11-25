"""DirectBox の柵。通る間柄は届き、通らない間柄は台帳に残り、返事は差出人の今の席へ戻る。"""
from __future__ import annotations

import re

import pytest

from direct_box import DirectBox, JsonlLedger, build_tree

KEY_RE = re.compile(r"^D-\d{8}-\d{6}-[0-9a-f]{4}$")


class World:
    """agents / seats を後から書き換えられる、系図の出所と偽の transport。"""

    def __init__(self, tmp_path, agents, roster, seats, **box_kwargs):
        self.agents, self.roster, self.seats = agents, roster, seats
        self.sent: list[tuple[str, str]] = []
        self.fail = False
        self.ledger = JsonlLedger(str(tmp_path / "direct_box.jsonl"), text_limit=box_kwargs.get("text_limit", 6000))
        self.box = DirectBox(self.ledger, self.transport, self.tree_provider, roster=roster, **box_kwargs)

    def tree_provider(self):
        return build_tree(self.agents, self.roster, self.seats, root_alias="root", root_name="統括"), self.seats

    def transport(self, seat_id: str, text: str) -> None:
        if self.fail:
            raise RuntimeError("daemon is down")
        self.sent.append((seat_id, text))


@pytest.fixture
def world(tmp_path, agents, roster, seats):
    return World(tmp_path, agents, roster, seats)


A1, B1, C1, D1 = "a1-aaaaaaaaaa", "b1-bbbbbbbbbb", "c1-cccccccccc", "d1-dddddddddd"


# ── 通る ────────────────────────────────────────────────────────────────────────

def test_same_level_is_delivered_with_tag(world):
    r = world.box.send(A1, "b", "設計の相談です。")
    assert r["ok"] and r["relation"] == "same_level" and r["to"] == "b" and r["seat"] == B1
    assert KEY_RE.match(r["key"])
    seat, text = world.sent[0]
    assert seat == B1
    head = text.splitlines()[0]
    assert head.startswith("〔direct box・from=A（Claude Code）・to=B（Codex）・relation=same_level・key=" + r["key"])
    assert "所有者の言葉ではない" in head
    assert "\n\n設計の相談です。\n\n" in text
    assert r["key"] in text.splitlines()[-1]           # 返し方の一行に鍵が載る
    rec = world.ledger.find(r["key"])
    assert rec["kind"] == "sent" and rec["result"] == "delivered" and rec["relation"] == "same_level"
    assert (rec["sender"], rec["sender_seat"], rec["to"], rec["seat"]) == ("a", A1, "b", B1)


def test_two_up_to_root_is_delivered_to_root_seat(world):
    r = world.box.send(C1, "root", "納品です。")
    assert r["ok"] and r["relation"] == "two_up_to_root" and r["seat"] == "root"
    assert world.sent[0][0] == "root" and "relation=two_up_to_root" in world.sent[0][1]


def test_one_up_and_one_down(world):
    up = world.box.send(C1, "a", "報告です。")
    down = world.box.send(A1, "c1-cccc", "次はこれを。")          # 短い id（7 文字以上）で部下を指す
    root_down = world.box.send("", "A", "方針です。", from_root=True)
    assert (up["relation"], up["seat"]) == ("one_up", A1)
    assert (down["relation"], down["seat"]) == ("one_down", C1)
    assert (root_down["relation"], root_down["seat"]) == ("one_down", A1)
    assert world.sent[2][1].startswith("〔direct box・from=統括・to=A（Claude Code）・relation=one_down")


def test_address_by_name(world):
    r = world.box.send(A1, "B", "名で呼ぶ。")
    assert r["ok"] and r["to"] == "b" and world.sent[0][0] == B1


def test_running_seat_is_preferred_over_registry(world):
    world.agents.append({"id": "b2-running0000", "title": "B の走っている席", "provider": "codex", "status": "running",
                         "updated": "2026-01-01T00:09:00Z", "labels": {"from": "bypass", "staff": "b"}})
    r = world.box.send(A1, "b", "今の席へ。")
    assert r["ok"] and r["seat"] == "b2-running0000" and world.sent[0][0] == "b2-running0000"


# ── 通らない（台帳には残る） ────────────────────────────────────────────────────────

def test_diagonal_is_not_delivered_but_recorded(world):
    r = world.box.send(C1, "b", "斜めの一通。")
    assert r["ok"] is False and r["reason"].startswith("relation:")
    assert world.sent == []
    rec = world.ledger.find(r["key"])
    assert rec["kind"] == "not_delivered" and rec["sender"] == "c1-cccccccccc" and rec["to"] == "b"
    assert rec["text"] == "斜めの一通。" and rec["reason"] == r["reason"]
    assert world.box.list()[0]["kind"] == "not_delivered"


def test_root_to_grandchild_is_refused(world):
    r = world.box.send("", C1, "部下の部下へ直に。", from_root=True)
    assert r["ok"] is False and r["reason"].startswith("relation:")
    assert world.sent == []


def test_great_grandchild_to_root_is_refused(world):
    r = world.box.send(D1, "root", "三段上へ。")
    assert r["ok"] is False and r["reason"].startswith("relation:")


def test_unknown_sender_seat_is_refused(world):
    r = world.box.send("nope-0000000", "b", "名乗りだけ。")
    assert r["ok"] is False and r["reason"].startswith("sender:")
    claimed = world.box.send("root", "b", "root を名乗る。")        # from_root 無しで root を名乗る
    assert claimed["ok"] is False and claimed["reason"].startswith("sender:")
    empty = world.box.send("", "b", "器の印なし。")
    assert empty["ok"] is False and empty["reason"].startswith("sender:")
    assert world.sent == []
    assert [e["kind"] for e in world.box.list()] == ["not_delivered"] * 3
    assert world.ledger.find(r["key"])["sender_seat"] == "nope-0000000"


def test_unknown_addressee_is_refused(world):
    r = world.box.send(A1, "ghost", "誰も居ない。")
    assert r["ok"] is False and r["reason"].startswith("addressee:")
    assert world.ledger.find(r["key"])["to"] == "ghost"


def test_roster_person_without_any_seat(world):
    world.roster["e"] = {"name": "E", "engine": ""}
    r = world.box.send(A1, "e", "席の無い人へ。")
    assert r["ok"] is False and r["reason"].startswith("seat:")      # 間柄は同じ階層で通るが、届け先が無い
    assert world.ledger.find(r["key"])["relation"] == "same_level"


def test_transport_failure_is_recorded_then_raised(world):
    world.fail = True
    with pytest.raises(RuntimeError):
        world.box.send(A1, "b", "落ちる。")
    rec = world.ledger.read()[-1]
    assert rec["kind"] == "not_delivered" and rec["reason"].startswith("transport: RuntimeError")
    assert rec["seat"] == B1


def test_empty_text_raises(world):
    with pytest.raises(ValueError):
        world.box.send(A1, "b", "   ")
    assert world.ledger.read() == []


# ── 返事 ────────────────────────────────────────────────────────────────────────

def test_reply_returns_to_the_sender_current_seat(world):
    r = world.box.send(C1, "root", "納品です。")
    back = world.box.reply(r["key"], "受け取りました。")
    assert back["ok"] and back["relation"] == "reply_from_root" and back["seat"] == C1 and back["to"] == C1
    seat, text = world.sent[-1]
    assert seat == C1
    assert text.startswith("〔direct box・from=統括・to=素材づくり（codex）・relation=reply_from_root・key=" + r["key"])
    assert f"（あなたが鍵 {r['key']} で送った一通への返事です）" in text
    kinds = [e["kind"] for e in world.ledger.read() if e["key"] == r["key"]]
    assert kinds == ["sent", "replied", "returned"]
    folded = world.box.list()[0]
    assert folded["key"] == r["key"] and [x["kind"] for x in folded["replies"]] == ["replied", "returned"]
    assert folded["replies"][0]["text"] == "受け取りました。" and folded["replies"][0]["by"] == "root"


def test_reply_follows_the_sender_to_a_new_seat(world):
    r = world.box.send(A1, "b", "相談です。")
    world.agents.append({"id": "a3-newseat0000", "title": "A の新しい席", "provider": "claude", "status": "running",
                         "updated": "2026-01-01T00:09:00Z", "labels": {"from": "staff", "staff": "a"}})
    back = world.box.reply(r["key"], "こちらで。")
    assert back["ok"] and back["seat"] == "a3-newseat0000" and back["relation"] == "same_level"
    assert world.sent[-1][0] == "a3-newseat0000"


def test_reply_unknown_key_raises(world):
    with pytest.raises(KeyError):
        world.box.reply("D-00000000-000000-0000", "誰にも。")


def test_reply_when_sender_left_is_recorded_not_raised(world):
    r = world.box.send(C1, "a", "報告です。")
    world.agents[:] = [a for a in world.agents if a["id"] not in (C1, D1)]
    back = world.box.reply(r["key"], "ありがとう。")
    assert back["ok"] is False and "no longer in the genealogy" in back["reason"]
    assert world.ledger.read()[-1]["kind"] == "returned" and world.ledger.read()[-1]["result"].startswith("not returned")


# ── 読む ────────────────────────────────────────────────────────────────────────

def test_recipients_lists_only_allowed_relations(world):
    by_alias = {x["alias"]: x for x in world.box.recipients(A1)}
    assert {k: v["relation"] for k, v in by_alias.items()} == {"b": "same_level", "root": "one_up", C1: "one_down"}
    assert by_alias["b"]["seat"] == B1
    c = {x["alias"]: x["relation"] for x in world.box.recipients(C1)}
    assert c == {"a": "one_up", D1: "one_down", "root": "two_up_to_root"}
    # 2026-11-21 アリア: 名簿に e を足す前に、統括から見える相手を確かめる（元は足した後に足す前の答えを見ていた）
    assert {x["alias"] for x in world.box.recipients("", from_root=True)} == {"a", "b"}
    world.roster["e"] = {"name": "E", "engine": ""}
    assert any(x["alias"] == "e" and x["seat"] == "" for x in world.box.recipients(A1, from_root=False))
    # 名簿に居て席の無い人は、統括からも並ぶ（フィオの 送れる相手 と同じ）
    assert {x["alias"] for x in world.box.recipients("", from_root=True)} == {"a", "b", "e"}
    assert world.box.recipients("root") == [] and world.box.recipients("nope") == []


def test_list_is_folded_newest_first(world):
    first = world.box.send(A1, "b", "一通目。")
    second = world.box.send(C1, "b", "二通目（通らない）。")
    out = world.box.list()
    assert [e["key"] for e in out] == [second["key"], first["key"]]
    assert [e["kind"] for e in out] == ["not_delivered", "sent"]
    assert world.box.list(limit=1)[0]["key"] == second["key"]


def test_long_text_is_truncated_in_ledger_but_transported_whole(tmp_path, agents, roster, seats):
    w = World(tmp_path, agents, roster, seats, text_limit=20)
    w.box.send(A1, "b", "x" * 100)
    assert w.ledger.read()[0]["text"] == "x" * 20
    assert "x" * 100 in w.sent[0][1]


def test_footer_can_be_dropped(tmp_path, agents, roster, seats):
    w = World(tmp_path, agents, roster, seats, footer=None)
    w.box.send(A1, "b", "本文だけ。")
    assert w.sent[0][1].endswith("\n\n本文だけ。")
