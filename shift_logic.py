import re
import pandas as pd
import pulp
import gspread

# 30分刻みのコマ名と、時間の対応マッピング
TIME_MAP = [
    {"slot": "9:00〜9:30",   "start": "9:00",  "end": "9:30"},
    {"slot": "9:30〜10:00",  "start": "9:30",  "end": "10:00"},
    {"slot": "10:00〜10:30", "start": "10:00", "end": "10:30"},
    {"slot": "10:30〜11:00", "start": "10:30", "end": "11:00"},
    {"slot": "11:00〜11:30", "start": "11:00", "end": "11:30"},
    {"slot": "11:30〜12:00", "start": "11:30", "end": "12:00"},
    {"slot": "12:00〜12:30", "start": "12:00", "end": "12:30"},
    {"slot": "12:30〜13:00", "start": "12:30", "end": "13:00"},
    {"slot": "13:00〜13:30", "start": "13:00", "end": "13:30"},
    {"slot": "13:30〜14:00", "start": "13:30", "end": "14:00"},
    {"slot": "14:00〜14:30", "start": "14:00", "end": "14:30"},
    {"slot": "14:30〜15:00", "start": "14:30", "end": "15:00"},
    {"slot": "15:00〜15:30", "start": "15:00", "end": "15:30"},
    {"slot": "15:30〜16:00", "start": "15:30", "end": "16:00"}
]

ALL_TIME_SLOTS = [m["slot"] for m in TIME_MAP]

def extract_8digit(email):
    if pd.isna(email):
        return ""
    match = re.search(r'\d{8}', str(email))
    return match.group(0) if match else ""

def extract_year(email):
    if pd.isna(email):
        return None
    match = re.search(r'\d{4}', str(email))
    return int(match.group()) if match else None

