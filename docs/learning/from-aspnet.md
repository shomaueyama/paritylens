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

## Phase 3 で出てきた具体例

Phase 3 で初めて I/O が出てくる。非同期処理と HTTP クライアントが中心。

| 見るファイル | C# / .NET でいうと | 見どころ |
|---|---|---|
| `executor.py` の `async def` / `await` | `async Task` / `await` | 文法はほぼ同じ。`asyncio.gather(a, b, c)` が `Task.WhenAll`、`asyncio.Semaphore` が `SemaphoreSlim`、`asyncio.timeout(30)` が `CancellationTokenSource(TimeSpan)` に当たる |
| `executor.py` の `httpx2.AsyncClient` | `HttpClient` | 1回の実行で1つ作って使い回す(接続プールを共有する)。この点も `HttpClient` と同じ |
| `transport.py` の `GuardedTransport` | `DelegatingHandler` / `SocketsHttpHandler.ConnectCallback` | HTTP クライアントの下層を差し替える。.NET で SSRF 対策をするなら `ConnectCallback` で同じことをする |
| `tests/test_executor.py` の `MockTransport` | `HttpMessageHandler` を差し替えたテスト | ネットワークに出ずに、リクエストを受け取る関数でレスポンスを返す |
| `packages/cli/.../main.py` | `System.CommandLine` | 関数の引数と型注釈が、そのままコマンドライン引数の定義になる(Typer)。FastAPI と同じ作者で、考え方も同じ |
| `suite.py` の `model_validator` | `IValidatableObject.Validate` | フィールドをまたぐ検証。「変数は使う前に取得されていること」を読み込み時に確かめる |
| ルートの `conftest.py` | xUnit の `IClassFixture` / `WebApplicationFactory` | テスト用にアプリを実ポートで起動する fixture |

### async / await で C# と違うところ

- **スレッドは1本。** .NET の `await` は継続をスレッドプールで再開するが、Python の asyncio は1つのスレッドのイベントループで順番に進める。待っている間に別の処理が進むだけで、同時に2つのコードが走ることはない。そのためロックはほとんど要らない
- **同期のブロッキング呼び出しは全体を止める。** `time.sleep(1)` や同期の HTTP 呼び出しを `async def` の中で使うと、その間ほかのリクエストも全部止まる。.NET の `.Result` によるデッドロックとは症状が違うが、「async の中で同期 I/O を使わない」という規律は同じ
- **`asyncio.run()` が入口。** 同期の世界から非同期の関数を呼ぶ唯一の場所。CLI の `main.py` に1回だけ出てくる

### SSRF 対策の要点

`http://evil.example/` が安全かどうかは、URL を見てもわからない。`evil.example` がどの IP に解決されるかで決まり、それは攻撃者が決められる。だから検査の対象は URL ではなく、実際に接続する IP アドレスである。

さらに、検査のときと接続のときで名前解決を別々に行うと、その間に答えを変えられる(DNS rebinding)。`GuardedBackend.connect_tcp` が名前解決・検査・接続を1つの関数の中で行っているのは、このためである。`tests/test_transport.py` の `test_dns_rebinding_gets_no_second_lookup_to_exploit` が、名前解決が1回しか行われないことを確かめている。

## Phase 4 で出てきた具体例

Phase 4 は ASP.NET の経験がいちばん活きる。Controller、DI、EF Core、認証ミドルウェアに当たるものが揃う。

| 見るファイル | ASP.NET Core でいうと | 見どころ |
|---|---|---|
| `routers/projects.py` | Controller | 関数の引数がそのままバインディング。パス、クエリ、ボディ、DI の区別は型で決まる(`uuid.UUID` はパス、Pydantic モデルはボディ、`Depends` は DI) |
| `deps.py` | `[Authorize]` + `ClaimsPrincipal` + DI | `PrincipalDep` を引数に書いたハンドラは認証が必須になる。属性ではなく引数なので、認証済みのユーザーを使うコードは、認証を通らずには書けない |
| `schemas/` | DTO と FluentValidation | 入力用(`ProjectCreate`)と出力用(`ProjectOut`)を分ける。`extra="forbid"` で未知のフィールドを拒否する |
| `models.py` | EF Core のエンティティ | `Mapped[str]` がプロパティ、`mapped_column(...)` が Fluent API に当たる |
| `db.py` の `get_session` | `DbContext` を Scoped で登録 | リクエストごとに1セッション、成功したら commit、例外なら rollback。`SaveChangesAsync` を1か所にまとめた形 |
| `migrations/` | EF Migrations | `alembic revision --autogenerate` が `dotnet ef migrations add` に当たる。生成結果は必ず読む |
| `repositories/owned.py` | グローバルクエリフィルター | EF Core なら `HasQueryFilter` でテナントを絞るところ。ここでは「workspace_id を取らない取得関数を作らない」ことで同じ効果を出している |
| `core/errors.py` | `ProblemDetails` と例外フィルター | 例外クラスにステータスを持たせ、ハンドラで RFC 9457 の形に変換する |
| `worker/loop.py` | `BackgroundService` | 別プロセスで動く。API と同じコードを import して使う |
| `tests/conftest.py` | `WebApplicationFactory` + テスト用 DB | アプリをプロセス内で呼び、DB は本物の PostgreSQL。テストごとにトランザクションをロールバックする |

