import streamlit as st
import gspread
from shift_logic import create_shift, ALL_TIME_SLOTS

st.set_page_config(page_title="シフト表自動作成システム", layout="wide")

# Googleの合鍵（Secrets）チェック
try:
    credentials = dict(st.secrets["gcp_service_account"])
    gc = gspread.service_account_from_dict(credentials)
except Exception as e:
    st.error(f"🔒 Googleの合鍵（Secrets）が正しく設定されていないか、形式が違います。詳細: {e}")
    st.stop()

st.title("📅 シフト表自動作成システム")
st.markdown("---")

col_left, col_right = st.columns(2)

with col_left:
    st.header("⚙️ 1. 基本条件設定")
    spreadsheet_url = st.text_input(
        "スプレッドシートのURLを貼り付けてください：",
        placeholder="https://docs.google.com/spreadsheets/d/..."
    )
    
    # 時間を「コマ（スロット）」ベースで選ぶようにして、YY:YYの表示ズレを完璧に防止
    st.markdown("**イベント時間帯（開始コマ〜終了コマ）を選んでください**")
    c1, c2 = st.columns(2)
    with c1:
        start_slot = st.selectbox("開始時間（ここから）:", ALL_TIME_SLOTS, index=0)
    with c2:
        end_slot = st.selectbox("終了時間（ここまで含む）:", ALL_TIME_SLOTS, index=len(ALL_TIME_SLOTS)-1)
        
    start_idx = ALL_TIME_SLOTS.index(start_slot)
    end_idx = ALL_TIME_SLOTS.index(end_slot)
    
    # 選択された実際の時間帯を綺麗に画面に表示する機能
    display_start = start_slot.split("-")[0]
    display_end = end_slot.split("-")[1]
    st.info(f"⏰ 選択中の時間帯: **{display_start} 〜 {display_end}** (合計 {end_idx - start_idx + 1} コマ)")
    
    event_days = st.radio("イベント日数:", ["1日のみ", "2日間"], index=0, horizontal=True)

with col_right:
    st.header("🎓 2. 学年ごとの最大シフト数制限")
    g1_limit = st.number_input("1年生の上限（コマ数）:", min_value=0, value=4)
    g2_limit = st.number_input("2年生の上限（コマ数）:", min_value=0, value=6)
    g3_limit = st.number_input("3年生の上限（コマ数）:", min_value=0, value=3)
    limits = [g1_limit, g2_limit, g3_limit]

st.markdown("---")

# 3. 役割・人数・配置制限の設定
st.header("👥 3. 役割・人数・配置制限の設定")
base_requirements = {}
role_restrictions = {}

# 通常シフトの設定枠
for i in range(1, 7):
    c_role, c_num, c_rest = st.columns([3, 2, 3])
    with c_role:
        r_name = st.text_input(f"役割名 {i}:", key=f"r_name_{i}", placeholder="例：入口（空欄でスキップ）")
    with c_num:
        r_num = st.number_input("必要人数:", min_value=0, value=0, key=f"r_num_{i}")
    with c_rest:
        r_rest = st.selectbox("配置制限:", ["混在可能", "模型班のみ", "展示班のみ", "模型＋展示最高学年"], key=f"r_rest_{i}")
    
    if r_name.strip():
        base_requirements[r_name.strip()] = r_num
        role_restrictions[r_name.strip()] = r_rest

# ★【新機能】通常シフトの設定数を計算して表示
total_normal_slots = sum(base_requirements.values()) * (end_idx - start_idx + 1) * (1 if event_days == "1日のみ" else 2)
st.metric(label="📊 通常シフトの総必要スロット数（全時間帯の合計必要人数）", value=f"{total_normal_slots} コマ分")

st.markdown("---")

# 4. 特殊ルールの設定
st.header("⚡ 4. 特定の時間だけ人数が変わる特殊ルール")
special_rules = []

c_sp_role, c_sp_num, c_sp_slots = st.columns([2, 1, 4])
with c_sp_role:
    sp_name = st.text_input("対象の役割名:", placeholder="例：宣伝")
with c_sp_num:
    sp_num = st.number_input("その時間の人数:", min_value=0, value=0)
with c_sp_slots:
    # 選択可能な選択肢を、上で選んだイベント時間内に絞り込む
    current_active_slots = ALL_TIME_SLOTS[start_idx:end_idx + 1]
    sp_slots = st.multiselect("対象の時間帯（複数選択）:", current_active_slots)

# ★【新機能】特殊シフトの設定数を計算して表示
total_special_slots = 0
if sp_name.strip() and sp_slots:
    special_rules.append((sp_name.strip(), sp_num, sp_slots))
    # 本来の人数からどれだけ増減したかをカウント
    normal_num = base_requirements.get(sp_name.strip(), 0)
    diff = sp_num - normal_num
    total_special_slots = diff * len(sp_slots) * (1 if event_days == "1日のみ" else 2)

st.metric(label="⚡ 特殊ルールによる人数の増減分", value=f"{'+' if total_special_slots >= 0 else ''}{total_special_slots} コマ分")

st.markdown("---")

if st.button("🚀 シフト表を自動作成してスプレッドシートに書き出す", type="primary", use_container_width=True):
    if start_idx > end_idx:
        st.error("❌ 開始時間は終了時間より前のものを選択してください。")
    elif not spreadsheet_url:
        st.warning("⚠️ スプレッドシートのURLを入力してください。")
    elif not base_requirements:
        st.warning("⚠️ 役割名を少なくとも1つは入力してください。")
    else:
        with st.spinner("🔮 最適なシフトを計算しています..."):
            try:
                sh = gc.open_by_url(spreadsheet_url)
                success, message = create_shift(
                    sh, gc, start_idx, end_idx, event_days, limits, 
                    base_requirements, role_restrictions, special_rules
                )
                if success:
                    st.success(f"🎉 {message}")
                    st.balloons()
                else:
                    st.error(f"❌ {message}")
            except Exception as e:
                st.error(f"❌ エラーが発生しました: {e}")
