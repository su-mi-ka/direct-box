"""DirectBox — 名前で届ける手紙箱の本体。

send(sender_seat, to, text)
  1. 差出人は名乗りではなく席（sender_seat）で決める。系図に居ない席からは送れない（台帳には残す）。
  2. 宛先（to）は名義・名・席の id・短い id・札の key のどれでもよい。名義に引いてから今の席に落とす。
  3. 間柄（relation）が None なら送らない。送らなかった一通も台帳に kind="not_delivered" と理由で残す。
  4. 通るなら、頭に札（tag）を付けて transport(seat_id, text) へ渡す。札は出所の明示——
     「〔direct box・from=…・to=…・relation=…・key=…。所有者の言葉ではない〕」。
     受け取った席が、これを所有者（人間）の指示と取り違えないためにある。
reply(key, text)
  元の一通の受け手から、差出人の「今の席」へ同じ形で戻す。間柄の検査は通さない（元の一通が通っている）。
list(limit)
  台帳を鍵ごとに畳んで新しい順。

transport と系図の出所は注入する。箱は「誰に・何を・通ったか」を決めるだけで、届ける手段は持たない。
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from .genealogy import (
    RELATION_MEANING,
    RELATIONS,
    REPLY_RELATION,
    Person,
    current_seat,
    person_of,
    relation,
    resolve_alias,
    root_of,
)
from .ledger import JsonlLedger, now_text

Transport = Callable[[str, str], None]
TreeProvider = Callable[[], tuple[dict[str, Person], dict]]

_KEY_TIME_FORMAT = "%Y%m%d-%H%M%S"


def make_key() -> str:
    """一通の鍵。D-YYYYMMDD-HHMMSS-xxxx（xxxx は乱数の 16 進 4 桁）。"""
    return f"D-{time.strftime(_KEY_TIME_FORMAT)}-{uuid.uuid4().hex[:4]}"


def tag(sender: Person, receiver: Person, rel: str, key: str) -> str:
    """一通の頭に付ける札。出所と間柄と鍵を明示し、所有者の言葉ではないと断る。"""
    meaning = RELATION_MEANING.get(rel, "")
    return (f"〔direct box・from={sender.label()}・to={receiver.label()}・relation={rel}・key={key}。"
            f"所有者の言葉ではない（{meaning}）〕")


def default_footer(sender: Person, key: str) -> str:
    """一通の末尾に添える、返し方の一行。"""
    return (f"（返事や続きが要る時は、同じ direct box で {sender.alias} 宛てに送るか、"
            f"この一通の鍵 {key} で reply してください。要らなければ返さなくて構いません）")


class DirectBox:
    def __init__(self, ledger: JsonlLedger, transport: Transport, tree_provider: TreeProvider, *,
                 roster: dict | None = None, root_alias: str = "root", text_limit: int = 6000,
                 footer: Callable[[Person, str], str] | None = default_footer,
                 clock: Callable[[], str] = now_text, key_factory: Callable[[], str] = make_key):
        self.ledger = ledger
        self.transport = transport
        self.tree_provider = tree_provider
        self.roster = roster or {}
        self.root_alias = root_alias
        self.text_limit = int(text_limit)
        self.footer = footer
        self.clock = clock
        self.key_factory = key_factory

    # ── 送る ───────────────────────────────────────────────────────────────────

    def send(self, sender_seat: str, to: str, text: str, *, from_root: bool = False) -> dict:
        """一通を届ける。返すのは {"ok": True, "key", "relation", "to", "seat"} か {"ok": False, "key", "reason"}。

        transport が例外を上げた時は、台帳に not_delivered を残してからそのまま投げる。"""
        key = self.key_factory()
        text = (text or "").strip()
        if not text:
            raise ValueError("text is empty")
        tree, seats = self.tree_provider()
        root = root_of(tree) or tree.get(self.root_alias)
        if root is None:
            raise ValueError("the genealogy has no root (a Person with level 0)")
        if from_root:
            sender, sender_seat = root, root.alias
        elif not sender_seat or sender_seat == root.alias or sender_seat not in tree:
            return self._refuse(key, None, sender_seat or "(no mark)", to, None, text,
                                "sender: the seat is not in the genealogy (no tag, no env mark, or claimed to be root)")
        else:
            sender = tree[sender_seat]
        to_alias = resolve_alias(to, tree, seats, self.roster)
        receiver = person_of(to_alias, tree) if to_alias else None
        if receiver is None and to_alias and to_alias in self.roster:   # 名簿に居るが席がまだ一度も立っていない人
            x = self.roster[to_alias] or {}
            receiver = Person(to_alias, x.get("name") or to_alias, x.get("engine", ""), 1, root.alias)
        if receiver is None:
            return self._refuse(key, sender, sender_seat, to, None, text, f"addressee: {to!r} is not in the genealogy")
        rel = relation(sender, receiver)
        if rel is None:
            allowed = " / ".join(RELATIONS)
            return self._refuse(key, sender, sender_seat, receiver.alias, receiver, text,
                                f"relation: {sender.name} -> {receiver.name} is not an allowed relation ({allowed})")
        seat = current_seat(receiver.alias, tree, seats)
        if seat is None:
            return self._refuse(key, sender, sender_seat, receiver.alias, receiver, text,
                                f"seat: {receiver.name} has no current seat", rel)
        body = tag(sender, receiver, rel, key) + "\n\n" + text
        if self.footer is not None:
            body += "\n\n" + self.footer(sender, key)
        record = self._record("sent", key, sender, sender_seat, receiver, text, relation=rel, seat=seat)
        try:
            self.transport(seat, body)
        except Exception as e:  # noqa: BLE001 — 何が起きたかは台帳に残してから投げる
            self.ledger.append(dict(record, kind="not_delivered", reason=f"transport: {type(e).__name__}: {e}"[:400]))
            raise
        self.ledger.append(dict(record, result="delivered"))
        return {"ok": True, "key": key, "relation": rel, "to": receiver.alias, "seat": seat}

    def _record(self, kind: str, key: str, sender: Person | None, sender_seat: str, receiver: Person | None,
                text: str, **more) -> dict:
        d = {"kind": kind, "key": key, "time": self.clock(),
             "sender": sender.alias if sender else sender_seat, "sender_name": sender.name if sender else "",
             "sender_engine": sender.engine if sender else "", "sender_seat": sender_seat,
             "to": receiver.alias if receiver else "", "to_name": receiver.name if receiver else "",
             "relation": "", "seat": "", "text": text[: self.text_limit]}
        d.update(more)
        return d

    def _refuse(self, key: str, sender: Person | None, sender_seat: str, to: str, receiver: Person | None,
                text: str, reason: str, rel: str = "") -> dict:
        d = self._record("not_delivered", key, sender, sender_seat, receiver, text, relation=rel, reason=reason)
        if receiver is None:
            d["to"] = to
        self.ledger.append(d)
        return {"ok": False, "key": key, "reason": reason}

    # ── 返す ───────────────────────────────────────────────────────────────────

    def reply(self, key: str, text: str) -> dict:
        """鍵の一通の受け手から、差出人の今の席へ返事を戻す。台帳には replied と returned を残す。"""
        text = (text or "").strip()
        if not text:
            raise ValueError("text is empty")
        sent = self.ledger.find(key, "sent")
        if sent is None:
            raise KeyError(f"no delivered letter with key {key!r}")
        tree, seats = self.tree_provider()
        by = str(sent.get("to") or "")
        self.ledger.append({"kind": "replied", "key": key, "time": self.clock(), "by": by, "reply": text})
        target = person_of(str(sent.get("sender") or ""), tree)
        if target is None:
            return self._not_returned(key, by, "the sender is no longer in the genealogy")
        seat = current_seat(target.alias, tree, seats)
        if seat is None:
            return self._not_returned(key, by, f"{target.name} has no current seat")
        replier = person_of(by, tree) or Person(by, str(sent.get("to_name") or by), "", 1, None)
        rel = REPLY_RELATION.get(str(sent.get("relation") or ""), "reply")
        body = tag(replier, target, rel, key) + f"\n\n（あなたが鍵 {key} で送った一通への返事です）\n\n" + text
        if self.footer is not None:
            body += "\n\n" + self.footer(replier, key)
        try:
            self.transport(seat, body)
        except Exception as e:  # noqa: BLE001
            self._not_returned(key, by, f"transport: {type(e).__name__}: {e}"[:400])
            raise
        self.ledger.append({"kind": "returned", "key": key, "time": self.clock(), "by": by, "seat": seat,
                            "relation": rel, "result": "delivered"})
        return {"ok": True, "key": key, "relation": rel, "to": target.alias, "seat": seat}

    def _not_returned(self, key: str, by: str, reason: str) -> dict:
        self.ledger.append({"kind": "returned", "key": key, "time": self.clock(), "by": by, "seat": "",
                            "result": f"not returned: {reason}"})
        return {"ok": False, "key": key, "reason": reason}

    # ── 読む ───────────────────────────────────────────────────────────────────

    def recipients(self, sender_seat: str, *, from_root: bool = False) -> list[dict]:
        """その席から送れる相手 [{"alias", "name", "relation", "seat"}]。名簿に居て席の無い人も並ぶ。"""
        tree, seats = self.tree_provider()
        root = root_of(tree)
        sender = root if from_root else tree.get(sender_seat)
        if sender is None or (not from_root and root is not None and sender_seat == root.alias):
            return []
        seen: set[str] = set()
        out: list[dict] = []
        for p in tree.values():
            if p.alias in seen:
                continue
            seen.add(p.alias)
            rel = relation(sender, p)
            if rel:
                out.append({"alias": p.alias, "name": p.name, "relation": rel,
                            "seat": current_seat(p.alias, tree, seats) or ""})
        for alias, x in self.roster.items():
            if alias in seen or root is None:
                continue
            p = Person(alias, (x or {}).get("name") or alias, (x or {}).get("engine", ""), 1, root.alias)
            rel = relation(sender, p)
            if rel:
                out.append({"alias": alias, "name": p.name, "relation": rel, "seat": ""})
        return out

    def list(self, limit: int | None = 30) -> list[dict]:
        """台帳を鍵ごとに畳んで新しい順（JsonlLedger.list と同じ）。"""
        return self.ledger.list(limit)
