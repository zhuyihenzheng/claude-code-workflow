#!/usr/bin/env node
// HTMX 画面の実ブラウザー検証（Playwright）。
// 画面を開く → 入力 → 操作 → 対象フラグメントの置換をアサーション →
// htmx エラーイベント／コンソールエラーがないことを確認 → スクリーンショットを保存する。
//
// 例：
//   node scripts/htmx-check.mjs --url http://localhost:8080/orders/new \
//     --fill "#name=テスト太郎" --click "#submit" \
//     --expect "#order-form" --contains "登録しました" --absent "ログイン" \
//     --screenshot target/htmx-check/order-success.png
//
// 終了コード：0 = 合格、1 = アサーション失敗、2 = 引数／起動エラー（検証未完了）。
// 1 回の実行で 1 つの操作を検証する。正常送信・入力チェックエラー・セッション失効は別々に実行する。
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { parseArgs } from 'node:util';

const HTMX_ERROR_EVENTS = [
  'htmx:targetError', 'htmx:responseError', 'htmx:swapError', 'htmx:sendError',
  'htmx:sendAbort', 'htmx:timeout', 'htmx:onLoadError', 'htmx:oobErrorNoTarget',
];

const HTTP_STATUS_LOG = /^Failed to load resource: the server responded with a status of \d+/;

const USAGE = `usage: node scripts/htmx-check.mjs --url URL --click SELECTOR --expect SELECTOR
         [--fill SELECTOR=VALUE]... [--contains TEXT] [--absent TEXT]...
         [--screenshot PATH] [--timeout MS] [--allow-console-error TEXT]...`;

class Incomplete extends Error {}

function fail(code, message) {
  console.error(message);
  process.exit(code);
}

function parseOptions(argv) {
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      options: {
        url: { type: 'string' },
        fill: { type: 'string', multiple: true, default: [] },
        click: { type: 'string' },
        expect: { type: 'string' },
        contains: { type: 'string' },
        absent: { type: 'string', multiple: true, default: [] },
        screenshot: { type: 'string' },
        timeout: { type: 'string', default: '10000' },
        'allow-console-error': { type: 'string', multiple: true, default: [] },
        help: { type: 'boolean', default: false },
      },
    }).values;
  } catch (error) {
    fail(2, `${error.message}\n${USAGE}`);
  }
  if (parsed.help) {
    console.log(USAGE);
    process.exit(0);
  }
  for (const key of ['url', 'click', 'expect']) {
    if (!parsed[key]) fail(2, `--${key} is required\n${USAGE}`);
  }
  const timeout = Number(parsed.timeout);
  if (!Number.isInteger(timeout) || timeout <= 0) fail(2, '--timeout must be a positive integer (ms)');
  const fills = parsed.fill.map((item) => {
    const index = item.indexOf('=');
    if (index <= 0) fail(2, `--fill expects SELECTOR=VALUE: ${item}`);
    return [item.slice(0, index), item.slice(index + 1)];
  });
  return { ...parsed, timeout, fills };
}

