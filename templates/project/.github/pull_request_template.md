## 変更内容

<!-- 何を、なぜ変えたか。設計書の該当箇所、関連する課題 -->

## 検証の証跡

レビューは diff より先にここを確認する。「確認しました」ではなく、実行したコマンドと結果を記載する。

- `python scripts/guard.py`：
- `./mvnw verify`：
- 単体テスト成績書（`python scripts/junit_report.py` の出力先）：
- 設計書との一致（`python scripts/spec_sync.py`。設計書を変えた場合）：
- 画面（`docs/feature-map/` の機能 ID と手順、スクリーンショットまたは `結果一覧.md`）：
- 実施していない検証とその理由：

## 再発防止

<!-- 修正指示やレビュー指摘を受けて追加したもの（guard のルール ID、設計の変更、テスト）。なければ「なし」 -->

## プロジェクト知識

- [ ] `docs/knowledge/` に今回確かめた事実を書き戻した（または書き戻すものがない）。`python scripts/knowledge_check.py`：

## 例外とベースライン

- [ ] `config/guard/allow.json` に例外を追加していない（追加した場合：ルール ID、期限、承認者、理由）
- [ ] `config/guard/baseline.json` の件数を増やしていない
