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

## Phase 1 で出てきた具体例

| 見るファイル | ASP.NET でいうと | 見どころ |
|---|---|---|
| `apps/api/src/paritylens_api/routers/health.py` | Controller のアクション1つ | `APIRouter` がコントローラー、`@router.get` が `[HttpGet]`。戻り値の型 `HealthResponse` がそのままレスポンスの DTO になり、OpenAPI にも出る |
| `apps/api/src/paritylens_api/main.py` | `Program.cs` | `create_app()` でアプリを組み立てる。`include_router` が `MapControllers` に当たる |
| `apps/api/tests/test_api_health.py` | `WebApplicationFactory` を使った統合テスト | `TestClient(create_app())` で、サーバーを起動せずに HTTP を投げられる |
| `demo/legacy-shop-api/.../main.py` と `demo/modern-shop-api/.../main.py` | 手書きの検証 と `[ApiController]` + DataAnnotations | 同じ API を2通りに書いてある。Legacy は dict を手で検証して 400 を返す。Modern は Pydantic に任せるので、検証エラーは自動で 422 になる。この既定値の違いが、そのままデモの差異 10 になっている |
| `apps/web/src/app/page.tsx` | Razor Page の `OnGetAsync` + View | `async` の Server Component。サーバーで API を `await` し、HTML だけをブラウザに送る |
| `apps/web/next.config.ts` の `rewrites` | YARP などのリバースプロキシ | `/api/*` をバックエンドに中継する。ブラウザから見るとオリジンが1つになる |
| `pyproject.toml`(ルート) | `.sln` + `Directory.Build.props` | uv の workspace が複数パッケージをまとめる。ruff や mypy の設定もここに1回だけ書く |
| `infra/docker/python-service.Dockerfile` | `dotnet publish` を使うマルチステージビルド | 1段目で依存を入れ、2段目には仮想環境だけをコピーする。実行は非 root ユーザー |

### Python で最初につまずきやすい点

- **`bool` は `int` のサブクラス。** `isinstance(True, int)` は `True` になる。Legacy API の数量チェックで `bool` を明示的に除外しているのはこのため
- **型注釈は実行時に強制されない。** C# と違い、`def f(x: int)` に文字列を渡しても実行時エラーにならない。`mypy --strict` を CI で通すことで補う。Pydantic のモデルだけは実行時にも検証する
- **`//` は切り捨て除算。** `303 * 10 // 100` は `30`。デモの消費税計算はこれを使っている。金額に `float` を使わないのは C# で `decimal` を使うのと同じ理由

## Phase 2 で出てきた具体例

Phase 2 は `packages/engine` だけで完結する。Web も DB も出てこない、普通の Python のコードである。

| 見るファイル | C# でいうと | 見どころ |
|---|---|---|
| `model.py` | `record` と `enum` | Pydantic の `frozen=True` が不変の record に当たる。`StrEnum` は値が文字列の enum で、JSON にそのまま出せる。`field_validator` はコンストラクタでの検証 |
| `jsonvalue.py` の `type Json = ...` | 判別共用体(C# にはまだない) | 「JSON の値とは、bool か int か … か、それらの list か dict」を型として書いている。`isinstance` で分岐すると、mypy がその枝の中の型を絞り込む |
| `paths.py` の `match pattern:` | `switch` 式とパターンマッチ | `case _Key(name):` はクラスの中身を取り出しながら分岐する。C# の `case Key(var name):` と同じ |
| `diff.py` | 再帰で木をたどる普通のコード | 入力を受け取り、差異のリストを返すだけ。I/O がないので、テストは値を渡して結果を見るだけで済む |
| `severity.py` の `Evidence` | 引数をまとめる小さな `record` | `@dataclass(frozen=True)` は Pydantic より軽い。外部に出さない内部用の値にはこちらを使う |
| `tests/test_diff.py` の `@pytest.mark.parametrize` | xUnit の `[Theory]` + `[InlineData]` | 1つのテスト関数に入力の表を渡す |
| `tests/test_properties.py` | FsCheck | Hypothesis が JSON を自動生成し、「自分自身との差分は空」のような性質が常に成り立つかを調べる。失敗すると、最小の反例まで縮めて見せてくれる |

### Pydantic と dataclass の使い分け

- **Pydantic(`BaseModel`)**: プロセスの外に出る値。JSON にする、ファイルに書く、API で返す。実行時に検証する
- **dataclass**: プロセスの中だけで使う値。検証は要らず、型検査(mypy)で足りる

`Difference` は CLI がファイルに書き、API が読んで DB に保存するので Pydantic。`RawDifference` は engine の中でしか使わないので dataclass。

### 純粋関数にしておく理由

`compare_step(old, new, rules, baseline)` は、引数だけから結果が決まる。時計も乱数もネットワークも触らない。受信時刻が必要な判定(リクエスト時刻への追従)も、時刻を引数として受け取る形にしてある。

C# でいえば、`DateTime.Now` を直接呼ばずに `TimeProvider` を注入するのと同じ発想だが、ここではさらに進めて、値そのものを渡している。おかげで engine のテストにはモックが1つもない。
