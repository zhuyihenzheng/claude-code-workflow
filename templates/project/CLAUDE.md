@AGENTS.md

# Claude Code 固有の補足

- レビュー：実装の完了後、PR の作成前に `code-reviewer` サブエージェントを呼び出す。このエージェントは Bash を使用できないため、比較元のコミット、完全な diff（ステージ済み・未ステージ・新規ファイル）、受入条件、テスト結果、`python scripts/guard.py` の出力、画面の証跡（機能マップの ID とスクリーンショットの保存先）を渡す。
- 修正指示：人から修正を指示された、または同じレビュー指摘を 2 回受けたら、直したうえで `correct` skill を実行し、同じ誤りを設計・型・guard のルール・テストのいずれかで止める。
- 機能マップ：`docs/feature-map/` がない、または変更した画面の項目がない場合は `feature-map` skill で作成・更新する。
- Excel 設計書：`.xlsx` / `.xlsm` の Read は deny されている。`specs-ai/` が存在しない、または古い場合は `python scripts/xlsx2ai.py` で再生成する（Python 3.11+、初回のみ `pip install "exstruct==0.9.0" "excel2md==2.3.0"`）。
- 権限：マイグレーションの編集には確認（ask）が入る。deny／ask で止められた操作は別の手段で回避せず、理由を報告する。
- 設定ファイルの構成と変更手順は `.claude/README.md`（人向けの説明）に記載している。設定を変更する場合のみ参照する。
