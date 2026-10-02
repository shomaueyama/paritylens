# ASP.NET から見た対応表

C# / ASP.NET Core の経験を前提に、このリポジトリで使う技術がどれに当たるかをまとめる。各 Phase で実際のコードが出てきたときに、ここへ具体例を足していく。

## バックエンド(FastAPI)

| ASP.NET Core | このリポジトリ | 違い |
|---|---|---|
| Controller | `routers/` の関数 | クラスではなく関数。`@router.get("/projects")` がルーティング属性に当たる |
| DTO(record、class) | Pydantic モデル(`schemas/`) | 型注釈がそのまま検証ルールになる。ModelState の検証は FastAPI が自動で行い、失敗すると 422 を返す |
| DI コンテナ(`AddScoped`) | `Depends` | コンテナへの登録はない。引数に `Depends(get_db)` と書くと、リクエストごとに関数が呼ばれて結果が渡る。Scoped に近い |
| Middleware | Middleware、または `Depends` | 認証のように「現在のユーザー」を返すものは `Depends` で書くほうが型が付く |
| Entity Framework Core | SQLAlchemy 2.0 | `DbContext` に当たるのが `AsyncSession`。変更追跡と Unit of Work は同じ考え方 |
| EF Migrations | Alembic | モデルから差分を自動生成できるが、生成結果は必ず読む |
| `IOptions<T>`、appsettings | pydantic-settings | 環境変数を型付きのクラスに読み込む |
| `async Task<T>` | `async def` | 文法はほぼ同じ。違いは、Python のイベントループは1スレッドで、同期のブロッキング呼び出しを混ぜると全体が止まること |
| interface | `Protocol` | 継承を宣言しなくても、メソッドの形が合えば適合する(構造的部分型) |
| xUnit、Moq | pytest、fixture | fixture は DI に近い。テスト関数の引数名で依存を受け取る |
| NuGet、csproj | uv、pyproject.toml | |

## フロントエンド(Next.js)

| ASP.NET | Next.js | 違い |
|---|---|---|
| Razor Pages、MVC の View | Server Component | サーバーで実行されて HTML になる。DB や API を直接呼べる。状態もイベントも持てない |
| Blazor WebAssembly のコンポーネント | Client Component(`"use client"`) | ブラウザで動く。`useState` やクリックの処理はこちらにしか書けない |
| ルーティング属性 | App Router | フォルダ構造がそのまま URL になる。`app/projects/[projectId]/page.tsx` が `/projects/123` |
| `_Layout.cshtml` | `layout.tsx` | 入れ子にできる |
| ViewModel の双方向バインド | React の state | 単方向。state を変えると再描画される。値を直接書き換えても画面は変わらない |

## AI

| 用語 | 一言で |
|---|---|
| LLM | 文章を入力すると続きを生成するモデル。このプロジェクトでは差異の説明と分類に使う |
| 構造化出力 | LLM に JSON スキーマどおりの出力をさせる方法。自由文をパースしない |
| Embedding | 文章を数百〜数千次元のベクトルに変換したもの。意味が近い文章はベクトルも近くなる |
| Vector Search | ベクトルの近さで検索すること。PostgreSQL では pgvector 拡張で行う |
| RAG | 質問に関連する文書を検索し、それを LLM に渡して答えさせる構成。LLM が知らない仕様書の内容を扱える |
