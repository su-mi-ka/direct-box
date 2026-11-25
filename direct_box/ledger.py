"""台帳（JSON Lines）と、それを壊さずに書くための二つの道具。

atomic_replace(path, text)
    呼ぶたびに別名の一時ファイル（同じフォルダ）へ書き切ってから os.replace で置き換える。
    Windows で読み手が本物を開いている一瞬は置き換えが PermissionError になるので、少し待って試し直す。
    置き換えられなかった時は一時ファイルを消して例外を上げる（前の中身はそのまま残る）。
    一時ファイルの名前を固定（path + ".tmp"）にすると、二人が同時に書いた時に同じ一時ファイルを
    取り合って落ちる——それがこの形の出所。

file_lock(path, timeout)
    読む → 直す → 書き戻す を一本ずつ通す。同じプロセスの中はスレッドの RLock、プロセスを跨ぐ分は
    path + ".lock" のファイル錠（Windows は msvcrt.locking、ほかは fcntl.flock）。
    同じスレッドからの入れ子は通す。待ちきれなければ TimeoutError を上げる（黙って錠なしで書かない）。
    ⚠ 錠を持ったまま await しない。同じスレッドの入れ子を通すので、イベントループの上で錠を持って
       待つと、同じループの別の仕事が素通りする。

JsonlLedger(path)
    追記だけの台帳。一行が一つの出来事（dict・必ず "kind" と "key" を持つ）。
    - arrived(key, ...) は同じ鍵を二度書かない（二度目は False）。見張りが同じ一通を二度拾っても一件のまま。
    - list(limit) は鍵ごとに畳んで新しい順。頭は HEAD_KINDS のどれか、あとの出来事は "replies" に並ぶ。
      頭の無い鍵（返事だけ）は並べない。
    - 長い文（text_fields）は text_limit で切って残す。
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Iterable, Iterator

#: 一件の「頭」になる種。これ以外の種は、同じ鍵の頭の "replies" に畳まれる。
HEAD_KINDS: tuple[str, ...] = ("arrived", "sent", "not_delivered")

_locks: dict[str, "_PathLock"] = {}
_registry_lock = threading.Lock()


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def now_text() -> str:
    """台帳に書く時刻の形（ローカル時刻・秒まで）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ── atomic_replace ────────────────────────────────────────────────────────────────

def atomic_replace(path: str, text: str | bytes, *, encoding: str = "utf-8", newline: str | None = "\n",
                   attempts: int = 20, interval: float = 0.05) -> None:
    """path を text で置き換える。一時ファイルは呼ぶたびに別の名前（同じフォルダ）。"""
    folder = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        if isinstance(text, bytes):
            with os.fdopen(fd, "wb") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        else:
            with os.fdopen(fd, "w", encoding=encoding, newline=newline) as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        for i in range(max(1, attempts)):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i + 1 >= attempts:
                    raise
                time.sleep(interval)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ── file_lock ────────────────────────────────────────────────────────────────────

class _PathLock:
    """一つの道（path）に対する錠。スレッドの RLock と、プロセスを跨ぐファイル錠の二枚。"""

    def __init__(self, path: str):
        self.path = path
        self.thread_lock = threading.RLock()
        self.depth = 0
        self.handle = None

    def _acquire_file(self, deadline: float) -> None:
        f = open(self.path + ".lock", "a+b")
        try:
            while True:
                try:
                    f.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.handle = f
                    return
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"cannot take the ledger lock (held by another process): {self.path}") from None
                    time.sleep(0.02)
        except BaseException:
            f.close()
            raise

    def _release_file(self) -> None:
        f, self.handle = self.handle, None
        if f is None:
            return
        try:
            f.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


@contextlib.contextmanager
def file_lock(path: str, timeout: float = 10.0) -> Iterator[None]:
    """path の台帳を一本ずつ通す（プロセスの中も外も）。同じスレッドの入れ子は通す。

    待ちきれなければ TimeoutError。錠を取れないまま黙って先へ進むことはしない。"""
    norm = _norm(path)
    with _registry_lock:
        lock = _locks.get(norm)
        if lock is None:
            lock = _locks[norm] = _PathLock(norm)
    deadline = time.monotonic() + timeout
    if not lock.thread_lock.acquire(timeout=max(0.0, timeout)):
        raise TimeoutError(f"cannot take the ledger lock (held by another thread): {path}")
    try:
        if lock.depth == 0:
            lock._acquire_file(deadline)
        lock.depth += 1
        try:
            yield
        finally:
            lock.depth -= 1
            if lock.depth == 0:
                lock._release_file()
    finally:
        lock.thread_lock.release()


