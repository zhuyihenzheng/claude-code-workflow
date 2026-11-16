// サンプルアプリ（注文登録）画面試験：ケース定義。期待値は docs/設計書.md による
import { makeState, go, shot } from 'midscene-poc/core/steps.mjs';

// 完了メッセージ（#done）はこの画面固有の読み取り位置
const state = makeState({ extra: { done: '#done' } });
const shown = text => ({ aiWaitFor: `「${text}」と表示されている`, timeout: 15000 });

export const SUITES = [
{
  file: '01-order', title: 'S01 注文登録', cases: [
  { id: 'O-01', screen: 'S01 注文登録', kind: '必須チェック', title: '名前が未入力のまま〈登録〉',
    steps: '1. 何も入力せず〈登録〉', expect: '「名前を入力してください」と表示される。注文登録画面のまま。',
    flow: [...go('/orders/new', '注文登録'), { aiTap: '「登録」ボタン' }, shown('名前を入力してください'), state('O01'), shot('O-01 必須エラー')],
    verify: [
      ['名前の必須エラー', 'O01.errors.name', '名前を入力してください'],
      ['注文登録画面のまま', 'O01.title', '注文登録']] },

  { id: 'O-02', screen: 'S01 注文登録', kind: '正常系', title: '名前を入力して〈登録〉',
    steps: '1. 名前「テスト太郎」\n2. 〈登録〉', expect: '「登録しました：テスト太郎」と表示される。',
    flow: [...go('/orders/new', '注文登録'), { aiInput: '名前の入力欄', value: 'テスト太郎' }, { aiTap: '「登録」ボタン' },
      shown('登録しました：テスト太郎'), state('O02'), shot('O-02 登録完了')],
    verify: [
      ['完了メッセージ', 'O02.done', '登録しました：テスト太郎']] },

  { id: 'O-03', screen: 'S01 注文登録', kind: '異常系', title: 'HTML を含む名前はそのまま文字として表示',
    steps: '1. 名前「<b>x</b>」\n2. 〈登録〉', expect: '「登録しました：<b>x</b>」と表示される（太字にならない）。',
    flow: [...go('/orders/new', '注文登録'), { aiInput: '名前の入力欄', value: '<b>x</b>' }, { aiTap: '「登録」ボタン' },
      shown('登録しました：<b>x</b>'), state('O03'), shot('O-03 エスケープ')],
    verify: [
      ['入力値を HTML として解釈しない', 'O03.done', '登録しました：<b>x</b>']] },
  ] },
];
