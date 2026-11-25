"""系図 — 席（エージェント）の札から「誰が誰の下に居るか」を組む純粋関数。

考え方:
  - 人（Person）と席（seat・エージェントの id）は別物。同じ人の席は何本あっても同じ名義（alias）。
    宛先は名義で引き、届ける時だけ「今の席」に落とす。だから席が替わっても届く。
  - 階層は札（labels）から決める。
      root（統括）                      … 階層 0。系図に一人だけ。
      labels.from が person_tags のどれか  … その席は名簿（roster）の staff=<alias> の人本人。階層 1・親は root。
        （または seats（席の控え）に今の席として載っている席）
      labels[parent_label] = <親の席>     … その席の部下。階層 = 親 + 1・親 = 親の名義。
      題が "[Handoff]" で始まる席          … 引き継ぎ。親の席と同じ人（階層も名義も同じ）。
      札から人を決められない席             … 系図に載せない（名乗りでは載らない）。
    親が後ろに並んでいても拾えるように、変わらなくなるまで回す（固定点）。
  - 通してよい間柄（relation）は四つだけ。斜め（よその部下）や段飛ばしは None。
      same_level      同じ階層（連絡・相談・共有。指示ではない）
      one_up          直属の上長へ（報告・相談）
      one_down        直属の部下へ（指示は上から下へだけ）
      two_up_to_root  階層 2 から root へだけ（納品・報告）。root から部下の部下へは送らない。
"""
from __future__ import annotations

from dataclasses import dataclass, replace

RUNNING: tuple[str, ...] = ("running", "initializing")
RELATIONS: tuple[str, ...] = ("same_level", "one_up", "one_down", "two_up_to_root")
RELATION_MEANING: dict[str, str] = {
    "same_level": "同じ階層からの連絡・相談・共有。指示ではない",
    "one_up": "直属の部下からの報告・相談",
    "one_down": "直属の上長から",
    "two_up_to_root": "部下の部下からの納品・報告。指示ではない",
    "reply_from_root": "root からの、納品・報告への返事。指示ではない",
}
#: 返事に付ける間柄（元の一通の間柄を裏返す）。返事は間柄の検査を通さない——元の一通が通ったのだから、戻りは通す。
REPLY_RELATION: dict[str, str] = {
    "same_level": "same_level", "one_up": "one_down", "one_down": "one_up", "two_up_to_root": "reply_from_root",
}
HANDOFF_PREFIX = "[Handoff]"


@dataclass(frozen=True)
class Person:
    """系図の一人。alias が名義（人を指す鍵）、key / status / updated はその席の物。"""
    alias: str
    name: str
    engine: str = ""
    level: int = 1
    parent: str | None = None
    key: str = ""
    status: str = ""
    updated: str = ""

    def label(self) -> str:
        return f"{self.name}（{self.engine}）" if self.engine else self.name


def person_of_labels(labels: dict | None, roster: dict, person_tags: tuple[str, ...] = ("staff", "bypass"),
                     person_label: str = "staff") -> str:
    """札から、その席が名簿のどの人の席かを返す（その人の席でなければ空）。判断口はここ一つ。"""
    lb = labels if isinstance(labels, dict) else {}
    alias = str(lb.get(person_label) or "")
    if lb.get("from") in person_tags and alias in (roster or {}):
        return alias
    return ""


