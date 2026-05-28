import pulp
import pandas as pd
import gspread
import re

# ==========================================
# app.py から呼び出される選択肢の定義
# ==========================================
START_OPTIONS = [
    "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", 
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00"
]

END_OPTIONS = [
    "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", 
    "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30"
]

ALL_TIME_SLOTS = [
    "09:00-09:30", "09:30-10:00", "10:00-10:30", "10:30-11:00",
    "11:00-11:30", "11:30-12:00", "12:00-12:30", "12:30-13:00",
    "13:00-13:30", "13:30-14:00", "14:00-14:30", "14:30-15:00",
    "15:00-15:30"
]

def create_shift(sh, gc, spreadsheet_url, start_time, end_time, event_days, limits, base_requirements, role_restrictions, special_rules):
    try:
        # 1. 時間枠のフィルタリング
        s_idx = START_OPTIONS.index(start_time)
        e_idx = END_OPTIONS.index(end_time)
        if s_idx > e_idx:
            return False, "開始時間は終了時間より前に設定してください。"
            
        active_slots = ALL_TIME_SLOTS[s_idx:e_idx+1]
        days = ["1日目"] if event_days == "1日のみ" else ["1日目", "2日目"]
        
        # 2. スプレッドシートからのデータ読み込み
        try:
            member_ws = sh.worksheet("名簿")
            survey_ws = sh.worksheet("フォーム回答")
        except:
            return False, "『名簿』または『フォーム回答』シートが見つかりません。"
            
        member_df = pd.DataFrame(member_ws.get_all_records())
        survey_df = pd.DataFrame(survey_ws.get_all_records())
        
        # 3. メンバー情報の整理
        members = member_df["名前"].tolist()
        班データ = dict(zip(member_df["名前"], member_df["班"]))
        学年データ = dict(zip(member_df["名前"], member_df["入学年度"]))
        
        # 最新の入学年度を1年生とする判定
        unique_years = sorted(member_df["入学年度"].unique(), reverse=True)
        year_to_grade = {year: idx+1 for idx, year in enumerate(unique_years)}
        
        # 学年ごとの上限辞書作成
        grade_limits = {}
        for year, grade in year_to_grade.items():
            if grade == 1: grade_limits[year] = limits[0]
            elif grade == 2: grade_limits[year] = limits[1]
            else: grade_limits[year] = limits[2]

        # 4. 希望シフト（回答）のパース
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

        # 5. 各コマの必要人数の組み立て
        requirements = {d: {s: base_requirements.copy() for s in active_slots} for d in days}
        
        # 特殊ルールの適用
        for r_name, sp_num, sp_slots in special_rules:
            target_slots = sp_slots if sp_slots else active_slots
            for d in days:
                for s in target_slots:
                    if s in requirements[d] and r_name in requirements[d][s]:
                        requirements[d][s][r_name] = sp_num

        roles = list(base_requirements.keys())
        if not roles:
            return False, "有効な役割が設定されていません。"

        # 6. 数理最適化モデルの構築
        prob = pulp.LpProblem("Shift_Scheduling", pulp.LpMaximize)
        
        # 変数定義: x[m, d, s, r] = 1 (メンバーmがd日目の枠sで役割rに入る)
        x = pulp.LpVariable.dicts("x", (members, days, active_slots, roles), cat="Binary")
        
        # 目的関数: 入れる枠を最大化（希望に沿う）
        prob += pulp.lpSum(x[m][d][s][r] * available[m][d][s] for m in members for d in days for s in active_slots for r in roles)
        
        # 制約ルール設定
        for d in days:
            for s in active_slots:
                # 制約①：各コマ、各役割の必要人数を満たす
                for r in roles:
                    prob += pulp.lpSum(x[m][d][s][r] for m in members) == requirements[d][s][r]
                
                # 制約②：一人のメンバーは同じ時間に1つの役割しかできない
                for m in members:
                    prob += pulp.lpSum(x[m][d][s][r] for r in roles) <= 1
                    # 希望していない時間には入れない
                    for r in roles:
                        prob += x[m][d][s][r] <= available[m][d][s]

        # 制約③：学年ごとの合計コマ数制限
        for m in members:
            m_year = 学年データ.get(m)
            if m_year in grade_limits:
                prob += pulp.lpSum(x[m][d][s][r] for d in days for s in active_slots for r in roles) <= grade_limits[m_year]

        # 制約④：配置制限（班制限など）
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
                        elif rest == "模型＋展示最高学年":
                            # 最高学年（1 = 最も数値が新しい = 1年生、ではない方、つまり2,3年生など）
                            if m_grade == 1: 
                                prob += x[m][d][s][r] == 0

        # 7. 計算実行
        status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
        
        if pulp.LpStatus[status] != "Optimal":
            return False, "❌ 条件が厳しすぎるか、人数が不足しているためシフトを割り当てられませんでした。条件（人数や上限）を緩めてみてください。"

        # 8. 結果の整形とスプレッドシートへの書き出し
        try:
            out_ws = sh.worksheet("作成されたシフト")
            out_ws.clear()
        except:
            out_ws = sh.add_worksheet(title="作成されたシフト", rows="100", cols="20")

        # ヘッダー作成
        headers = ["日程", "時間帯"] + roles
        output_rows = [headers]
        
        for d in days:
            for s in active_slots:
                row_data = [d, s]
                for r in roles:
                    assigned_members = [m for m in members if x[m][d][s][r].varValue and x[m][d][s][r].varValue > 0.9]
                    row_data.append(", ".join(assigned_members) if assigned_members else "（空き）")
                output_rows.append(row_data)
                
        out_ws.update("A1", output_rows)
        return True, "シフトの作成とスプレッドシートへの書き出しが正常に完了しました！"
        
    except Exception as e:
        return False, f"システムエラーが発生しました: {str(e)}"