function loadPlaywright() {
  const require = createRequire(import.meta.url);
  try {
    return require('playwright');
  } catch {
    fail(2, '検証未完了：playwright が見つかりません。'
      + '`npm install --no-save playwright` と `npx playwright install chromium` を実行してください。');
  }
}

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const { chromium } = loadPlaywright();
  let browser;
  try {
    browser = await chromium.launch(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {});
  } catch (error) {
    fail(2, `検証未完了：ブラウザーを起動できません：${error.message.split('\n')[0]}`);
  }

  const problems = [];
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(options.timeout);
    const consoleErrors = [];
    page.on('console', (message) => {
      // Chromium logs every 4xx/5xx response as a console error. Whether htmx treats
      // the status as an error is checked via htmx:responseError instead, so an
      // intended 422 re-render is not reported twice; net::ERR_* failures still count.
      if (message.type() === 'error' && !HTTP_STATUS_LOG.test(message.text())) consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`));
    await page.addInitScript((events) => {
      window.__htmxCheckErrors = [];
      window.__htmxCheckSwaps = 0;
      document.addEventListener('htmx:afterSwap', () => { window.__htmxCheckSwaps += 1; }, true);
      for (const name of events) {
        document.addEventListener(name, (event) => {
          const target = event.target && event.target.id ? `#${event.target.id}` : '';
          window.__htmxCheckErrors.push(`${name}${target ? ` on ${target}` : ''}`);
        }, true);
      }
    }, HTMX_ERROR_EVENTS);

    let response;
    try {
      response = await page.goto(options.url, { waitUntil: 'load' });
    } catch (error) {
      throw new Incomplete(`検証未完了：画面を開けません（サービスは起動していますか）：${error.message.split('\n')[0]}`);
    }
    if (response && !response.ok()) problems.push(`初期表示が HTTP ${response.status()}`);
    if (!(await page.evaluate(() => typeof window.htmx !== 'undefined'))) {
      problems.push('window.htmx が未定義（HTMX が読み込まれていない）');
    }

    const target = page.locator(options.expect);
    if ((await target.count()) !== 1) {
      problems.push(`--expect ${options.expect} が操作前に 1 件ではない（${await target.count()} 件）`);
    }
    const before = problems.length ? null : await target.innerHTML();

    if (!problems.length) {
      for (const selector of [...options.fills.map(([fill]) => fill), options.click]) {
        if ((await page.locator(selector).count()) === 0) problems.push(`操作対象 ${selector} が画面にない`);
      }
    }

    if (!problems.length) {
      for (const [selector, value] of options.fills) await page.fill(selector, value);
      await page.evaluate(() => { window.__htmxCheckSwaps = 0; });
      await page.click(options.click);
      try {
        // A swap must happen (htmx:afterSwap or changed content) so that text that was
        // already on the page before the click cannot make a broken request pass.
        await page.waitForFunction(({ selector, contains, before }) => {
          const element = document.querySelector(selector);
          if (!element) return false;
          const swapped = window.__htmxCheckSwaps > 0 || element.innerHTML !== before;
          return swapped && (contains === undefined || element.textContent.includes(contains));
        }, { selector: options.expect, contains: options.contains, before }, { timeout: options.timeout });
      } catch {
        problems.push(options.contains === undefined
          ? `${options.expect} の内容が ${options.timeout}ms 以内に置換されなかった`
          : `${options.expect} が ${options.timeout}ms 以内に置換されず、または「${options.contains}」が表示されなかった`);
      }
      // Let htmx settle and late events/console messages arrive.
      await page.waitForTimeout(300);
      const text = (await page.locator(options.expect).count()) ? await page.locator(options.expect).textContent() : '';
      for (const absent of options.absent) {
        if (text.includes(absent)) problems.push(`${options.expect} に表示されてはいけない「${absent}」がある`);
      }
    }

    for (const error of await page.evaluate(() => window.__htmxCheckErrors)) problems.push(`HTMX エラーイベント：${error}`);
    for (const error of consoleErrors) {
      if (!options['allow-console-error'].some((allowed) => error.includes(allowed))) {
        problems.push(`コンソールエラー：${error}`);
      }
    }

    if (options.screenshot) {
      mkdirSync(dirname(options.screenshot), { recursive: true });
      await page.screenshot({ path: options.screenshot, fullPage: true });
      console.log(`スクリーンショット：${options.screenshot}`);
    }
  } finally {
    await browser.close();
  }

  if (problems.length) {
    console.error(`NG：${options.url}`);
    for (const problem of problems) console.error(`  - ${problem}`);
    process.exit(1);
  }
  console.log(`OK：${options.url}（${options.click} → ${options.expect}）`);
}

main().catch((error) => fail(2, error instanceof Incomplete ? error.message : `検証未完了：${error.stack || error}`));
