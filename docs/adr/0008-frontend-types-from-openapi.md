# ADR 0008: フロントエンドの型を OpenAPI から生成し、読み取りは Server Component で行う

- 状態: 採用
- 日付: 2026-10-02

## 背景

フロントエンド(TypeScript)とバックエンド(Python)は別の言語で、同じデータの形を両方が知っている必要がある。

よくある方法は、TypeScript 側に `interface Project { ... }` を手で書くことである。動くが、バックエンドのフィールド名を変えたときに、TypeScript の型は古いまま、コンパイルも通る。ずれは実行時に、画面が壊れて初めてわかる。

当初の構成案には、共有の型を置く `packages/shared` があった。しかし Python と TypeScript の間で共有できるコードはなく、そこに置けるのは手書きの型定義だけである。

もう1つ決めることがある。Next.js の App Router では、データを取得する場所が複数ある(Server Component、Client Component、Route Handler、Server Action)。場所ごとにやり方が違うと、認証の扱いやエラー処理が分散する。

## 決定

**型は生成する。** FastAPI が出力する OpenAPI から `openapi-typescript` で `schema.d.ts` を生成し、`openapi-fetch` でそれを使う。パス、パラメータ、リクエストボディ、レスポンスのすべてに型が付く。フロントエンドには API の型定義を1行も手で書かない。

```
FastAPI のモデル → openapi.json → schema.d.ts → api.GET("/api/v1/projects/{project_id}", ...)
```

生成物(`openapi.json` と `schema.d.ts`)はリポジトリに入れ、CI で再生成して差分がないことを確かめる。バックエンドを変えて再生成を忘れると、CI が落ちる。

**データの流れを2本に絞る。**

| | 場所 | 方法 |
|---|---|---|
| 読み取り | Server Component | `serverApi()`。リクエストの Cookie をバックエンドに転送する |
| 更新 | Client Component | `api`(ブラウザから同一オリジンの `/api/*` へ) |

Server Action と Route Handler は使わない。更新の入口はバックエンドの API だけにする。

状態やイベントを持つ部分(フォーム、実行状況のポーリング、削除ボタン)だけを Client Component にし、残りは Server Component のままにする。

## 検討した他の案

**型を手書きする。** 生成の仕組みが要らない。上に書いたとおり、ずれを検出できない。

**tRPC や GraphQL。** 型の共有が前提の仕組みで、フロントとバックが両方 TypeScript なら最有力。バックエンドが Python なので使えない、または二重の層が要る。

**Server Action で更新する。** フォームが JavaScript なしでも動く、という利点がある。ただし Next.js のサーバーが更新を仲介することになり、「バックエンドの API が唯一の入口」でなくなる。CSRF 対策や認可を、バックエンドと Next.js の両方で考えることになる。

**すべて Client Component にして、ブラウザから取得する。** 従来の SPA と同じで理解しやすい。初期表示が遅くなり、ローディング状態の扱いが全画面に要る。

## 結果

- バックエンドのレスポンスの形を変えると、それを使っているフロントエンドのコードがコンパイルエラーになる
- バックエンドの型が曖昧だと、生成される型も曖昧になる。Phase 5 で、ステータスや重大度を `str` から列挙型に直した(`string` ではなく `"queued" | "running" | ...` が生成される)
- 既定値のあるフィールドは、リクエストでは省略可能、レスポンスでも省略可能として生成される(`--default-non-nullable false`)。レスポンスでは実際には必ず入っているので、型のほうが少し緩い
- 更新のあとは `router.refresh()` を呼び、Server Component に再取得させる。呼び忘れると画面が古いままになる
- JavaScript を無効にするとフォームは動かない
