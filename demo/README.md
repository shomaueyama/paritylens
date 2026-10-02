# Demo: Legacy Shop API と Modern Shop API

ParityLens の動作確認用に用意した、架空の注文 API 2つ。実在のシステムとは無関係。

- `legacy-shop-api`: 旧システム。リクエストを手作業で検証し、レスポンスを1項目ずつ組み立てている
- `modern-shop-api`: 新システム。Pydantic のモデルと FastAPI の既定の挙動に寄せて書き直したもの

新システムには、書き直しのときに誰も決めないまま紛れ込みがちな差異を意図的に入れてある。ParityLens はこれらを自動で見つけ、重大度を付けることを目標にする。

## エンドポイント

どちらも同じ。

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/health` | 死活確認 |
| POST | `/orders` | 注文を作成する |
| GET | `/orders/{id}` | 注文を取得する |
| DELETE | `/orders/{id}` | 注文を取り消す |

`ORD-000001` は旧システムから移行済みの注文として、両方に最初から入っている。

## 仕込んである差異

| # | 条件 | Legacy | Modern | ParityLens に期待する検出 |
|---|---|---|---|---|
| 1 | 注文を作成する | `id` は `ORD-000002` 形式、`created_at` は JST | `id` は UUID、`created_at` は UTC | 重大度 NONE(実行ごとに変わる値) |
| 2 | 注文を作成する | `currency` なし | `currency: "JPY"` | `FIELD_ADDED` / LOW |
| 3 | `customer_name` を省略する | 400 | 201 | `STATUS_CHANGED` / CRITICAL |
| 4 | 明細が2行以上の注文 | 消費税を明細ごとに切り捨てて合算 | 小計に対して1回だけ切り捨て | `VALUE_CHANGED` / CRITICAL |
| 5 | 注文を取り消す | 200 と `{"id", "status"}` | 204、ボディなし | `STATUS_CHANGED` / HIGH |
| 6 | 注文を作成する | `quantity` が文字列(`"3"`) | `quantity` が数値(`3`) | `TYPE_CHANGED` / HIGH |
| 7 | 明細が2行以上の注文 | `items` を SKU 順に返す | `items` をリクエスト順に返す | `unordered` ルールで解消 |
| 8 | `ORD-000001` を取得する | `2026-01-15T10:00:00+09:00` | `2026-01-15T10:00:00Z` | `VALUE_CHANGED`(1 と同じフィールドだが、毎回同じ値なので本物の差異) |
| 9 | 存在しない注文を取得する | `{"error": {"code", "message"}}` | `{"detail": "..."}` | `FIELD_REMOVED` + `FIELD_ADDED` |
| 10 | 数量に 0 を指定する | 400 | 422 | `STATUS_CHANGED` / HIGH |

4 の例: 198 円と 105 円の商品を1つずつ注文すると、小計は 303 円。Legacy は 19 円 + 10 円 = 29 円、Modern は 30 円を消費税とするので、合計が 1 円違う。明細が1行なら一致するため、単純なテストでは見つからない。

各差異は `demo/tests/test_planted_differences.py` で両方の API に対して確認している。番号はテスト名と対応する。

## 起動

```bash
uv run uvicorn legacy_shop_api.main:app --port 8001
uv run uvicorn modern_shop_api.main:app --port 8002
```

```bash
curl -s -X POST localhost:8001/orders -H 'content-type: application/json' \
  -d '{"customer_name":"John","items":[{"sku":"B-200","quantity":1},{"sku":"A-100","quantity":1}]}'
```
