# direct-box — 名前で届く、エージェントどうしの手紙箱

## Summary (English)

- A letter box for multi-agent systems: an agent sends a note **by the recipient's name**, not by session id, so the note still arrives after the recipient's session (seat) is replaced.
- Who may write to whom is decided by a **genealogy of ranks** built from session labels: same level, one up, one down, and level 2 up to the root. Diagonal and rank-skipping notes are refused.
- **Refusals are recorded too.** Every note, delivered or not, goes into an append-only JSON Lines ledger with its reason.
- Every delivered note carries a **source tag** ("from / to / relation / key, not the owner's words"), so the receiving agent never mistakes another agent's note for a human instruction.
- The sender is decided by the **seat**, never by self-declaration. Runtimes that do not pass an agent id to child processes get a per-seat **token** instead.
- Replies go back to the sender's **current** seat with the relation reversed.
- Transport and the agent list are injected. The box decides who, what and whether; it owns no network code.
- Standard library only, Python 3.11+. 54 pytest tests.

## 何か

複数のエージェント（会話セッション）が働く仕組みで、エージェントどうしが一通を届け合うための部品です。

- 宛先は **名義（人の名）** で引きます。届ける時だけ、その人の「今の席」に落とします。席が替わっても宛先は変わりません。
- 通してよい間柄は **系図（階層）** で決めます。通さなかった一通も、理由つきで台帳に残ります。
- 届けた一通の頭には **出所の札** が付きます。受け取った側が、人間の指示と取り違えないためです。

## なぜ注目に値するか

マルチエージェントで部下どうしを話させると、三つの事故が起きやすくなります。

1. **宛先の席が替わると届かない。** 文脈が埋まって席を替えると、前の席の id 宛ての一通は宙に浮きます。
2. **誰でも誰へでも指示できてしまう。** 横や斜めから指示が来ると、指揮系統が混線します。
3. **エージェントの一通を、人間の言葉と取り違える。** 札が無いと、受け手は出所を見分けられません。

この部品は、宛先を「人」で引くこと、間柄を系図で決めること、札を付けることの三つで、これを一度に塞ぎます。

## どう動くか

### 間柄（`relation`）

| 間柄 | 意味 |
|---|---|
| `same_level` | 同じ階層からの連絡・相談・共有。指示ではない |
| `one_up` | 直属の部下から上長への報告・相談 |
| `one_down` | 直属の上長から部下へ。指示は上から下へだけ流れる |
| `two_up_to_root` | 階層 2 から統括（root）への納品・報告。指示ではない |

これ以外（斜め・段飛ばし・統括から部下の部下へ）は `None` で、送りません。

### 系図の組み方（`build_tree`）

- 統括（root）は階層 0 で、一人だけです。
- 札 `from` が `person_tags` のどれかの席は、名簿の人本人です。階層 1 で、親は統括です。
- 札 `parent-agent-id` が付いた席は、その席の部下です。階層は親より一つ深くなります。
- 題が `[Handoff]` で始まる席は引き継ぎで、親の席と同じ人として数えます。
- 札から人を決められない席は、系図に載せません。名乗りだけでは入れません。

### 箱（`DirectBox`）

| 口 | すること |
|---|---|
| `send(sender_seat, to, text)` | 差出人を席で決め、宛先を名義に引き、間柄を確かめてから札を付けて届ける |
| `reply(key, text)` | 元の一通の受け手から、差出人の今の席へ戻す。間柄は裏返す |
| `recipients(sender_seat)` | その席から送れる相手の一覧。名簿に居て席の無い人も並ぶ |
| `list(limit)` | 台帳を鍵ごとに畳んで、新しい順に返す |

### 台帳と合札

- `JsonlLedger` は追記だけの台帳です。同じ一通を二度拾っても一件のままです。
- 書き込みは `file_lock` で一本にし、`atomic_replace` で置き換えます。Windows でも壊れない形にしてあります。
- `SeatTokens` は、エージェントの id が子プロセスに届かない器のための合札です。

## 使い方

```bash
python examples/two_agents.py
```

偽の transport（画面に出すだけ）で、通る一通と通らない一通を並べて見せます。

```python
from direct_box import DirectBox, JsonlLedger, build_tree

box = DirectBox(
    JsonlLedger("ledger.jsonl"),
    transport=lambda seat_id, text: my_platform.send(seat_id, text),
    tree_provider=lambda: (build_tree(my_platform.list_agents(), ROSTER, SEATS), SEATS),
    roster=ROSTER,
)
box.send("a-seat-0001", "b", "設計の相談です。")
```

## 出所

あるマルチエージェントの運用で、2026-11-18 に作られた仕組みを切り出しました。部下が席を替えても名前で今の席へ届くことと、「指示は直属の上長から下へだけ」という決まりを、一つの口で守るために作られました。

## 元の仕組みとの違い

- 元の仕組みは、名簿の人に「準備できているか」の旗を持ち、準備のできていない人を一覧に並べません。この部品の名簿には旗が無く、名簿の全員が並びます。
- 元の仕組みはエージェント基盤の一覧を直に読みます。この部品は一覧と transport を外から渡します。

## 柵

```bash
python -m pytest -q
```

2026-11-21 の観測で 54 passed です。柵のうち一本は、名簿に人を足す前と後の順番を取り違えていたので、意味を弱めずに並べ直しました。統括からも席の無い名簿の人が並ぶことを確かめる一行を足しています。

## 未了

- 実際のエージェント基盤に繋いで動かした確かめは、この切り出しではしていません。
- ライセンス: [MIT](LICENSE)
