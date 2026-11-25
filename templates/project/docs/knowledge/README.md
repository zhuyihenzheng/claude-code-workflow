# プロジェクト知識

作業のたびに確かめた事実を書き戻し、次の作業で同じ調査を繰り返さないための記録である。人もエージェント（Claude Code、GitHub Copilot）も同じファイルを読む。更新の手順は `.claude/skills/knowledge/SKILL.md`（`knowledge` skill）に記載している。

- **作業の最初に読む**：依頼の言葉は `glossary.md` で画面の項目名・コード上の名前に置き換え、修正箇所は `codemap.md` の機能 ID から引く。記載と実際のコードが違えば、コードが正しい。記載を直す。
- **作業の最後に書き戻す**：今回の作業で確かめた事実だけを書く。推測、作業の経過、顧客情報・認証情報は書かない。
- **古い記載を残さない**：`python scripts/knowledge_check.py` が、存在しないパス、機能マップにない機能 ID、重複した用語を報告する（CI でも実行する）。

ここに書かないもの：規約（`AGENTS.md`）、機械で止められる誤り（`correct` skill で guard・ArchUnit・PMD・テストにする）、利用者から見た機能の手順（`docs/feature-map/`）。

## glossary.md（用語集）

依頼・設計書で使われる業務の言葉と、画面・コード・データベースでの名前の対応である。1 用語 1 行、1 列目の用語は重複させない。

```markdown
# 用語集

| 用語 | 意味 | 画面・設計書での表記 | コード・DB での名前 |
|---|---|---|---|
| 受注 | 顧客からの注文を登録した状態 | 「注文登録」画面（S01） | `Order`、`t_order` |
| 締め | 月末に当月分の受注を確定する処理 | 「月次締め」 | `ClosingService#closeMonth` |
```

## codemap.md（コードマップ）

機能マップの機能 ID ごとに、実装と資料の場所、変更時の注意点を書く。見出しは `## <機能ID> <機能名>`（機能 ID は `docs/feature-map/` に存在するもの）。パスはリポジトリのルートからの相対パスをコードスパンで書き、ファイルは拡張子まで、フォルダは末尾に `/` を付ける（`knowledge_check.py` が存在を確認する）。

```markdown
# コードマップ

## S01 注文登録

- 画面：`src/main/webapp/WEB-INF/jsp/orders/new.jsp`、フラグメント `src/main/webapp/WEB-INF/jsp/fragments/order-form.jsp`
- Controller：`src/main/java/com/example/order/OrderController.java`（`create`）
- 設計書：`specs-ai/注文/sheets/S01 注文登録.md`
- テスト：`src/test/java/com/example/order/OrderControllerTest.java`、画面試験のスイート `S01`
- 注意：入力チェックのエラーは 422 + フォームのフラグメントで返す。画面全体を返すとフォームの中にページ全体が入る。
```
