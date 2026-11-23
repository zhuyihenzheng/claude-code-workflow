---
name: correct
description: 人から修正を指示されたとき、または同じレビュー指摘を 2 回受けたときに、その誤りを設計・型・guard のルール・テストのいずれかで機械的に止める手順。「/correct」「また同じ間違い」「ルールにして」「二度とやらないように」といった依頼時にも使用する。文章のルールを足すだけで終わらせない。
---

# 修正指示を決定的チェックに変える

前提：エージェントは開いたファイルしか見ず、近くにある実装を真似し、コンパイルが通る最短の方法を選ぶ。文章のルールはそれを止められない。止められるのは、誤りを書けなくする設計か、誤るとビルドや検査が失敗する仕組みだけである。

## 1. 誤りのクラスを特定する

- 今回の指摘を、同じ原因で起きる誤りの「クラス」として 1 文で書く（例：「Controller が Mapper を直接呼ぶ」「入力チェックの失敗を空の catch で無視する」）。
- 根拠を集める：会話での指摘、PR のレビューコメント、revert、`git log -S'<特徴的な文字列>'` で見つかる過去の同じ誤り。
- AGENTS.md や `.claude/rules/` に文章で書かれているのに起きた場合は再発である。文章を強めず、必ず次の段の 1〜4 で止める。

## 2. いちばん上の段で止める

上から順に検討し、できる段を選ぶ。下の段を選んだ場合は、上の段ができない理由を報告する。

1. **設計で消す**：正しい方法を 1 つにする（共通の Service、タグ、ユーティリティを用意し、古い方法を同じ変更で削除する）。パッケージの可視性で誤った依存を書けなくする。
2. **型とコンパイルで消す**：enum、値オブジェクト、`final`、コンストラクタの引数で、誤った状態を表現できなくする。
3. **検査ツールのルールにする**：誤りの種類で置き場所を選ぶ。
   - クラス間・層間の依存（どの層がどの層を使うか、どのアノテーションを禁止するか）：`src/test/java/ArchitectureTest.java`（ArchUnit）に `@ArchTest` のルールを追加し、`.because(...)` に直し方を書く。import 文を書かない同じパッケージ内の参照も止められる。
   - JSP の構文上の誤り（エスケープ漏れなど）：`config/pmd/jsp-ruleset.xml` に PMD の既存ルールを追加する（ルール一覧は PMD の JSP Rule Index）。`message` で直し方を上書きする。
   - それ以外の書き方の誤り（特定の API の呼び出し、コメント、テストの無効化など）：`config/guard/rules.json`（3 を参照）。
   ArchUnit と PMD は `./mvnw verify` で実行される。プロジェクトに未導入の場合（`config/quality/pom-snippet.xml` が pom.xml にない）は、guard のルールにして、導入を報告で提案する。
4. **テストにする**：振る舞いの誤りは、壊れたら失敗するテストにする。内部実装が変わっただけで失敗するテストにしない。
5. **文章にする**：判断が必要で機械化できないものだけ、AGENTS.md（チーム共通ルール）または `.claude/rules/` に短く書き、誤りの例を 1 つ添える。

## 3. guard のルールを書く

`config/guard/rules.json` の `rules` に 1 件追加する。

```json
{
  "id": "service-no-direct-now",
  "files": ["**/src/main/java/**/*.java"],
  "pattern": "\\bLocalDateTime\\.now\\(\\s*\\)",
  "message": "現在時刻は LocalDateTime.now() ではなく、注入した Clock から取得する（LocalDateTime.now(clock)）。",
  "origin": "2026-11-20 PR #123 のレビュー指摘",
  "examples": {
    "bad": ["order.setOrderedAt(LocalDateTime.now());"],
    "good": ["order.setOrderedAt(LocalDateTime.now(clock));"]
  }
}
```

- `files`：対象を必要な範囲に絞る。誤検知はルールへの信頼を壊し、例外の乱用を招く。
- `pattern`：Python の正規表現。ファイル全体に複数行モード（`^` と `$` は行頭と行末）で適用する。
- `message`：直し方を書く。何を使うか（クラス、タグ、メソッド）まで具体的にする。違反した行と一緒に表示されるため、これだけで直せる内容にする。
- `examples.bad`：**実際にあった誤り**をそのまま入れる（社名などの固有名は伏せる）。`examples.good`：正しい書き方と、誤検知しやすい紛らわしい例を入れる。
- `python scripts/guard.py --list` で一覧を、`python scripts/guard.py` で検査を実行する。examples が期待どおりに一致しない場合は終了コード 2 で止まるので、pattern を直す。

## 4. 既存コードの違反を片付ける

- 既存の違反が少なければ、同じ PR の別コミットで直す。古いパターンが残っていると、次のエージェントがそれを手本にする。
- 多い場合は、件数とファイルを報告し、人に既存の違反の受け入れを依頼する。エージェントは自分で受け入れない。
  - guard：`python scripts/guard.py --init-baseline`（確認が入る）。エージェントはベースラインを編集せず、`guard:allow` も書かない。
  - ArchUnit：ルールを `FreezingArchRule.freeze(...)` で包み、人が `./mvnw test -Dtest=ArchitectureTest -Darchunit.freeze.store.default.allowStoreCreation=true` を一度実行して記録をコミットする。
  - PMD：人が pom.xml の `maxAllowedViolations` を現在の件数にする。
  いずれも、以後は件数が縮小だけできる状態にする。
- 同じ形の修正が大量にある場合は、手で直さず、一括変換の道具（スクリプト、IDE の構造置換、OpenRewrite のレシピなど）を作るか使い、変換の前後で guard とテストが同じ結果になることを示す。OpenRewrite の Spring 向け・静的解析向けレシピは Moderne Source Available License であり、OSI のオープンソースではないため、組織の利用条件を確認してから使う。

## 5. 効くことを証明する

- 誤りがある状態（直す前のコミット、または誤りを一時的に戻した作業ツリー）で guard が終了コード 1 になり、直した状態で 0 になることを確認し、両方の出力を報告に貼る。
- CI と同じコマンド（`python scripts/guard.py`、`./mvnw verify`）を使う。ArchUnit と PMD の失敗も、出力の理由（`because` や `PMD Failure` の行）をそのまま貼る。

## 6. 台帳を更新する

- AGENTS.md の該当する規約の末尾に `〔guard: <id>〕`、`〔ArchUnit: <フィールド名>〕`、`〔PMD: <ルール名>〕` のいずれかを付ける。該当する規約がなければ、1 行で追加してタグを付ける。
- エラーメッセージだけで十分になった文章のルールは削除する。AGENTS.md は 150 行未満に保つ。
- 誤りが起きなくなった（設計で消えた）ルールは、ルールごと削除してよい。

## 報告

クラスごとに次を報告する：誤りの内容と根拠、選んだ段と上の段を選ばなかった理由、変更したファイル、guard の失敗時と成功時の出力、既存の違反の扱い（直した件数、またはベースライン登録の依頼）。
