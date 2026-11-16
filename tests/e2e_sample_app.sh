#!/usr/bin/env bash
# End-to-end check of the templates against a real Spring Boot + JSP + HTMX app.
# Runs in CI (needs JDK 21, Maven, Node with playwright + htmx.org installed in the repo root).
# Steps: install templates -> ./mvnw verify -> Stop hook (pass + real compile failure)
#        -> start the app -> htmx-check.mjs (success, 422 re-render, escaping)
#        -> screen tests (framework installed from GitHub at the pinned commit) -> xlsx_patch on the generated results.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${RUNNER_TEMP:-$(mktemp -d)}/sample-app"
OUT="${E2E_OUTPUT:-$REPO/e2e-output}"
APP_PID=""

cleanup() {
  if [ -n "$APP_PID" ]; then
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

step() { printf '\n=== %s\n' "$*"; }

rm -rf "$WORK" && mkdir -p "$OUT" && cp -R "$REPO/tests/fixtures/sample-app" "$WORK"
cd "$WORK"

step "Generate Maven Wrapper"
mvn -B -q -N wrapper:wrapper -Dmaven=3.9.9
test -x ./mvnw

step "Install templates (dry run, then apply)"
python "$REPO/scripts/install.py" project "$WORK" --with-screen-tests
python "$REPO/scripts/install.py" project "$WORK" --with-screen-tests --apply
python "$REPO/scripts/install.py" project "$WORK" --with-screen-tests | tee "$OUT/install-second-run.txt"
grep -q 'create: 0, merge: 0' "$OUT/install-second-run.txt"
python scripts/sync_rules.py --check

step "./mvnw verify (JUnit + MockMvc)"
./mvnw -B -q verify

step "Stop hook: passing compile is silent"
hook_out="$(printf '%s\n' '{"stop_hook_active":false}' | python .claude/hooks/verify-stop.py)"
test -z "$hook_out"

step "Stop hook: real javac failure blocks with diagnostics"
cat > src/main/java/com/example/demo/Broken.java <<'JAVA'
package com.example.demo;
class Broken { MissingType value; }
JAVA
set +e
printf '%s\n' '{"stop_hook_active":false}' | python .claude/hooks/verify-stop.py 2> "$OUT/hook-failure.txt"
code=$?
set -e
rm src/main/java/com/example/demo/Broken.java
test "$code" -eq 2
grep -q 'MissingType' "$OUT/hook-failure.txt"

step "Start the app"
mkdir -p src/main/resources/static
cp "$REPO/node_modules/htmx.org/dist/htmx.min.js" src/main/resources/static/htmx.min.js
./mvnw -B -q spring-boot:run > "$OUT/app.log" 2>&1 &
APP_PID=$!
for _ in $(seq 1 90); do
  if curl -fsS http://localhost:8080/orders/new > /dev/null 2>&1; then break; fi
  if ! kill -0 "$APP_PID" 2>/dev/null; then cat "$OUT/app.log"; exit 1; fi
  sleep 2
done
curl -fsS http://localhost:8080/orders/new > /dev/null

# The app lives outside the repo; resolve playwright from the repo's node_modules.
export NODE_PATH="$REPO/node_modules${NODE_PATH:+:$NODE_PATH}"
check() { node scripts/htmx-check.mjs --url http://localhost:8080/orders/new --expect '#order-form' "$@"; }

step "htmx-check: successful submit"
check --fill '#name=テスト太郎' --click '#submit' --contains '登録しました：テスト太郎' \
  --screenshot "$OUT/success.png"

step "htmx-check: 422 validation error is re-rendered into the form"
check --click '#submit' --contains '名前を入力してください' --screenshot "$OUT/validation-422.png"

step "htmx-check: user input is escaped by c:out"
check --fill '#name=<b id="xss">x</b>' --click '#submit' --contains '登録しました：<b id="xss">x</b>' \
  --screenshot "$OUT/escaped.png"

step "htmx-check: a wrong expectation is reported as NG (exit 1)"
set +e
check --click '#submit' --contains '登録しました' --timeout 3000
code=$?
set -e
test "$code" -eq 1

step "screen tests: install the pinned framework"
cd "$WORK/screen-tests"
test -f package.json && test -f cases.mjs
npm install --no-audit --no-fund > "$OUT/screen-tests-npm.log" 2>&1 || { cat "$OUT/screen-tests-npm.log"; exit 1; }
export TEST_BROWSER_CHANNEL=chromium TEST_ENGINE=playwright
npx playwright install chromium > /dev/null

step "screen tests: case definitions and design-document coverage (no browser)"
npm run -s build | tee "$OUT/screen-tests-build.txt"
grep -q '設計書の 3 項目中 3 項目にケースあり' "$OUT/screen-tests-build.txt"

step "screen tests: run against the app"
npm test -s | tee "$OUT/screen-tests-run.txt"
grep -q '結果：3/3 OK' "$OUT/screen-tests-run.txt"
test -f 試験仕様書.xlsx && test -f 試験結果.xlsx && test -f 結果一覧.md && test -f out/junit.xml
# Committed outputs must not contain machine-specific absolute paths.
if grep -l "$WORK" 結果一覧.md 観点カバレッジ.md ./*.yaml; then echo "absolute path in a committed output" >&2; exit 1; fi
grep -q '設計書：\.\./docs/設計書\.md' 観点カバレッジ.md
cp 結果一覧.md report.html "$OUT/" 2>/dev/null || true

step "screen tests: a change the design document does not allow is reported as NG (exit 1)"
sed -i.bak "s/名前を入力してください'\]/お名前を入力してください']/" cases.mjs
set +e
npm test -s > "$OUT/screen-tests-ng.txt" 2>&1
code=$?
set -e
mv cases.mjs.bak cases.mjs
test "$code" -eq 1
grep -q 'O-01' "$OUT/screen-tests-ng.txt"

step "xlsx_patch: add a remark to the generated result workbook by case ID"
cd "$WORK"
cp screen-tests/試験結果.xlsx "$OUT/試験結果.before.xlsx"
cat > "$OUT/remark.json" <<'JSON'
{"sheet": "試験結果", "table": {"key": "ケースID", "rows": {"O-01": {"備考": "確認済み：必須チェック"}}}}
JSON
python scripts/xlsx_patch.py apply screen-tests/試験結果.xlsx "$OUT/remark.json" | tee "$OUT/xlsx-patch.txt"
grep -q '1 セルを変更しました' "$OUT/xlsx-patch.txt"
python scripts/xlsx_patch.py diff "$OUT/試験結果.before.xlsx" screen-tests/試験結果.xlsx --expect "$OUT/remark.json"

step "All end-to-end checks passed"
