@AGENTS.md

# Claude Code の設定ガイド

- パス別ルール：`.claude/rules/jsp.md`、`.claude/rules/htmx.md` は `paths:` で適用対象を限定する。該当ファイルの読み取り時にも読み込まれる場合がある。
- サブエージェント：`.claude/agents/code-reviewer.md` は読み取り専用でレビューを行う。呼び出し時には、比較元のコミット、完全な diff、受入条件、テスト結果を渡す。
- Skill：`.claude/skills/spring-endpoint/SKILL.md` にエンドポイント／画面フラグメントの追加手順を定義している。タスクに応じて使用する。
- Settings/permissions：チーム設定は `.claude/settings.json`、個人の上書き設定は `.claude/settings.local.json`（リポジトリ管理対象外）に記載する。プロジェクトルート／worktree ルートから起動し、`/permissions` で有効な権限を確認する。
- settings のパス別ルールはプロセスの隔離を保証しない。Bash スクリプト、MCP、hooks の権限は別途管理する。マイグレーションのディレクトリには ask を使用し、新規追加時にも確認を必要とする。
- Hooks：このテンプレートでは hooks を有効にしておらず、セッション終了時の自動コンパイルは行わない。`.claude/hooks/verify-stop.py` は macOS/Linux/WSL 向けの任意の参考サンプルであり、有効にする場合は Stop への登録が必要。ネイティブ Windows では書き換えが必要となる。
- MCP：必要に応じて `.mcp.json` をマージし、`/mcp` で接続を確認する。使用しないサーバーは削除し、API キー・秘密鍵などの認証情報は環境変数で渡す。
