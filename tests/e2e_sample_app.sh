#!/usr/bin/env bash
# End-to-end check of the templates against a real Spring Boot + JSP + HTMX app.
# Runs in CI (needs JDK 21, Maven, Node with playwright + htmx.org installed in the repo root).
# Steps: install templates -> guard (pass + real past mistakes) -> ./mvnw verify (JUnit, ArchUnit, PMD on JSP)
#        -> unit test record from the JUnit results -> project knowledge is current -> what guard cannot see: ArchUnit and PMD catch it -> Stop hook (pass + real compile failure)
#        -> start the app -> htmx-check.mjs (success, 422 re-render, escaping) -> feature map recipes
#        -> screen tests, also against an Excel design document converted to Markdown by xlsx2ai.py
#        -> screen tests (framework installed from GitHub at the pinned commit) -> xlsx_patch on the generated results.
set -euo pipefail
# Rule messages are Japanese; Maven and the forked test JVM print them in the locale's encoding.
export LC_ALL=C.UTF-8 LANG=C.UTF-8

REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/workflow-sample.XXXXXXXX")/sample-app"
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

mkdir -p "$OUT" && cp -R "$REPO/tests/fixtures/sample-app" "$WORK"
cd "$WORK"

step "Generate Maven Wrapper"
mvn -B -q -N wrapper:wrapper -Dmaven=3.9.9
test -x ./mvnw

step "Install templates (dry run, then apply)"
python "$REPO/scripts/install.py" project "$WORK" --with-screen-tests --with-archunit
python "$REPO/scripts/install.py" project "$WORK" --with-screen-tests --with-archunit --apply
python "$REPO/scripts/install.py" project "$WORK" --with-screen-tests --with-archunit | tee "$OUT/install-second-run.txt"
grep -q 'create: 0, merge: 0' "$OUT/install-second-run.txt"
python scripts/sync_rules.py --check

step "guard: the sample app passes the template rules"
python scripts/guard.py | tee "$OUT/guard-pass.txt"
grep -q 'guard: OK' "$OUT/guard-pass.txt"

step "guard: a mapper injected into a controller and a scriptlet fail with their fix (exit 1)"
CONTROLLER=src/main/java/com/example/demo/OrderController.java
RESULT_JSP=src/main/webapp/WEB-INF/jsp/fragments/order-result.jsp
cp "$CONTROLLER" "$OUT/OrderController.java.orig" && cp "$RESULT_JSP" "$OUT/order-result.jsp.orig"
sed -i.bak -e 's/^import jakarta.servlet.http.HttpServletResponse;/import com.example.demo.mapper.OrderMapper;\
&/' \
  -e 's/^public class OrderController {/&\
    @Autowired\
    private OrderMapper orderMapper;/' "$CONTROLLER"
printf '%s\n' '<p><%= request.getParameter("name") %></p>' >> "$RESULT_JSP"
set +e
python scripts/guard.py > "$OUT/guard-fail.txt"
code=$?
set -e
cat "$OUT/guard-fail.txt"
test "$code" -eq 1
grep -q "^$CONTROLLER:3: \[controller-no-persistence\] " "$OUT/guard-fail.txt"
grep -q "^$CONTROLLER:15: \[java-no-field-injection\] .*コンストラクタの引数で受け取る" "$OUT/guard-fail.txt"
grep -q "^$RESULT_JSP:[0-9]*: \[jsp-no-scriptlet\] " "$OUT/guard-fail.txt"
cp "$OUT/OrderController.java.orig" "$CONTROLLER" && cp "$OUT/order-result.jsp.orig" "$RESULT_JSP"
python scripts/guard.py > /dev/null

step "./mvnw verify (JUnit + MockMvc, ArchUnit, PMD on JSP)"
./mvnw -B -q verify
grep -q 'tests="3"' target/surefire-reports/TEST-ArchitectureTest.xml

step "Unit test report: the JUnit results and @DisplayName become the test record (Markdown and Excel)"
python scripts/junit_report.py --title 注文サンプル | tee "$OUT/junit-report.txt"
grep -q '| 判定 | 合格 |' target/test-report/単体テスト成績書.md
grep -q '| S01 注文登録（OrderControllerTest） | 名前が空白のとき、422 とフォームのフラグメントを返す |' target/test-report/単体テスト成績書.md
test -s target/test-report/単体テスト成績書.xlsx
cp target/test-report/単体テスト成績書.* "$OUT/"

step "Project knowledge: the code map and glossary point at files and features that exist"
python scripts/knowledge_check.py | tee "$OUT/knowledge.txt"
grep -q 'knowledge: OK（2 ファイル）' "$OUT/knowledge.txt"

step "ArchUnit: a same-package repository used by the controller passes guard but fails the layer rule"
cp "$CONTROLLER" "$OUT/OrderController.java.orig"
printf '%s\n' 'package com.example.demo;' '' 'class OrderRepository {' '    void save(String name) {' '    }' '}' \
  > src/main/java/com/example/demo/OrderRepository.java