# Streamlit側から呼び出すメイン関数
def create_shift(sh, gc, url, start_slot, end_slot, event_days, limits, base_requirements, role_restrictions, special_rules):
    # limits = [1年上限, 2年上限, 3年上限]
    
    # 1. 時間枠の決定
    try:
        idx_start = next(i for i, m in enumerate(TIME_MAP) if m["start"] == start_slot)
        idx_end = next(i for i, m in enumerate(TIME_MAP) if m["end"] == end_slot)
    except:
        return False, "時間の範囲指定が不正です。"
        
    if idx_start > idx_end:
        return False, "開始時間が終了時間より後になっています。"
        
    target_slots = ALL_TIME_SLOTS[idx_start:idx_end + 1]
    roles = list(base_requirements.keys())

    # 2. 名簿データの取得
    try:
        try:
            meibo_sheet = sh.worksheet("学年名簿")
            meibo_emails = meibo_sheet.col_values(1)[1:] 
            meibo_numbers = [extract_8digit(e) for e in meibo_emails if extract_8digit(e)]
        except gspread.exceptions.WorksheetNotFound:
            meibo_numbers = []

        worksheet = sh.get_worksheet(0)
        df_res = pd.DataFrame(worksheet.get_all_records())
    except Exception as e:
        return False, f"スプレッドシートの読み込みに失敗しました: {e}"

    if "参加の可否" in df_res.columns:
        df_res = df_res[df_res["参加の可否"] == "はい"].copy()
    else:
        return False, "シートに『参加の可否』列が見つかりません。"

    df_res['入学年度'] = df_res['メールアドレス'].apply(extract_year) if "メールアドレス" in df_res.columns else None

    if meibo_numbers and "メールアドレス" in df_res.columns:
        def sort_by_meibo_index(row_data):
            email_num = extract_8digit(row_data["メールアドレス"])
            return meibo_numbers.index(email_num) if email_num in meibo_numbers else 9999
        df_res["_sort_key"] = df_res.apply(sort_by_meibo_index, axis=1)
        df_res = df_res.sort_values("_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)

    valid_years = sorted([int(y) for y in df_res['入学年度'].dropna().unique()], reverse=True)

    def assign_relative_grade(year):
        if pd.isna(year) or year not in valid_years:
            return 3
        rank = valid_years.index(year) + 1
        return 3 if rank > 3 else rank

    df_res['学年'] = df_res['入学年度'].apply(assign_relative_grade)

    exhibition_df = df_res[df_res["所属班"] == "展示"] if "所属班" in df_res.columns else pd.DataFrame()
    highest_grade_year_exhibit = exhibition_df['入学年度'].min() if not exhibition_df.empty else None

    member_info = {}
    for _, row in df_res.iterrows():
        name = row["名前"]
        group = row["所属班"] if "所属班" in df_res.columns else "不明"
        grade = row["学年"]
        year = row["入学年度"]
        is_highest_exhibit = (group == "展示" and year == highest_grade_year_exhibit and highest_grade_year_exhibit is not None)
        
        member_info[name] = {
            "学年": grade,
            "所属班": group,
            "模型班のみ": 1 if group == "模型" else 0,
            "展示班のみ": 1 if group == "展示" else 0,
            "模型＋展示最高学年": 1 if (group == "模型" or is_highest_exhibit) else 0,
            "混在可能": 1
        }

    time_cols = [c for c in df_res.columns if "参加可能時間" in c]
    if event_days == '1日のみ':
        col_1st = [c for c in time_cols if "一日目" in c]
        target_col = col_1st[0] if col_1st else (time_cols[0] if time_cols else None)
        mapping_days = {target_col: "一日目"} if target_col else {}
        days = ["一日目"] if target_col else []
    else:
        mapping_days = {}
        days = []
        for c in time_cols:
            if "一日目" in c:
                mapping_days[c] = "一日目"
                if "一日目" not in days: days.append("一日目")
            elif "二日目" in c:
                mapping_days[c] = "二日目"
                if "二日目" not in days: days.append("二日目")
                
    if not days:
        return False, "シート内に『参加可能時間』に関する列が見つかりません。"

    members = df_res["名前"].tolist()

    # 必要人数の初期化
    required_staff = {}
    for d in days:
        for t in target_slots:
            for r in roles:
                required_staff[(d, t, r)] = base_requirements[r]

    # 特殊ルールの適用
    for r_sp_name, count_val, selected_slots in special_rules:
        if not r_sp_name or r_sp_name not in roles:
            continue
        slots_to_apply = selected_slots if selected_slots else target_slots.copy()
        for d in days:
            for t in slots_to_apply:
                if t in target_slots:
                    required_staff[(d, t, r_sp_name)] = count_val

    # 参加可能マッピング
    avail = {}
    for _, row in df_res.iterrows():
        m = row["名前"]
        for orig_col, d in mapping_days.items():
            raw_time = row[orig_col]
            allowed = [t.strip() for t in str(raw_time).split(",")] if pd.notna(raw_time) else []
            for t in target_slots:
                avail[(m, d, t)] = 1 if t in allowed else 0

    # 3. 最適化計算
    prob = pulp.LpProblem("Shift_Scheduling", pulp.LpMinimize)
    x = pulp.LpVariable.dicts("x", ((m, d, t, r) for m in members for d in days for t in target_slots for r in roles), cat='Binary')
    max_work = pulp.LpVariable("max_work", lowBound=0, cat='Integer')
    prob += max_work

    for d in days:
        for t in target_slots:
            for r in roles:
                prob += pulp.lpSum(x[m, d, t, r] for m in members) == required_staff[(d, t, r)]

    for m in members:
        for d in days:
            for t in target_slots:
                prob += pulp.lpSum(x[m, d, t, r] for r in roles) <= 1
                for r in roles:
                    prob += x[m, d, t, r] <= avail[(m, d, t)]
        
    for r in roles:
        restriction_type = role_restrictions[r]
        if restriction_type != "混在可能":
            for m in members:
                if member_info[m][restriction_type] == 0:
                    for d in days:
                        for t in target_slots:
                            prob += x[m, d, t, r] == 0
                            
    for m in members:
        m_grade = member_info[m]["学年"]
        total_slots_for_member = pulp.lpSum(x[m, d, t, r] for d in days for t in target_slots for r in roles)
        if m_grade == 1:
            prob += total_slots_for_member <= limits[0]
        elif m_grade == 2:
            prob += total_slots_for_member <= limits[1]
        elif m_grade == 3:
            prob += total_slots_for_member <= limits[2]

    for m in members:
        prob += pulp.lpSum(x[m, d, t, r] for d in days for t in target_slots for r in roles) <= max_work

    status = prob.solve()

    if pulp.LpStatus[status] == "Optimal":
        seen_names = set()
        unique_staff_names = [m for m in members if not (m in seen_names or seen_names.add(m))]

        # スプレッドシートへの書き出し
        for d in days:
            rows = []
            for r in roles:
                max_staff = max(required_staff[(d, t, r)] for t in target_slots)
                if max_staff == 0: continue
                for i in range(max_staff):
                    row_data = {"役割": r if i == 0 else ""}
                    for t in target_slots:
                        assigned = [m for m in members if x[m, d, t, r].varValue == 1]
                        row_data[t] = assigned[i] if i < len(assigned) else ""
                    rows.append(row_data)
            
            final_df = pd.DataFrame(rows)
            sheet_name = f"{d}_自動生成シフト"
            try:
                ws_output = sh.worksheet(sheet_name)
                sh.del_worksheet(ws_output)
            except gspread.exceptions.WorksheetNotFound:
                pass
            
            ws_output = sh.add_worksheet(title=sheet_name, rows="100", cols="20")
            header = ["役割"] + target_slots
            values = [header] + final_df.values.tolist()
            ws_output.update('A1', values)
            
            # プルダウンの設置 (※API制限エラー回避のため簡易化)
            try:
                end_row = len(values)  
                dropdown_rows = [end_row + 3, end_row + 5, end_row + 7]
                column_letter = "D"
                for idx, r_num in enumerate(dropdown_rows):
                    target_cell_a1 = f"{column_letter}{r_num}"
                    validation_rule = {
                        "validateInput": True,
                        "strict": True,
                        "showCustomUi": True,
                        "formula1": f'="{",".join(unique_staff_names[:30])}"' # 念のため上限絞り
                    }
                    ws_output.update_cell_selector_validation(target_cell_a1, validation_rule)
                    ws_output.update_cell(f"C{r_num}", f"確認対象 {idx + 1}:")
            except:
                pass # プルダウン設置エラーは全体の処理を止めないようにスルー
                
        return True, "最適シフトの計算とスプレッドシートへの書き出しが成功しました！"
    else:
        return False, "設定された条件を満たす組み合わせが存在しませんでした。上限コマ数を増やすか、役割の人数を減らしてください。"
