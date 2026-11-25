"""direct_box — エージェント（席）どうしが「名前」で一通を届け合う手紙箱。

宛先は席の id ではなく名義で引くので、席が替わっても今の席へ届く。
通してよい間柄は系図（階層）で決め、通さなかった一通も台帳に残す。

    ledger      … 追記だけの JSONL 台帳と、壊さずに書くための atomic_replace / file_lock
    genealogy   … 席の札から系図を組む純粋関数（build_tree / resolve_alias / current_seat / relation）
    seat_tokens … 器の印が無い席のための合札（seat token）
    box         … DirectBox（send / reply / list / recipients）
"""
from __future__ import annotations

from .box import DirectBox, default_footer, make_key, tag
from .genealogy import (
    RELATION_MEANING,
    RELATIONS,
    REPLY_RELATION,
    RUNNING,
    Person,
    build_tree,
    current_seat,
    person_of,
    person_of_labels,
    relation,
    resolve_alias,
    root_of,
)
from .ledger import HEAD_KINDS, JsonlLedger, atomic_replace, file_lock, fold, now_text
from .seat_tokens import SeatTokens

__version__ = "0.1.0"

__all__ = [
    "DirectBox", "default_footer", "make_key", "tag",
    "RELATION_MEANING", "RELATIONS", "REPLY_RELATION", "RUNNING", "Person",
    "build_tree", "current_seat", "person_of", "person_of_labels", "relation", "resolve_alias", "root_of",
    "HEAD_KINDS", "JsonlLedger", "atomic_replace", "file_lock", "fold", "now_text",
    "SeatTokens",
]