### EF Core と違って戸惑うところ

- **遅延読み込みがない。** async のセッションでは、読み込んでいない関連(`case.steps`)に触るとエラーになる。EF Core の `Include` に当たる `selectinload` を明示的に書く(`routers/runs.py` の `read_case_result`)
- **`flush` と `commit` は別。** `flush` は SQL を発行するがトランザクションは閉じない。採番された ID や DB 側の既定値が欲しいときに呼ぶ。EF Core の `SaveChanges` は両方を兼ねている
- **関連を定義しないと、INSERT の順序は保証されない。** `relationship()` で結んでいない2つのテーブルは、同じ `flush` の中でどちらが先に入るか決まらない。外部キーがあるなら、親を先に `flush` する

### `Depends` の読み方

```python
async def read_project(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> ProjectOut:
```

`PrincipalDep` は `Annotated[Principal, Depends(get_principal)]` の別名。FastAPI はリクエストごとに `get_principal` を呼び、その引数(`session`、`settings`)もまた `Depends` で解決する。コンストラクタインジェクションの連鎖と同じだが、登録するコンテナがなく、関数の引数をたどるだけで依存関係がわかる。

テストでは `app.dependency_overrides[get_session] = ...` で差し替える。`ConfigureTestServices` に当たる。

### SELECT ... FOR UPDATE SKIP LOCKED

worker がキューから1件取るときの SQL。`FOR UPDATE` は取得した行をロックし、`SKIP LOCKED` は他のトランザクションがロックしている行を飛ばす。複数の worker が同時に同じテーブルを見ても、同じ行を2回取ることがない。`tests/test_worker_concurrency.py` が、6つの worker に3件を取り合わせて確かめている。

## Phase 5 で出てきた具体例

Next.js の App Router。ASP.NET の経験からいちばん遠い部分で、「どのコードがどこで動くか」を意識する必要がある。

| 見るファイル | ASP.NET でいうと | 見どころ |
|---|---|---|
| `app/(app)/projects/page.tsx` | Razor Page の `OnGetAsync` + View | Server Component。サーバーで API を呼び、HTML を返す。ブラウザにはこのコードは送られない |
| `app/(app)/layout.tsx` | `_Layout.cshtml` + `[Authorize]` | 配下の全ページを包む。ここで `requireUser()` を呼ぶので、ログインしていなければページ本体は描画されない |
| `components/forms/project-form.tsx` | Blazor のコンポーネント | `"use client"` で始まる Client Component。状態(`useState`)とイベントはここにしか書けない |
| `lib/api/server.ts` と `lib/api/client.ts` | 型付き `HttpClient`(NSwag など) | OpenAPI から生成した型を使う。URL、パラメータ、レスポンスのすべてに型が付く |
| `components/run-poller.tsx` | SignalR を使うほどでもないポーリング | TanStack Query の `refetchInterval`。終わったら `router.refresh()` でサーバーに再描画させる |
| `proxy.ts` | ミドルウェア | ページの描画前に動く。ここでは未ログインをログイン画面へ送るだけ |
| `app/(app)/error.tsx` | 例外フィルター / エラーページ | 配下のページが描画中に例外を投げると、これが表示される |
| `e2e/migration-check.spec.ts` | Playwright for .NET | 実際のブラウザで、ログインから結果確認までを通す |

### Server Component と Client Component の境界

```
Server Component(既定)            Client Component("use client")
─────────────────────────         ─────────────────────────────
サーバーで実行される                  ブラウザで実行される(初回はサーバーでも描画)
await でデータを取れる                useState / useEffect / onClick が使える
Cookie を読める                      ブラウザの API(window など)を使える
状態もイベントも持てない              サーバーの秘密には触れない
```

