"""合札（seat token）— 器の印が無い席のために、口が席ごとに出す札。

差出人は「名乗り」では決めない。決め手は二つだけ:
  1. 器の印（env_mark）… 走っている器が子プロセスに渡す環境変数（例: エージェント基盤が付ける agent id）。
  2. 合札（token）    … 器の印が子プロセスへ届かない器のために、箱がその席へ届けた一通にだけ載せる札。
                        合札 → 席 id の対応はここが持つので、合札を知っているのはその席だけ。

出所の出来事: ある器では exec の子プロセスに器の印の環境変数が来なかった。名乗りは信じないので、
箱が席ごとに合札を出して、その席へ届ける文の末尾に「返す時はこの合札を付けて」と書く形にした。

置き場は一つの JSON（token → agent_id）。書く時は file_lock で一本にし、atomic_replace で置き換える。
"""
from __future__ import annotations

import json
import os
import uuid

from .ledger import atomic_replace, file_lock


class SeatTokens:
    def __init__(self, path: str, *, prefix: str = "ds-", lock_timeout: float = 10.0):
        self.path = path
        self.prefix = prefix
        self.lock_timeout = float(lock_timeout)

    def _read(self) -> dict[str, str]:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return {}
        return {str(k): str(v or "") for k, v in d.items()} if isinstance(d, dict) else {}

    def _write(self, d: dict[str, str]) -> None:
        atomic_replace(self.path, json.dumps(d, ensure_ascii=False, indent=1) + "\n")

    def issue(self, agent_id: str = "") -> str:
        """その席の合札。在ればそれ、無ければ作る。agent_id が空なら、席が立つ前の合札（後で bind）。"""
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with file_lock(self.path, self.lock_timeout):
            d = self._read()
            if agent_id:
                for token, aid in d.items():
                    if aid == agent_id:
                        return token
            token = self.prefix + uuid.uuid4().hex[:16]
            d[token] = agent_id
            self._write(d)
        return token

    def bind(self, token: str, agent_id: str) -> None:
        """席が立ってから、先に出した合札をその席に結ぶ。"""
        with file_lock(self.path, self.lock_timeout):
            d = self._read()
            d[token] = agent_id
            self._write(d)

    def seat_of(self, token: str) -> str:
        """合札の席。知らない合札・空なら ""。"""
        return self._read().get((token or "").strip(), "") or ""

    def sender_seat(self, env_mark: str, token: str = "") -> str:
        """差出人の席を決める。器の印を先に、無ければ合札から。どちらも無ければ ""（送れない）。"""
        return (env_mark or "").strip() or self.seat_of(token)

    def hint(self, token: str) -> str:
        """その席へ届ける文の末尾に添える一行（器の印が無い器から返す時に合札を付けさせる）。"""
        return (f"（この席の合札: {token}。器の印が無い席から返す時は、この合札を sender token として付けてください）")