sed -i.bak -e 's/^public class OrderController {/&\
\
    private final OrderRepository repository = new OrderRepository();/' \
  -e 's/^        return "fragments\/order-result";/        repository.save(name);\
&/' "$CONTROLLER"
python scripts/guard.py > "$OUT/guard-same-package.txt"
set +e
./mvnw -B test -Dtest=ArchitectureTest > "$OUT/archunit-fail.txt" 2>&1
code=$?
set -e
test "$code" -ne 0
grep -q 'controllers_do_not_use_persistence' "$OUT/archunit-fail.txt"
grep -q 'Service のメソッドとして追加し' "$OUT/archunit-fail.txt"
grep -q 'OrderRepository.save' "$OUT/archunit-fail.txt"
rm src/main/java/com/example/demo/OrderRepository.java
cp "$OUT/OrderController.java.orig" "$CONTROLLER"

step "PMD: unescaped EL in a JSP fails verify with the fix"
printf '%s\n' '<p class="echo">${name}</p>' >> "$RESULT_JSP"
set +e
./mvnw -B pmd:check@jsp-xss > "$OUT/pmd-fail.txt" 2>&1
code=$?
set -e
test "$code" -ne 0
grep -q 'PMD Failure: order-result.jsp:4 Rule:NoUnsanitizedJSPExpression' "$OUT/pmd-fail.txt"
grep -q 'fn:escapeXml' "$OUT/pmd-fail.txt"
cp "$OUT/order-result.jsp.orig" "$RESULT_JSP"
./mvnw -B -q pmd:check@jsp-xss

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

step "feature map: every recipe in docs/feature-map runs and leaves its evidence"
grep -ho '`node scripts/htmx-check.mjs [^`]*`' docs/feature-map/*.md | tr -d '`' > "$OUT/feature-map-recipes.txt"
test "$(wc -l < "$OUT/feature-map-recipes.txt")" -ge 3
while IFS= read -r recipe; do
  printf '+ %s\n' "$recipe"
  eval "$recipe"
done < "$OUT/feature-map-recipes.txt"
test -f target/evidence/S01/S01-1.png && test -f target/evidence/S01/S01-2.png && test -f target/evidence/S01/S01-3.png
cp -R target/evidence "$OUT/feature-map-evidence"

step "screen tests: install the pinned framework"
cd "$WORK/screen-tests"
test -f package.json && test -f cases.mjs
npm install --no-audit --no-fund > "$OUT/screen-tests-npm.log" 2>&1 || { cat "$OUT/screen-tests-npm.log"; exit 1; }
export TEST_BROWSER_CHANNEL=chromium TEST_ENGINE=playwright
npx playwright install chromium > /dev/null
# What the installed README points at must really be in the installed package.
test -f node_modules/midscene-poc/.github/instructions/site-tests.instructions.md

step "screen tests: the scaffold command works after a real install"
npx screen-test-new-site probe --dir scaffold-probe --url http://localhost:8080/ > "$OUT/screen-tests-scaffold.txt"
grep -q "from 'midscene-poc/core/" scaffold-probe/site.mjs
node scaffold-probe/run.mjs --engine playwright --build-only > /dev/null

step "screen tests: case definitions and design-document coverage (no browser)"
node run.mjs --engine playwright --build-only | tee "$OUT/screen-tests-build.txt"
grep -q '設計書の 3 項目中 3 項目にケースあり' "$OUT/screen-tests-build.txt"

step "screen tests: an Excel design document converted by xlsx2ai gives the same coverage"
(cd "$WORK" && python "$REPO/tests/make_sample_design_xlsx.py" specs/設計書.xlsx && python scripts/xlsx2ai.py)
EXCEL_MD="$WORK/specs-ai/設計書/sheets/注文登録.md"
cp "$EXCEL_MD" "$OUT/excel-design.md"
grep -q '^| 条件 | メッセージ |$' "$EXCEL_MD"
cp site.mjs "$OUT/site.mjs.orig"
sed -i.bak "s#design: DIR + '../docs/設計書.md'#design: DIR + '../specs-ai/設計書/sheets/注文登録.md'#" site.mjs
grep -q "specs-ai/設計書/sheets/注文登録.md" site.mjs
node run.mjs --engine playwright --build-only | tee "$OUT/screen-tests-build-excel.txt"
grep -q '設計書の 3 項目中 3 項目にケースあり' "$OUT/screen-tests-build-excel.txt"
cp "$OUT/site.mjs.orig" site.mjs

step "screen tests: run against the app"
node run.mjs --engine playwright | tee "$OUT/screen-tests-run.txt"
grep -q '結果：3/3 OK' "$OUT/screen-tests-run.txt"
test -f 試験仕様書.xlsx && test -f 試験結果.xlsx && test -f 結果一覧.md && test -f out/junit.xml
# Committed outputs must not contain machine-specific absolute paths.
if grep -l "$WORK" 結果一覧.md 観点カバレッジ.md ./*.yaml; then echo "absolute path in a committed output" >&2; exit 1; fi
grep -q '設計書：\.\./docs/設計書\.md' 観点カバレッジ.md
cp 結果一覧.md report.html "$OUT/" 2>/dev/null || true

step "screen tests: a change the design document does not allow is reported as NG (exit 1)"
sed -i.bak "s/名前を入力してください'\]/お名前を入力してください']/" cases.mjs
set +e
node run.mjs --engine playwright > "$OUT/screen-tests-ng.txt" 2>&1
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