Server Component から Client Component へは、props でデータを渡す。渡せるのは JSON にできる値だけで、関数は渡せない。`components/delete-button.tsx` が「何を消すか」を関数ではなくデータ(`{ kind: "rule", id }`)で受け取っているのは、このためである。

### React の state

Blazor の `@bind` のような双方向バインドはない。値は state に持ち、変えるときは setter を呼ぶ。setter を呼ぶと、そのコンポーネントの関数がもう一度実行されて、画面が作り直される。

```tsx
const [email, setEmail] = useState("");
<input value={email} onChange={(event) => setEmail(event.target.value)} />
```

`email = "x"` と直接書き換えても、画面は変わらない。再実行のきっかけがないからである。

### 数値が変わってしまう問題

`JSON.parse` は、すべての数値を 64 ビット浮動小数点数にする。`9007199254740993` は `9007199254740992` になり、`1.0` は `1` になる。C# なら `long` と `decimal` を使い分けるところである。

新旧の値の違いを見せるツールなので、これは困る。表示用の値はバックエンドから文字列でも送り(`old_text` / `new_text`)、テストケースの JSON は `lossless-json` で扱う(`lib/json.ts`)。レビューで指摘されて直した箇所である。

## Phase 6 で出てきた具体例

| 見るファイル | 見どころ |
|---|---|
| `ai/provider.py` | LLM に対するインターフェース。`Protocol` なので、実装側は継承を宣言しなくてよい |
| `ai/anthropic_provider.py` | SDK を import する唯一のファイル。構造化出力(JSON スキーマ)、拒否(`stop_reason == "refusal"`)の扱い、例外の変換 |
| `ai/prompt.py` | システムプロンプトと、回答の JSON スキーマ。プロンプトにはバージョンを付ける |
| `ai/analyzer.py` | 差異の要約 → モデル → 検証 → 保存。モデルの回答を「信用できない入力」として検証している |
| `ai/fake_provider.py` | テストとデモ用の実装。インターフェースがあるから、これを差し込める |
| `tests/test_ai.py` | 「モデルが何を言っても結果は変わらない」ことのテスト。プロンプトインジェクションを仕込んだレスポンスも使う |

### LLM を組み込むときの考え方

- **LLM は関数ではない。** 同じ入力に同じ出力を返す保証がない。だから、正しさが必要な判断(差異の検出、重大度)には使わず、説明にだけ使う
- **出力は検証する。** JSON スキーマで形を制約しても、中身(存在しない ID への回答など)は自分で確かめる
- **入力に指示が混ざる。** モデルに渡すデータの中に「これまでの指示を無視せよ」と書かれていることがある。防ぎきれないので、だまされても被害が出ない位置に置く
- **テストは2種類要る。** 「何が返ってきても壊れない」は単体テストで、「返ってくる内容が妥当」は評価セット(`apps/api/evals/`)で見る

### Embedding、Vector Search、RAG(このプロジェクトではまだ使っていない)

Roadmap の「仕様書 RAG」で使う予定の技術。ここまでの AI 分析は、差異そのものをモデルに渡しているだけで、検索はしていない。

- **Embedding**: 文章を数百〜数千個の数値の並び(ベクトル)に変換したもの。意味の近い文章は、ベクトルも近くなる
- **Vector Search**: 質問のベクトルに近いベクトルを持つ文章を探すこと。PostgreSQL では pgvector 拡張で行う
- **RAG**: 質問に関係のある文書を検索し、それをモデルに渡して答えさせる構成。モデルが知らない社内の仕様書を根拠に答えさせるときに使う

## Phase 7 で出てきた具体例

| 見るファイル | 見どころ |
|---|---|
| `infra/terraform/security.tf` | セキュリティグループ。誰が誰に接続できるかを、1ルール1リソースで書いてある |
| `infra/terraform/ecs.tf` | タスク定義(コンテナの設計図)とサービス(それを何個動かし続けるか) |
| `infra/terraform/iam.tf` | 実行ロールとタスクロールの違い。GitHub Actions からのデプロイを OIDC で許可する部分 |
| `infra/terraform/secrets.tf` | シークレットを Secrets Manager に置き、ECS がコンテナに環境変数として渡す |
| `.github/workflows/deploy.yml` | イメージをビルドして push し、タスク定義の新しいリビジョンを登録してサービスを切り替える |

Azure の経験があるなら、ECS Fargate は Container Apps、RDS は Azure Database for PostgreSQL、ALB は Application Gateway、Secrets Manager は Key Vault、IAM ロールはマネージド ID に近い。
