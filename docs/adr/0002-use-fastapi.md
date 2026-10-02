# ADR 0002: バックエンドに FastAPI を使う

- 状態: 採用
- 日付: 2026-10-02

## 背景

バックエンドに必要なのは、CRUD の API、外部 API への大量の HTTP リクエスト、LLM の呼び出しである。どれも待ち時間の大半が I/O で、非同期処理に向いている。

フロントエンドは TypeScript で書くので、API の型をフロントエンドに正確に伝える手段も要る。

また、このプロジェクトには作者が Python と、LLM まわりのライブラリに習熟するという目的がある。作者の本業は C# / ASP.NET Core である。

## 決定

Python + FastAPI を使う。入出力の定義には Pydantic、DB アクセスには SQLAlchemy 2.0(async)を使う。

## 検討した他の案

**ASP.NET Core。** 作者がいちばん速く書ける。型も性能も十分で、技術的に劣る点はない。採用しなかった理由は、学習目的を満たさないことと、engine を Python で書く以上、API も同じ言語にしたほうが engine を import するだけで済むこと。

**Django + Django REST Framework。** 認証や管理画面が付いてくる。ただし非同期との相性が FastAPI ほど良くなく、今回は管理画面も要らない。

**Next.js だけで完結させる(Route Handlers)。** デプロイが1つで済む。ただし engine を CLI と共有できず、Python の LLM / RAG 関連ライブラリも使えない。

## 結果

- Pydantic のモデルから OpenAPI が自動生成される。フロントエンドの型はそこから生成する
- リクエストの検証、DI(`Depends`)、非同期がフレームワークの標準機能で揃う
- Python の型検査は実行時に強制されない。`mypy --strict` を CI で必須にして補う
- デプロイ対象が Next.js と FastAPI の2つになる
