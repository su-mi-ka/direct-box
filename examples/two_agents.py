"""two_agents — 偽の transport（print）で、名前で届く手紙箱と階層の法を見る例。

    root（統括・階層 0）
    ├ a（階層 1・Claude Code）  席 a-seat-0001 と、引き継ぎの席 a-seat-0002（[Handoff]＝同じ人）
    │   └ c（階層 2・a の部下）
    │        └ d（階層 3・c の部下）
    └ b（階層 1・Codex）        席 b-seat-0001

通る   : a → b（同じ階層）・c → root（二段上＝納品・報告）・root → a（一個下）
通らない: c → b（斜め）・root → c（部下の部下へは直属の上長から）・d → root（三段上）

実行:  python examples/two_agents.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from direct_box import DirectBox, JsonlLedger, build_tree  # noqa: E402

ROSTER = {
    "a": {"name": "A", "engine": "Claude Code"},
    "b": {"name": "B", "engine": "Codex"},
}
SEATS = {   # 名義 → 今の席の控え（席が替わったらここを書き換えるだけで、宛先は変わらない）
    "a": {"agent_id": "a-seat-0001"},
    "b": {"agent_id": "b-seat-0001"},
}
AGENTS = [  # エージェント基盤の一覧（id・title・provider・status・updated・labels）
    {"id": "a-seat-0001", "title": "A の席", "provider": "claude", "status": "idle",
     "labels": {"from": "staff", "staff": "a"}},
    {"id": "a-seat-0002", "title": "[Handoff] A の続き", "provider": "claude", "status": "running",
     "updated": "2026-01-01T00:05:00Z", "labels": {"parent-agent-id": "a-seat-0001"}},
    {"id": "b-seat-0001", "title": "B の席", "provider": "codex", "status": "idle",
     "labels": {"from": "bypass", "staff": "b"}},
    {"id": "c-seat-0001", "title": "素材づくり", "provider": "codex", "status": "running",
     "labels": {"parent-agent-id": "a-seat-0001"}},
    {"id": "d-seat-0001", "title": "孫の作業", "provider": "codex", "status": "idle",
     "labels": {"parent-agent-id": "c-seat-0001"}},
    {"id": "x-seat-0001", "title": "所有者が直に立てた席（札なし）", "provider": "claude", "status": "running",
     "labels": {}},
]


def transport(seat_id: str, text: str) -> None:
    """本物なら、エージェント基盤の「走っている一手に合流させる」口（steer）を呼ぶ所。ここでは印字。"""
    print(f"    --> transport(seat_id={seat_id!r})")
    for line in text.splitlines():
        print("        | " + line)


def tree_provider():
    return build_tree(AGENTS, ROSTER, SEATS, root_alias="root", root_name="統括"), SEATS


def show(label: str, r: dict) -> None:
    mark = "通った  " if r["ok"] else "通さない"
    detail = f"relation={r['relation']} seat={r['seat']}" if r["ok"] else r["reason"]
    print(f"[{mark}] {label}  key={r['key']}  {detail}")


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        ledger = JsonlLedger(os.path.join(folder, "direct_box.jsonl"))
        box = DirectBox(ledger, transport, tree_provider, roster=ROSTER)

        print("== 系図（席 → 人・階層・親）")
        tree, _ = tree_provider()
        for seat_id, p in tree.items():
            print(f"    {seat_id:<12} alias={p.alias:<12} name={p.name:<8} level={p.level} parent={p.parent} status={p.status}")
        print("    （x-seat-0001 は札が無いので載らない＝名乗りでは系図に入れない）")

        print("\n== a-seat-0001 から送れる相手")
        for x in box.recipients("a-seat-0001"):
            print(f"    {x['alias']:<12} {x['relation']:<14} 今の席={x['seat']}")

        print("\n== 送る")
        show("a → b（同じ階層）      ", box.send("a-seat-0001", "b", "設計の相談です。接合部の形を揃えませんか。"))
        show("c → b（斜め）          ", box.send("c-seat-0001", "b", "よその上長へ直に。"))
        show("c → root（二段上）     ", box.send("c-seat-0001", "root", "素材 3 点を納品します。"))
        show("root → c（部下の部下） ", box.send("", "c-seat-0001", "直に指示。", from_root=True))
        show("d → root（三段上）     ", box.send("d-seat-0001", "root", "孫から統括へ。"))
        show("root → a（一個下）     ", box.send("", "a", "方針を一つ。接合部は a が決めてください。", from_root=True))
        show("x（札なし）→ b         ", box.send("x-seat-0001", "b", "名乗りだけの席から。"))

        print("\n== 返事（c → root の一通へ、root から戻す。差出人の今の席へ届く）")
        delivered = [e for e in box.list(limit=None) if e["kind"] == "sent" and e["to"] == "root"]
        back = box.reply(delivered[0]["key"], "受け取りました。3 点とも通ります。")
        print(f"    returned: ok={back['ok']} relation={back['relation']} seat={back['seat']}")

        print("\n== 台帳（鍵ごとに畳んで新しい順。通さなかった一通も残る）")
        for e in box.list(limit=None):
            rel = e.get("relation") or "-"
            tail = e.get("reason") or e.get("result") or ""
            print(f"    {e['time']}  {e['kind']:<14} {e['sender']:<12} -> {e['to']:<12} {rel:<15} replies={len(e['replies'])}  {tail}")


if __name__ == "__main__":
    main()
