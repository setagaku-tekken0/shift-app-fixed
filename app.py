import streamlit as st
import gspread
from shift_logic import create_shift, START_OPTIONS, END_OPTIONS, ALL_TIME_SLOTS

# 1. ページの設定
st.set_page_config(page_title="シフト表自動作成システム", layout="wide")

# 2. Googleの合鍵（Secrets）チェック
try:
    credentials = st.secrets["gcp_service_account"]
    gc = gspread.service_account_from_dict(credentials)
except Exception as e:
    st.error("🔒 Googleの合鍵（Secrets）が正しく設定されていないか、形式が違います。Streamlitの管理画面でSecretsをご確認ください。")
    st.stop()

# 3. アプリタイトル
st.title("📅 シフト表自動作成システム")
st.markdown("---")

# 左右2カラムに分けてフォームをすっきり配置
col_left, col_right = st.columns(2)

with col_left:
    st.header("⚙️ 1. 基本条件設定")
    spreadsheet_url = st.text_input(
        "スプレッドシートのURLを貼り付けてください：",
        placeholder="https://docs.google.com/spreadsheets/d/..."
    )
    
    # 時間選択
    c1, c2 = st.columns(2)
    with c1:
        start_time = st.selectbox("イベント開始時間:", START_OPTIONS, index=0)
    with c2:
        end_time = st.selectbox("イベント終了時間:", END_OPTIONS, index=len(END_OPTIONS)-1)
        
    # イベント日数
    event_days = st.radio("イベント日数:", ["1日のみ", "2日間"], index=1, horizontal=True)

with col_right:
    st.header("🎓 2. 学年ごとの最大シフト数制限")
    st.caption("💡 名簿内の『最新の入学年度』を自動で1年生、順に2年、3年と判定します。")
    
    g1_limit = st.number_input("1年生の上限（コマ数）:", min_value=0, value=4)
    g2_limit = st.number_input("2年生の上限（コマ数）:", min_value=0, value=6)
    g3_limit = st.number_input("3年生の上限（コマ数）:", min_value=0, value=3)
    limits = [g1_limit, g2_limit, g3_limit]

st.markdown("---")

# 4. 役割・人数・配置制限の設定
st.header("👥 3. 役割・人数・配置制限の設定")
st.caption("必要な役割の名前、人数、そして配置できるメンバーの制限を選んでください。")

# 役割入力を最大8個まで作れるようにループ処理
base_requirements = {}
role_restrictions = {}

# 最初から3行表示し、必要に応じて入力してもらう形にします
for i in range(1, 7):
    c_role, c_num, c_rest = st.columns([3, 2, 3])
    with c_role:
        r_name = st.text_input(f"役割名 {i}:", key=f"r_name_{i}", placeholder="例：入口（空欄でスキップ）")
    with c_num:
        r_num = st.number_input("必要人数:", min_value=0, value=1 if r_name else 0, key=f"r_num_{i}")
    with c_rest:
        r_rest = st.selectbox(
            "配置制限:",
            ["混在可能", "模型班のみ", "展示班のみ", "模型＋展示最高学年"],
            key=f"r_rest_{i}"
        )
    
    if r_name.strip():
        base_requirements[r_name.strip()] = r_num
        role_restrictions[r_name.strip()] = r_rest

st.markdown("---")

# 5. 特殊ルールの設定
st.header("⚡ 4. 特定の時間だけ人数が変わる特殊ルール")
st.caption("特定の時間帯だけ人数を変更したい役割がある場合のみ入力してください。")

special_rules = []
c_sp_role, c_sp_num, c_sp_slots = st.columns([2, 1, 4])
with c_sp_role:
    sp_name = st.text_input("対象の役割名:", placeholder="例：カフート")
with c_sp_num:
    sp_num = st.number_input("その時間の人数:", min_value=0, value=2)
with c_sp_slots:
    # 複数選択可能なボックス
    sp_slots = st.multiselect("対象の時間帯（複数選択可、選ばないと全時間帯）:", ALL_TIME_SLOTS)

if sp_name.strip():
    special_rules.append((sp_name.strip(), sp_num, sp_slots))

st.markdown("---")

# 6. 実行ボタン
if st.button("🚀 シフト表を自動作成してスプレッドシートに書き出す", type="primary", use_container_width=True):
    if not spreadsheet_url:
        st.warning("⚠️ スプレッドシートのURLを入力してください。")
    elif not base_requirements:
        st.warning("⚠️ 役割名を少なくとも1つは入力してください。")
    else:
        with st.spinner("🔮 提出データを解析し、最適な組み合わせを計算しています... ⏳"):
            try:
                # スプレッドシートを開く
                sh = gc.open_by_url(spreadsheet_url)
                
                # 計算ロジックを呼び出し
                success, message = create_shift(
                    sh, gc, spreadsheet_url, start_time, end_time, 
                    event_days, limits, base_requirements, role_restrictions, special_rules
                )
                
                if success:
                    st.success(f"🎉 {message}")
                    st.balloons()
                    st.markdown(f'### 👉 [ここをクリックしてスプレッドシートで確認する]({spreadsheet_url})')
                else:
                    st.error(f"❌ {message}")
                    
            except gspread.exceptions.SpreadsheetNotFound:
                st.error("❌ スプレッドシートが見つかりません。URLが正しいか、または共有設定に『ロボットのアドレス（shift-bot@...）』が追加されているか確認してください。")
            except Exception as e:
                st.error(f"❌ エラーが発生しました: {e}")
