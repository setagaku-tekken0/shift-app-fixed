import streamlit as st
import gspread
import pandas as pd
from shift_logic import create_shift  # シフト作成のロジックが書かれたファイルを読み込みます

# 1. Googleスプレッドシートへの接続設定（Secretsから合鍵を読み込む）
try:
    credentials = st.secrets["gcp_service_account"]
    gc = gspread.service_account_from_dict(credentials)
except Exception as e:
    st.error("Googleの合鍵（Secrets）が正しく設定されていないか、形式が違います。")
    st.stop()

# 2. 画面のタイトル
st.title("📅 シフト表自動作成システム")
st.write("GoogleスプレッドシートのURLを入力して、シフトを自動作成します。")

# 3. 【今回のポイント】URLの入力欄を作る
spreadsheet_url = st.text_input(
    "GoogleスプレッドシートのURLを貼り付けてください：",
    placeholder="https://docs.google.com/spreadsheets/d/..."
)

# 4. シフト作成ボタン
if st.button("🚀 シフト表を自動作成する"):
    if not spreadsheet_url:
        st.warning("スプレッドシートのURLを入力してください。")
    else:
        with st.spinner("スプレッドシートを読み込んでシフトを計算中... ⏳"):
            try:
                # 入力されたURLを開く
                sh = gc.open_by_url(spreadsheet_url)
                
                # --- ここからColabでやっていた処理を呼び出す ---
                # 例として、shift_logic.py の中にある関数を実行する形にしています
                # お使いの関数名や引数に合わせて調整してください
                result_df = create_shift(sh)
                # --------------------------------------------
                
                st.success("🎉 シフト表の作成が完了しました！")
                
                # 画面に結果を表示
                st.subheader("作成されたシフト表")
                st.dataframe(result_df)
                
                # ExcelやCSVとしてダウンロードできるボタンもオマケで設置
                csv = result_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 結果をCSVとしてダウンロード",
                    data=csv,
                    file_name="generated_shift.csv",
                    mime="text/csv"
                )
                
            except gspread.exceptions.SpreadsheetNotFound:
                st.error("スプレッドシートが見つかりません。URLが正しいか、またはロボットのメールアドレス（shift-bot@...）が共有されているか確認してください。")
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
