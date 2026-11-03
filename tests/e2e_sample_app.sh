#!/usr/bin/env bash
# End-to-end check of the templates against a real Spring Boot + JSP + HTMX app.
# Runs in CI (needs JDK 21, Maven, Node with playwright + htmx.org installed in the repo root).
# Steps: install templates -> ./mvnw verify -> Stop hook (pass + real compile failure)
#        -> start the app -> htmx-check.mjs (success, 422 re-render, escaping).
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
python "$REPO/scripts/install.py" project "$WORK"
python "$REPO/scripts/install.py" project "$WORK" --apply
python "$REPO/scripts/install.py" project "$WORK" | tee "$OUT/install-second-run.txt"
grep -q 'create: 0, merge: 0' "$OUT/install-second-run.txt"
python scripts/sync_rules.py . --check

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

step "All end-to-end checks passed"