def build_tree(agents: list[dict], roster: dict, seats: dict | None = None, *, root_alias: str = "root",
               root_name: str = "", root_engine: str = "", person_tags: tuple[str, ...] = ("staff", "bypass"),
               person_label: str = "staff", parent_label: str = "parent-agent-id") -> dict[str, Person]:
    """席の id → Person。root は root_alias の鍵で載る。純粋関数。

    agents … 席の一覧。各要素は {"id", "title", "provider"（器）, "status", "updated", "labels": {...}}。
    roster … 名義 → {"name", "engine"}。階層 1 の人の名簿。
    seats  … 名義 → {"agent_id", ...}。その人の今の席の控え（在れば札より先に見る）。"""
    roster = roster or {}
    seats = seats or {}
    tree: dict[str, Person] = {root_alias: Person(root_alias, root_name or root_alias, root_engine, 0, None)}
    by_id = {a.get("id"): a for a in agents or [] if isinstance(a, dict) and a.get("id")}
    seat_owner = {str((v or {}).get("agent_id") or ""): alias for alias, v in seats.items() if alias in roster}

    def person(alias: str) -> Person:
        x = roster.get(alias) or {}
        return Person(alias, x.get("name") or alias, x.get("engine", ""), 1, root_alias)

    for aid, a in by_id.items():
        if aid in seat_owner:
            tree[aid] = person(seat_owner[aid])
            continue
        alias = person_of_labels(a.get("labels"), roster, person_tags, person_label)
        if alias:
            tree[aid] = person(alias)
    changed = True
    while changed:   # 親の印で辿る部下・孫・引き継ぎ。親が先に載っていない時のため、変わらなくなるまで回す
        changed = False
        for aid, a in by_id.items():
            if aid in tree:
                continue
            labels = a.get("labels") if isinstance(a.get("labels"), dict) else {}
            p = labels.get(parent_label)
            if not p or p not in tree:
                continue
            parent = tree[p]
            if str(a.get("title") or "").startswith(HANDOFF_PREFIX):
                tree[aid] = replace(parent, key="", status="", updated="")
            else:
                tree[aid] = Person(aid, str(a.get("title") or aid[:7]), str(a.get("provider") or a.get("engine") or ""),
                                   parent.level + 1, parent.alias)
            changed = True
    for aid in list(tree):   # 札の key でも引けるように、席ごとに持たせる。状態と更新は「今の席」を選ぶため
        if aid == root_alias:
            continue
        a = by_id.get(aid) or {}
        labels = a.get("labels") if isinstance(a.get("labels"), dict) else {}
        tree[aid] = replace(tree[aid], key=str(labels.get("key") or ""), status=str(a.get("status") or "").lower(),
                            updated=str(a.get("updated") or a.get("updatedAt") or ""))
    return tree


def root_of(tree: dict[str, Person]) -> Person | None:
    return next((p for p in tree.values() if p.level == 0 and p.parent is None), None)


def person_of(alias: str, tree: dict[str, Person]) -> Person | None:
    """名義から人を引く。root と部下は自分の鍵、名簿の人はどれかの席の Person。"""
    if not alias:
        return None
    if alias in tree:
        return tree[alias]
    return next((p for p in tree.values() if p.alias == alias), None)


def resolve_alias(addr: str, tree: dict[str, Person], seats: dict | None = None, roster: dict | None = None) -> str | None:
    """宛先の書き方（root の名義か名・名簿の名義か名・席の id・7 文字以上の前方一致・札の key）から名義を引く。"""
    w = (addr or "").strip()
    if not w:
        return None
    root = root_of(tree)
    if root is not None and (w.lower() == root.alias.lower() or w == root.name):
        return root.alias
    for alias, x in (roster or {}).items():
        if w.lower() == alias.lower() or w == (x or {}).get("name"):
            return alias
    for aid, p in tree.items():
        if root is not None and aid == root.alias:
            continue
        if aid == w or (len(w) >= 7 and aid.startswith(w)) or (p.key and p.key == w):
            return p.alias
    for alias, v in (seats or {}).items():
        if (v or {}).get("key") == w:
            return alias
    return None


def current_seat(alias: str, tree: dict[str, Person], seats: dict | None = None) -> str | None:
    """その名義の今の席。走っている席（更新が最新）→ 席の控え → 自分の席 → None。

    用事の最中の席に合流させ、止まっている別の席を起こさないため、走っている席を控えより先に見る。"""
    root = root_of(tree)
    if root is not None and alias == root.alias:
        return root.alias
    running = sorted((p.updated, aid) for aid, p in tree.items()
                     if (root is None or aid != root.alias) and p.alias == alias and p.status in RUNNING)
    if running:
        return running[-1][1]
    v = (seats or {}).get(alias) or {}
    if v.get("agent_id"):
        return str(v["agent_id"])
    if alias in tree:
        return alias
    return None


def relation(sender: Person | None, receiver: Person | None) -> str | None:
    """通してよい間柄の名。通さないなら None（自分宛・斜め・段飛ばし）。"""
    if sender is None or receiver is None or sender.alias == receiver.alias:
        return None
    if sender.level == receiver.level:
        return "same_level"
    if sender.parent == receiver.alias:
        return "one_up"
    if receiver.parent == sender.alias:
        return "one_down"
    if receiver.level == 0 and receiver.parent is None and sender.level == 2:
        return "two_up_to_root"
    return None
