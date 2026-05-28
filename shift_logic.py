import pulp
import pandas as pd
import gspread

# ==========================================
# 時間枠の定義（30分刻み・全13コマ）
# ==========================================
ALL_TIME_SLOTS = [
    "09:00-09:30", "09:30-10:00", "10:00-10:30", "10:30-11:00",
    "11:00-11:30", "11:30-12:00", "12:00-12:30", "12:30-13:00",
    "13:00-13:30", "13:30-14:00", "14:00-14:30", "14:30-15:00",
    "15:00-15:30"
]

def create_shift(sh, gc, start_slot_idx, end_slot_idx, event_days, limits, base_requirements, role_restrictions, special_rules):
    try:
        # 選択された範囲の時間枠を抽出
        active_slots = ALL_TIME_SLOTS[start_slot_idx:end_slot_idx + 1]
        days = ["1日目"] if event_days == "1日のみ" else ["1日目", "2日目"]
        
        # シートの読み込み
        try:
            member_ws = sh.worksheet("名簿")
            survey_ws = sh.worksheet("フォーム回答")
        except:
            return False, "『名簿』または『フォーム回答』シートが見つかりません。シート名を確認してください。"
            
        member_df = pd.DataFrame(member_ws.get_all_records())
        survey_df = pd.DataFrame(survey_ws.get_all_records())
        
        members = member_df["名前"].tolist()
        班データ = dict(zip(member_df["名前"], member_df["班"]))
        学年データ = dict(zip(member_df["名前"], member_df["入学年度"]))
        
        # 学年判定（最新の入学年度＝1年生）
        unique_years = sorted(member_df["入学年度"].unique(), reverse=True)
        year_to_grade = {year: idx+1 for idx, year in enumerate(unique_years)}
        
        grade_limits = {}
        for year, grade in year_to_grade.items():
            if grade == 1: grade_limits[year] = limits[0]
            elif grade == 2: grade_limits[year] = limits[1]
            else: grade_limits[year] = limits[2]

        # 希望シフトのパース
        available = {m: {d: {s: 0 for s in active_slots} for d in days} for m in members}
        for _, row in survey_df.iterrows():
            m_name = row["名前"]
            if m_name not in available:
                continue
            for d in days:
                col_name = f"{d}の希望時間" if event_days == "2日間" else "希望時間"
                if col_name in row and pd.notna(row[col_name]):
                    ans = str(row[col_name])
                    for s in active_slots:
                        if s in ans:
                            available[m_name][d][s] = 1

        # 各コマの必要人数
        requirements = {d: {s: base_requirements.copy() for s in active_slots} for d in days}
        for r_name, sp_num, sp_slots in special_rules:
            for d in days:
                for s in sp_slots:
                    if s in requirements[d] and r_name in requirements[d][s]:
                        requirements[d][s][r_name] = sp_num

        roles = list(base_requirements.keys())
        
        # 最適化モデル作成
        prob = pulp.LpProblem("Shift_Scheduling", pulp.LpMaximize)
        x = pulp.LpVariable.dicts("x", (members, days, active_slots, roles), cat="Binary")
        
        # 目的関数
        prob += pulp.lpSum(x[m][d][s][r] * available[m][d][s] for m in members for d in days for s in active_slots for r in roles)
        
        # 制約ルール
        for d in days:
            for s in active_slots:
                for r in roles:
                    prob += pulp.lpSum(x[m][d][s][r] for m in members) == requirements[d][s][r]
                for m in members:
                    prob += pulp.lpSum(x[m][d][s][r] for r in roles) <= 1
                    for r in roles:
                        prob += x[m][d][s][r] <= available[m][d][s]

        for m in members:
            m_year = 学年データ.get(m)
            if m_year in grade_limits:
                prob += pulp.lpSum(x[m][d][s][r] for d in days for s in active_slots for r in roles) <= grade_limits[m_year]

        for m in members:
            m_ban = 班データ.get(m, "")
            m_year = 学年データ.get(m)
            m_grade = year_to_grade.get(m_year, 3)
            for d in days:
                for s in active_slots:
                    for r in roles:
                        rest = role_restrictions.get(r, "混在可能")
                        if rest == "模型班のみ" and m_ban != "模型":
                            prob += x[m][d][s][r] == 0
                        elif rest == "展示班のみ" and m_ban != "展示":
                            prob += x[m][d][s][r] == 0
                        elif rest == "模型＋展示最高学年" and m_grade == 1:
                            prob += x[m][d][s][r] == 0

        status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
        if pulp.LpStatus[status] != "Optimal":
            return False, "条件に合うシフトの組み合わせが見つかりませんでした。役割の人数を減らすか、学年の上限コマ数を増やしてみてください。"

        # スプレッドシートへ書き出し
        try:
            out_ws = sh.worksheet("作成されたシフト")
            out_ws.clear()
        except:
            out_ws = sh.add_worksheet(title="作成されたシフト", rows="100", cols="20")

        headers = ["日程", "時間帯"] + roles
        output_rows = [headers]
        for d in days:
            for s in active_slots:
                row_data = [d, s]
                for r in roles:
                    assigned = [m for m in members if x[m][d][s][r].varValue and x[m][d][s][r].varValue > 0.9]
                    row_data.append(", ".join(assigned) if assigned else "（空き）")
                output_rows.append(row_data)
                
        out_ws.update("A1", output_rows)
        return True, "シフトが正常に作成され、スプレッドシートに書き込まれました！"
        
    except Exception as e:
        return False, f"計算中にエラーが発生しました: {str(e)}"
