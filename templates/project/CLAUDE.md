@AGENTS.md

# Claude Code 固有の補足

- レビュー：実装の完了後、PR の作成前に `code-reviewer` サブエージェントを呼び出す。このエージェントは Bash を使用できないため、比較元のコミット、完全な diff（ステージ済み・未ステージ・新規ファイル）、受入条件、テスト結果を渡す。
- Excel 設計書：`.xlsx` / `.xlsm` の Read は deny されている。`specs-ai/` が存在しない、または古い場合は `python scripts/xlsx2ai.py` で再生成する（Python 3.11+、初回のみ `pip install "exstruct==0.9.0" "excel2md==2.3.0"`）。
- 権限：マイグレーションの編集には確認（ask）が入る。deny／ask で止められた操作は別の手段で回避せず、理由を報告する。
- 設定ファイルの構成と変更手順は `.claude/README.md`（人向けの説明）に記載している。設定を変更する場合のみ参照する。
