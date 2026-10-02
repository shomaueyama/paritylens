# Architecture Decision Records

設計上の重要な判断を、1件1ファイルで残す。あとから「なぜこうなっているのか」を追えるようにするためのもので、決定を変えるときは既存の ADR を書き換えず、新しい ADR を追加して古いほうの状態を「置き換え済み」にする。

| 番号 | 題 | 状態 |
|---|---|---|
| [0001](0001-engine-as-library-with-two-runners.md) | engine をライブラリとして分離し、実行形態を2つ持つ | 採用 |
| [0002](0002-use-fastapi.md) | バックエンドに FastAPI を使う | 採用 |
| [0003](0003-use-postgresql.md) | PostgreSQL を使い、ジョブキューも当面 PostgreSQL で持つ | 採用 |
| [0004](0004-separate-deterministic-and-ai-diff.md) | 決定的 diff と AI 分析を分離する | 採用 |
| [0005](0005-noise-detection.md) | ノイズの検出に、2回実行とリクエスト時刻への追従を使う | 採用 |
| [0006](0006-egress-policy.md) | 外向き通信を EgressPolicy で制御する | 採用 |
| [0007](0007-backend-owned-auth.md) | 認証をバックエンドで持つ | 採用 |
| [0008](0008-frontend-types-from-openapi.md) | フロントエンドの型を OpenAPI から生成し、読み取りは Server Component で行う | 採用 |
| [0009](0009-llm-provider-and-analysis-layer.md) | LLM をプロバイダーの裏に置き、分析を一方通行の層にする | 採用 |

## 書式

```markdown
# ADR NNNN: 題

- 状態: 提案 / 採用 / 置き換え済み(→ NNNN)
- 日付: YYYY-MM-DD

## 背景
## 決定
## 検討した他の案
## 結果
```
