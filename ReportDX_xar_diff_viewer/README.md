帳票DX テンプレート差分ビューア（Markdown & Excel レポート対応）

オプロ帳票DXの .xar テンプレート同士の差分を比較し、
Markdownレポート と Excelレポート（.xlsx） を生成できる Streamlit アプリです。

🔧 主な機能
	•	.xar → .xat の JSON 構造を解析
	•	追加・削除・変更オブジェクトの検出
	•	変更箇所は 重大(🔴) / 中(🟡) / 軽微(🟢) の色分け分類
	•	詳細な diff を HTML 表示
	•	Markdown レポート出力
	•	Excel レポート出力（複数シート構成）

📦 必要ライブラリ
streamlit
pandas
xlsxwriter

🚀 実行方法
1. 仮想環境（任意）
python -m venv venv
source venv/bin/activate

2. インストール
pip install -r requirements.txt

3. 起動
streamlit run ReportDX_xar_diff_viewer.py
