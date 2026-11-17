// サンプルアプリ（注文登録）：画面試験のサイト設定
import { createLocators, DEFAULTS } from 'midscene-poc/core/locators.mjs';
import { here } from 'midscene-poc/core/paths.mjs';

const DIR = here(import.meta.url);
const URL0 = process.env.SAMPLE_APP_URL || 'http://localhost:8080/';

export default {
  name: 'sample-app', dir: DIR, url: URL0, viewport: { width: 1280, height: 1000 }, cookieFile: DIR + 'out/session-cookie.json',
  locators: createLocators(DEFAULTS),
  design: DIR + '../docs/設計書.md',
  // ログインのないアプリ。最初の画面を開くだけ
  async login(browser, { viewport } = {}) {
    const context = await browser.newContext({ viewport, locale: 'ja-JP' });
    const page = await context.newPage();
    await page.goto(URL0 + 'orders/new');
    return { context, page };
  },
  explore: { flows: [] },
};
