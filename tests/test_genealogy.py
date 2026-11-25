"""系図の柵。階層の決め方・間柄の四種と None・名義の引き方・今の席の選び方。"""
from __future__ import annotations

from direct_box import Person, build_tree, current_seat, person_of, relation, resolve_alias, root_of


def tree_of(agents, roster, seats):
    return build_tree(agents, roster, seats, root_alias="root", root_name="統括")


# ── 階層の決め方 ─────────────────────────────────────────────────────────────────

def test_root_is_level_zero(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    root = root_of(tree)
    assert root is tree["root"]
    assert (root.alias, root.name, root.level, root.parent) == ("root", "統括", 0, None)


def test_person_tags_make_level_one(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    a1, b1 = tree["a1-aaaaaaaaaa"], tree["b1-bbbbbbbbbb"]
    assert (a1.alias, a1.name, a1.engine, a1.level, a1.parent) == ("a", "A", "Claude Code", 1, "root")
    assert (b1.alias, b1.level, b1.parent) == ("b", 1, "root")      # from=bypass も、その人本人
    assert a1.key == "S-a" and a1.status == "idle"


def test_parent_label_makes_subordinates_even_if_listed_before_parent(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    c1, d1 = tree["c1-cccccccccc"], tree["d1-dddddddddd"]
    assert (c1.alias, c1.name, c1.level, c1.parent) == ("c1-cccccccccc", "素材づくり", 2, "a")
    assert (d1.alias, d1.level, d1.parent) == ("d1-dddddddddd", 3, "c1-cccccccccc")   # 孫は先頭に並んでいる
    assert c1.key == "K-c" and c1.status == "running"


def test_handoff_seat_is_the_same_person_as_its_parent(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    a2 = tree["a2-handoff0000"]
    assert (a2.alias, a2.name, a2.level, a2.parent) == ("a", "A", 1, "root")
    assert a2.status == "idle" and a2.updated == "2026-01-01T00:05:00Z"   # 席の状態は自分の物


def test_seats_without_a_tag_are_not_in_the_tree(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    assert "x1-untagged000" not in tree      # 名乗りでは載らない
    assert "y1-orphan00000" not in tree      # 親が系図に居ない
    assert set(tree) == {"root", "a1-aaaaaaaaaa", "b1-bbbbbbbbbb", "c1-cccccccccc", "d1-dddddddddd", "a2-handoff0000"}


def test_seat_registry_counts_as_that_person_without_labels(agents, roster, seats):
    agents.append({"id": "b9-nolabels000", "title": "B の新しい席", "provider": "codex", "status": "idle", "labels": {}})
    seats["b"] = {"agent_id": "b9-nolabels000"}
    tree = tree_of(agents, roster, seats)
    assert tree["b9-nolabels000"].alias == "b" and tree["b9-nolabels000"].level == 1


def test_person_tags_and_parent_label_are_configurable(roster):
    agents = [
        {"id": "p1-ppppppppp", "labels": {"from": "my-staff", "staff": "a"}},
        {"id": "q1-qqqqqqqqq", "labels": {"paseo.parent-agent-id": "p1-ppppppppp"}},
    ]
    default = build_tree(agents, roster, {})
    assert "p1-ppppppppp" not in default and "q1-qqqqqqqqq" not in default
    custom = build_tree(agents, roster, {}, person_tags=("my-staff",), parent_label="paseo.parent-agent-id")
    assert custom["p1-ppppppppp"].alias == "a"
    assert (custom["q1-qqqqqqqqq"].level, custom["q1-qqqqqqqqq"].parent) == (2, "a")


def test_person_of_resolves_alias_to_a_person(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    assert person_of("root", tree).level == 0
    assert person_of("a", tree).alias == "a"
    assert person_of("c1-cccccccccc", tree).level == 2
    assert person_of("nobody", tree) is None
    assert person_of("", tree) is None


# ── 間柄 ────────────────────────────────────────────────────────────────────────

def test_relation_four_kinds(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    root, a, b = tree["root"], tree["a1-aaaaaaaaaa"], tree["b1-bbbbbbbbbb"]
    c, d = tree["c1-cccccccccc"], tree["d1-dddddddddd"]
    assert relation(a, b) == "same_level"
    assert relation(c, a) == "one_up"
    assert relation(a, c) == "one_down"
    assert relation(root, a) == "one_down"
    assert relation(a, root) == "one_up"
    assert relation(c, root) == "two_up_to_root"


def test_relation_none_for_diagonal_skips_and_self(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    root, a, b = tree["root"], tree["a1-aaaaaaaaaa"], tree["b1-bbbbbbbbbb"]
    c, d, a2 = tree["c1-cccccccccc"], tree["d1-dddddddddd"], tree["a2-handoff0000"]
    assert relation(c, b) is None          # 斜め（よその部下）
    assert relation(b, c) is None
    assert relation(root, c) is None       # root から部下の部下へは送らない（指示は直属の上長から）
    assert relation(d, root) is None       # 三段上は通さない
    assert relation(d, a) is None          # 二段上でも root 以外は通さない
    assert relation(a, a2) is None         # 同じ人の別の席＝自分宛
    assert relation(a, a) is None
    assert relation(None, a) is None and relation(a, None) is None


# ── 名義の引き方 ─────────────────────────────────────────────────────────────────

def test_resolve_alias_by_name_alias_id_prefix_and_key(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    r = lambda w: resolve_alias(w, tree, seats, roster)   # noqa: E731
    assert r("root") == "root" and r("ROOT") == "root" and r("統括") == "root"
    assert r("a") == "a" and r("A") == "a" and r("B") == "b"
    assert r("c1-cccccccccc") == "c1-cccccccccc"
    assert r("c1-cccc") == "c1-cccccccccc"       # 7 文字以上の前方一致
    assert r("c1-ccc") is None                    # 6 文字では引かない（短すぎる）
    assert r("K-c") == "c1-cccccccccc"            # 札の key
    assert r("S-a") == "a"                        # 名簿の人の席の key は、その人
    assert r("a2-hand") == "a"                    # 引き継ぎの席は、その人
    assert r("a1-aaaaaaaaaa") == "a"
    assert r("") is None and r("  ") is None and r("nobody") is None


def test_resolve_alias_by_seat_registry_key(agents, roster, seats):
    tree = tree_of([], roster, {})                # 席が一本も無い日でも、控えの key から名義は引ける
    seats["b"] = {"agent_id": "", "key": "S-b-old"}
    assert resolve_alias("S-b-old", tree, seats, roster) == "b"


# ── 今の席 ──────────────────────────────────────────────────────────────────────

def test_current_seat_prefers_running_seat_over_registry(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    assert current_seat("a", tree, seats) == "a1-aaaaaaaaaa"            # 走っていなければ控えの席
    for a in agents:
        if a["id"] == "a2-handoff0000":
            a["status"] = "running"
    tree = tree_of(agents, roster, seats)
    assert current_seat("a", tree, seats) == "a2-handoff0000"           # 走っている席が先


def test_current_seat_picks_latest_updated_among_running(agents, roster, seats):
    agents.append({"id": "a3-newest00000", "title": "A の三つ目", "provider": "claude", "status": "initializing",
                   "updated": "2026-01-01T00:09:00Z", "labels": {"from": "staff", "staff": "a"}})
    for a in agents:
        if a["id"] == "a2-handoff0000":
            a["status"] = "running"
    tree = tree_of(agents, roster, seats)
    assert current_seat("a", tree, seats) == "a3-newest00000"


def test_current_seat_root_self_and_none(agents, roster, seats):
    tree = tree_of(agents, roster, seats)
    assert current_seat("root", tree, seats) == "root"
    assert current_seat("c1-cccccccccc", tree, seats) == "c1-cccccccccc"   # 部下は自分の席
    assert current_seat("nobody", tree, seats) is None
    roster["e"] = {"name": "E", "engine": ""}
    assert current_seat("e", tree_of(agents, roster, seats), seats) is None  # 名簿に居ても席が無ければ None


def test_person_is_frozen_value():
    p = Person("a", "A", "Claude Code", 1, "root")
    assert p.label() == "A（Claude Code）"
    assert Person("root", "統括").label() == "統括"
    try:
        p.alias = "b"   # type: ignore[misc]
    except Exception as e:  # noqa: BLE001
        assert "frozen" in type(e).__name__.lower() or "FrozenInstanceError" in repr(type(e))
    else:
        raise AssertionError("Person should be frozen")
