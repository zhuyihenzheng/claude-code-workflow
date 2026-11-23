"""Write the sample app's design document (tests/fixtures/sample-app/docs/設計書.md) as an Excel workbook.

The layout imitates a typical Japanese grid ("方眼紙") design document: narrow columns, merged
cells for labels and values, section titles in their own row and indented prose. The end-to-end
test converts it with xlsx2ai.py and checks that the screen tests find the same design items as
in the Markdown original.

    python tests/make_sample_design_xlsx.py specs/設計書.xlsx
"""
import sys
from pathlib import Path

import openpyxl


def put(ws, row, col, value, span=1):
    ws.cell(row=row, column=col, value=value)
    if span > 1:
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)


def main(out):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '注文登録'
    for col in range(1, 41):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 3
    put(ws, 1, 1, 'システム名', 4)
    put(ws, 1, 5, '注文登録（サンプル）', 10)
    put(ws, 1, 25, '作成者', 3)
    put(ws, 1, 28, 'サンプル', 6)
    put(ws, 3, 2, '■ 画面一覧', 10)
    for col, label, span in ((2, '画面ID', 3), (5, '画面名', 8), (13, 'URL', 10)):
        put(ws, 4, col, label, span)
    for col, value, span in ((2, 'S01', 3), (5, '注文登録', 8), (13, '/orders/new', 10)):
        put(ws, 5, col, value, span)
    put(ws, 7, 2, '■ S01 注文登録', 10)
    put(ws, 8, 3, '項目', 5)
    put(ws, 8, 8, '規則', 8)
    put(ws, 9, 3, '名前', 5)
    put(ws, 9, 8, '必須', 8)
    put(ws, 11, 3, '〈登録〉を押すと、フォームの領域だけを置き換える（画面全体は再読み込みしない）。', 30)
    put(ws, 13, 3, '条件', 6)
    put(ws, 13, 9, 'メッセージ', 14)
    put(ws, 14, 3, '名前が未入力', 6)
    put(ws, 14, 9, '名前を入力してください', 14)
    put(ws, 15, 3, '登録成功', 6)
    put(ws, 15, 9, '登録しました：{名前}', 14)
    put(ws, 17, 3, '入力エラーの場合は、入力済みの値を保持したままフォームを再表示する。', 30)
    put(ws, 18, 3, '入力値は HTML として解釈しない。', 30)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


if __name__ == '__main__':
    main(sys.argv[1])