# ── JsonlLedger ──────────────────────────────────────────────────────────────────

def fold(records: Iterable[dict], head_kinds: tuple[str, ...] = HEAD_KINDS) -> list[dict]:
    """出来事を鍵ごとに畳む。読むだけの純粋関数。頭の時刻の新しい順（同じ時刻なら後に書かれた方が先）。

    一件の頭は、その鍵で最初に現れた head_kinds の出来事。頭のあとに同じ鍵で起きた出来事は、種を問わず
    "replies" に {"time", "kind", "by", "text"} として並ぶ（text は reply → reason → text → result の順で拾う）。
    頭の無い鍵は並べない。"""
    rows = list(records)
    heads: dict[str, dict] = {}
    head_index: dict[str, int] = {}
    for i, r in enumerate(rows):
        key = r.get("key")
        if key and r.get("kind") in head_kinds and key not in heads:
            heads[key] = dict(r, replies=[])
            head_index[key] = i
    for i, r in enumerate(rows):
        key = r.get("key")
        if key in heads and i != head_index[key]:
            heads[key]["replies"].append({
                "time": r.get("time", ""), "kind": r.get("kind", ""), "by": r.get("by", ""),
                "text": r.get("reply") or r.get("reason") or r.get("text") or r.get("result") or "",
            })
    order = sorted(heads, key=lambda k: (heads[k].get("time", ""), head_index[k]), reverse=True)
    return [heads[k] for k in order]


class JsonlLedger:
    """追記だけの JSONL 台帳。書く口は append / append_once / arrived / replied、読む口は read / find / has / list。"""

    def __init__(self, path: str, *, text_limit: int = 6000, text_fields: tuple[str, ...] = ("text", "reply"),
                 head_kinds: tuple[str, ...] = HEAD_KINDS, lock_timeout: float = 10.0):
        self.path = path
        self.text_limit = int(text_limit)
        self.text_fields = tuple(text_fields)
        self.head_kinds = tuple(head_kinds)
        self.lock_timeout = float(lock_timeout)

    # 読む

    def read(self) -> list[dict]:
        """全部の出来事を書かれた順に。壊れた行・鍵の無い行は飛ばす。無ければ空。"""
        out: list[dict] = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(d, dict) and d.get("key"):
                        out.append(d)
        except FileNotFoundError:
            pass
        return out

    def find(self, key: str, kind: str | None = None) -> dict | None:
        """その鍵（と種）の、いちばん後に書かれた出来事。無ければ None。"""
        for r in reversed(self.read()):
            if r.get("key") == key and (kind is None or r.get("kind") == kind):
                return r
        return None

    def has(self, key: str, kind: str | None = None) -> bool:
        return self.find(key, kind) is not None

    def list(self, limit: int | None = 30) -> list[dict]:
        """鍵ごとに畳んで新しい順。limit が None なら全部。"""
        out = fold(self.read(), self.head_kinds)
        return out if limit is None else out[: max(0, int(limit))]

    # 書く

    def _trim(self, record: dict) -> dict:
        d = dict(record)
        for k in self.text_fields:
            if isinstance(d.get(k), str):
                d[k] = d[k][: self.text_limit]
        d.setdefault("time", now_text())
        return d

    def append(self, record: dict) -> dict:
        """一つの出来事を追記する（"kind" と "key" が要る）。書いた形を返す。"""
        if not record.get("kind") or not record.get("key"):
            raise ValueError("a ledger record needs 'kind' and 'key'")
        d = self._trim(record)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with file_lock(self.path, self.lock_timeout):
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        return d

    def append_once(self, key: str, kind: str, **fields) -> bool:
        """同じ鍵・同じ種がまだ無ければ書いて True。もう在れば書かずに False。読んで書くまでを錠で一本にする。"""
        key = (key or "").strip()
        if not key:
            raise ValueError("key is required")
        with file_lock(self.path, self.lock_timeout):
            if self.has(key, kind):
                return False
            self.append(dict(fields, kind=kind, key=key))
        return True

    def arrived(self, key: str, text: str = "", **fields) -> bool:
        """外から一通が来た。新しく書いたら True、同じ鍵がもう在れば False（二度書かない）。"""
        return self.append_once(key, "arrived", text=text, **fields)

    def replied(self, key: str, reply: str, *, by: str = "", **fields) -> dict:
        """その一通へ返した。返事は何度でも足せる（list には全部並ぶ）。"""
        key = (key or "").strip()
        if not key:
            raise ValueError("key is required")
        return self.append(dict(fields, kind="replied", key=key, by=by, reply=reply or ""))
