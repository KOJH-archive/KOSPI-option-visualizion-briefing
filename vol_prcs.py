import glob
import os
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime

# ==========================================
# [설정] 폴더 구조 및 상품 분류 체계 정의
# ==========================================
src_daily_dir = "./daily"       # 당일 추가하는 데이터 위치
dest_raw_dir = "./vol_raw"      # 일별 데이터 기록 파일 누적 위치
picture_base_dir = "./picture"  # 가공된 데이터 그래프 파일 저장소 위치

# 파일명 접두사 체계 매핑 (접두사: 마스터 상품명)
product_mapping = {
    "200": "200",
    "w": "week",
    "w2": "week2",
    "m": "mini",
    "skh": "SK하이닉스",
    "sec": "삼성전자"
}

investors = ["기관", "개인", "외인"]
data_types = ["거래량", "거래대금"]

# 시각화 저장용 날짜별 하위 디렉토리 생성
today_str = datetime.today().strftime("%Y%m%d")
target_save_dir = os.path.join(picture_base_dir, today_str)

# 필요한 폴더들이 없는 경우 자동 생성
for folder in [src_daily_dir, dest_raw_dir, target_save_dir]:
    if not os.path.exists(folder):
        os.makedirs(folder)
        print(f"▶ 폴더 생성 완료: {folder}")

# ==========================================
# STEP 1. 일별 분할 로우 데이터 파일(c/p) 탐색 및 병합 누적
# ==========================================
call_files = glob.glob(os.path.join(src_daily_dir, "*c_*.csv"))

if not call_files:
    print(f"[{src_daily_dir}] 폴더 내에 당일 처리할 콜 원본 파일(*c_YYYYMMDD.csv)이 없습니다.")
    print("기존에 파일들로만 시각화(STEP 2) 단계 진입을 시도합니다.")
    jobs = []
else:
    jobs = []
    for file_path in call_files:
        filename = os.path.basename(file_path)
        try:
            prefix_part, rest = filename.split("c_")
            date_part = rest.split(".")[0]
            if prefix_part in product_mapping:
                jobs.append((prefix_part, date_part))
        except Exception:
            continue

if jobs:
    print(f"\n▶ 총 {len(jobs)}개의 데이터 삽입 및 가공을 시작합니다.")

for prefix, date_str in jobs:
    prod_name = product_mapping[prefix]
    formatted_date = f"{date_str[4:6]}월 {date_str[6:8]}일"
    
    call_file_path = os.path.join(src_daily_dir, f"{prefix}c_{date_str}.csv")
    put_file_path = os.path.join(src_daily_dir, f"{prefix}p_{date_str}.csv")
    
    if not os.path.exists(put_file_path):
        print(f"  ⚠ 풋 파일 누락 스킵: {prefix}p_{date_str}.csv 가 없습니다.")
        continue
        
    def load_raw_csv(path):
        for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr"]:
            try:
                df = pd.read_csv(path, encoding=enc, index_col=0)
                df.index = df.index.astype(str).str.strip()
                return df
            except Exception:
                continue
        return None

    call_raw = load_raw_csv(call_file_path)
    put_raw = load_raw_csv(put_file_path)
    
    if call_raw is None or put_raw is None:
        print(f"  ❌ 파일 로드 실패: {formatted_date} 데이터를 유효하게 해석하지 못했습니다.")
        continue

    def process_investor_df(df):
        df = df.rename(index={"외국인": "외인"})
        for col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors='coerce').fillna(0)
            
        summary_rows = {}
        inst_sum = df.loc["기관합계"] if "기관합계" in df.index else pd.Series(0, index=df.columns)
        etc_corp = df.loc["기타법인"] if "기타법인" in df.index else pd.Series(0, index=df.columns)
        summary_rows["기관"] = inst_sum + etc_corp
        
        summary_rows["개인"] = df.loc["개인"] if "개인" in df.index else pd.Series(0, index=df.columns)
        summary_rows["외인"] = df.loc["외인"] if "외인" in df.index else pd.Series(0, index=df.columns)
        
        return pd.DataFrame(summary_rows).T

    call_df = process_investor_df(call_raw)
    put_df = process_investor_df(put_raw)

    for d_type in data_types:
        target_csv_name = f"{prod_name}_{d_type}.csv"
        target_csv_path = os.path.join(dest_raw_dir, target_csv_name)
        
        if not os.path.exists(target_csv_path):
            header_line1 = ",기관,,개인,,외인,,기관,,개인,,외인,\n"
            header_line2 = ",콜_매도,콜_매수,콜_매도,콜_매수,콜_매도,콜_매수,풋_매도,풋_매수,풋_매도,풋_매수,풋_매도,풋_매수\n"
            with open(target_csv_path, "w", encoding="utf-8-sig") as f:
                f.write(header_line1)
                f.write(header_line2)
                
        existing_df = None
        for encoding_type in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
            try:
                existing_df = pd.read_csv(target_csv_path, encoding=encoding_type, header=None)
                break
            except Exception:
                continue

        if existing_df is None:
            print(f"  ❌ {target_csv_path} 파일을 읽어오는데 실패했습니다.")
            continue
        
        if existing_df.shape[0] > 2:
            existing_df = existing_df[existing_df[0].str.strip() != formatted_date]
            
        new_row = [formatted_date] + [0] * 12
        
        idx_map = {
            "기관": {"col": (1, 2), "put": (7, 8)},
            "개인": {"col": (3, 4), "put": (9, 10)},
            "외인": {"col": (5, 6), "put": (11, 12)}
        }
        
        col_sell = f"{d_type}_매도"
        col_buy = f"{d_type}_매수"
        
        for inv in investors:
            if inv in call_df.index:
                s_idx, b_idx = idx_map[inv]["col"]
                new_row[s_idx] = int(call_df.loc[inv, col_sell])
                new_row[b_idx] = int(call_df.loc[inv, col_buy])
                
            if inv in put_df.index:
                s_idx, b_idx = idx_map[inv]["put"]
                new_row[s_idx] = int(put_df.loc[inv, col_sell])
                new_row[b_idx] = int(put_df.loc[inv, col_buy])

        headers = existing_df.iloc[:2]
        data_body = existing_df.iloc[2:]
        
        new_row_df = pd.DataFrame([new_row])
        updated_data_body = pd.concat([new_row_df, data_body], ignore_index=True)
        updated_data_body.dropna(subset=[0], inplace=True)
        updated_data_body = updated_data_body[updated_data_body[0].astype(str).str.strip() != "nan"]
        
        final_df = pd.concat([headers, updated_data_body], ignore_index=True)
        final_df.to_csv(target_csv_path, index=False, header=False, encoding="utf-8-sig")
        print(f"  ✔ [업데이트] {target_csv_path} -> {formatted_date} 삽입 성공")


# ==========================================
# STEP 2. 스타일 초기화 및 4단 상단 가로형 범례 시각화
# ==========================================
print("\n▶ STEP 2: 시각화를 시작합니다.")

import koreanize_matplotlib
plt.style.use("dark_background")
plt.rcParams["axes.unicode_minus"] = False
plt.style.use("ggplot")

visualization_targets = glob.glob(os.path.join(dest_raw_dir, "*.csv"))

for file_path in visualization_targets:
    file_name = os.path.splitext(os.path.basename(file_path))[0]
    
    if "master" in file_name or file_name.count('_') != 1:
        continue
        
    df_chart = None
    for encoding_type in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
        try:
            df_chart = pd.read_csv(file_path, encoding=encoding_type, header=None)
            break
        except Exception:
            continue

    if df_chart is None or df_chart.shape[0] < 3:
        print(f"  ❌ 파일 파싱 불가 혹은 데이터 부족 스킵 ({file_name})")
        continue

    try:
        latest_row = df_chart.iloc[2]
        latest_date_label = str(latest_row.iloc[0]).strip()
        
        def parse_val(v):
            val = pd.to_numeric(str(v).strip(), errors='coerce')
            return 0 if pd.isna(val) else val

        call_data = pd.DataFrame({
            "매도": [parse_val(latest_row.iloc[1]), parse_val(latest_row.iloc[3]), parse_val(latest_row.iloc[5])],
            "매수": [parse_val(latest_row.iloc[2]), parse_val(latest_row.iloc[4]), parse_val(latest_row.iloc[6])]
        }, index=["기관", "개인", "외인"])

        put_data = pd.DataFrame({
            "매도": [parse_val(latest_row.iloc[7]), parse_val(latest_row.iloc[9]), parse_val(latest_row.iloc[11])],
            "매수": [parse_val(latest_row.iloc[8]), parse_val(latest_row.iloc[10]), parse_val(latest_row.iloc[12])]
        }, index=["기관", "개인", "외인"])

        history_body = df_chart.iloc[2:].copy()
        for col_idx in range(1, 13):
            history_body[col_idx] = pd.to_numeric(history_body[col_idx], errors='coerce').fillna(0)
            
        recent_5 = history_body.head(5).iloc[::-1]
        dates_5 = recent_5[0].astype(str).str.strip().tolist()

        c_net_inst = (recent_5[2] - recent_5[1]).tolist()
        c_net_ind = (recent_5[4] - recent_5[3]).tolist()
        c_net_frg = (recent_5[6] - recent_5[5]).tolist()

        p_net_inst = (recent_5[8] - recent_5[7]).tolist()
        p_net_ind = (recent_5[10] - recent_5[9]).tolist()
        p_net_frg = (recent_5[12] - recent_5[11]).tolist()

    except Exception as e:
        print(f"  ❌ 데이터 구조 분석 및 순매수 연산 오류 ({file_name}): {e}")
        continue

    # 전체 컴포넌트 4단 구성 (정방형 배치를 위해 11x18인치 스케일 유지)
    fig, (ax_call, ax_put, ax_c_trend, ax_p_trend) = plt.subplots(4, 1, figsize=(14, 20))
    fig.patch.set_facecolor("#111116")
    
    title_suffix = "거래량" if "거래량" in file_name else "거래대금"
    fig.suptitle(f"{file_name} 투자자별 거래실적 ({latest_date_label} 기준)", 
                 fontsize=26, fontweight="bold", y=0.98, color="#ffffff", linespacing=1.4)

    bar_colors = ["#008b94", "#e84118"]
    
    # ----------------------------------------------------
    # 1. 첫 번째 차트: 당일 콜 옵션 포지션 (상단 가로형 범례)
    # ----------------------------------------------------
    ax_call.set_facecolor("#1a1a24")
    call_data.plot(kind="bar", ax=ax_call, color=bar_colors, edgecolor="none", alpha=0.75, rot=0, width=0.3)
    ax_call.set_title(f"■ 당일 콜(CALL) 옵션 {title_suffix} 포지션", 
    fontsize=16, fontweight="bold", pad=14, color="#ffffff", loc="left")
    ax_call.tick_params(axis='x', colors="#ffffff", labelsize=15)
    ax_call.tick_params(axis='y', colors="#adb5bd", labelsize=10)

    
    # loc='upper center', ncol=2 설정을 통해 내부 상단에 가로로 나열
    ax_call.legend(["매도 (Sell)", "매수 (Buy)"], loc="upper center", ncol=2, 
    frameon=True, facecolor="#1a1a24", edgecolor="none", fontsize=14)
    ax_call.grid(True, axis="y", color="#2d2d3a", linestyle="-", linewidth=0.5)
    ax_call.grid(False, axis="x")
    for spine in ax_call.spines.values():
        spine.set_visible(False)

    max_c = call_data.max().max()
    ax_call.set_ylim(0, max_c * 1.25 if max_c > 0 else 1) # 상단 범례 여백 공간 확대
    for p in ax_call.patches:
        h = p.get_height()
        if h > 0:
            ax_call.text(p.get_x() + p.get_width() / 2., h + (max_c * 0.02), f"{h:,.0f}", 
                         ha="center", va="bottom", fontsize=14, color="#ffffff", fontweight="bold")

    # ----------------------------------------------------
    # 2. 두 번째 차트: 당일 풋 옵션 포지션 (상단 가로형 범례)
    # ----------------------------------------------------
    ax_put.set_facecolor("#1a1a24")
    put_data.plot(kind="bar", ax=ax_put, color=bar_colors, edgecolor="none", alpha=0.75, rot=0, width=0.3)
    ax_put.set_title(f"■ 당일 풋(PUT) 옵션 {title_suffix} 포지션", 
    fontsize=16, fontweight="bold", pad=14, color="#ffffff", loc="left")
    ax_put.tick_params(axis='x', colors="#ffffff", labelsize=15)
    ax_put.tick_params(axis='y', colors="#adb5bd", labelsize=10)

    # 동일하게 내부 상단 중앙 가로 정렬
    ax_put.legend(["매도 (Sell)", "매수 (Buy)"], loc="upper center", ncol=2, 
    frameon=True, facecolor="#1a1a24", edgecolor="none", fontsize=14)
    ax_put.grid(True, axis="y", color="#2d2d3a", linestyle="-", linewidth=0.5)
    ax_put.grid(False, axis="x")
    for spine in ax_put.spines.values():
        spine.set_visible(False)

    max_p = put_data.max().max()
    ax_put.set_ylim(0, max_p * 1.25 if max_p > 0 else 1) # 상단 범례 여백 공간 확대
    for p in ax_put.patches:
        h = p.get_height()
        if h > 0:
            ax_put.text(p.get_x() + p.get_width() / 2., h + (max_p * 0.02), f"{h:,.0f}", 
                         ha="center", va="bottom", fontsize=14, color="#ffffff", fontweight="bold")

    # 주체별 고유 컬러 정의
    color_inst = "#ff9f43"   # 기관: 오렌지
    color_ind = "#1dd1a1"    # 개인: 민트그린
    color_frg = "#9c88ff"    # 외인: 소프트퍼플

    # ----------------------------------------------------
    # 3. 세 번째 차트: 5거래일 콜(CALL) 순매수 추이 (상단 내부 가로형 범례)
    # ----------------------------------------------------
    ax_c_trend.set_facecolor("#1a1a24")
    ax_c_trend.plot(dates_5, c_net_inst, color=color_inst, linestyle="-", marker="o", linewidth=1.2, label="기관")
    ax_c_trend.plot(dates_5, c_net_ind, color=color_ind, linestyle="-", marker="o", linewidth=1.2, label="개인")
    ax_c_trend.plot(dates_5, c_net_frg, color=color_frg, linestyle="-", marker="o", linewidth=1.2, label="외인")
    ax_c_trend.axhline(0, color="#57606f", linestyle="-", linewidth=1.2, alpha=0.8)
    
    ax_c_trend.set_title(f"■ 최근 5거래일 콜(CALL) 옵션 주체별 순거래 추이", 
    fontsize=16, fontweight="bold", pad=12, color="#ffffff", loc="left")
    ax_c_trend.tick_params(axis='x', colors="#dee2e6", labelsize=14)
    ax_c_trend.tick_params(axis='y', colors="#adb5bd", labelsize=10)

    # 상단 내부 가로 정렬 배치 (ncol=3)
    ax_c_trend.legend(loc="best", ncol=3, 
    frameon=True, facecolor="#1a1a24", edgecolor="none", fontsize=14)
    ax_c_trend.grid(True, axis="both", color="#2d2d3a", linestyle="-", linewidth=0.5)
    for spine in ax_c_trend.spines.values():
        spine.set_visible(False)

    # 데이터 플롯이 상단 가로 범례 박스와 물리적으로 겹치지 않도록 Y축 상단 마진 자동 보정 처리
    all_c_vals = c_net_inst + c_net_ind + c_net_frg
    c_min, c_max = min(all_c_vals), max(all_c_vals)
    c_range = (c_max - c_min) * 0.35 if (c_max - c_min) > 0 else 10
    ax_c_trend.set_ylim(c_min - (c_range*0.45), c_max + (c_range * 0.45))

    for i in range(len(dates_5)):
        y_offset = 10 if c_net_frg[i] >= 0 else -16
        v_align = "bottom" if c_net_frg[i] >= 0 else "top"
        ax_c_trend.annotate(
            f"{c_net_frg[i]:+,.0f}",
            xy=(i, c_net_frg[i]),
            textcoords="offset points",
            xytext=(0, y_offset),
            ha="center", 
            va=v_align, 
            fontsize=14, 
            color=color_frg, 
            fontweight="bold"
        )

    # ----------------------------------------------------
    # 4. 네 번째 차트: 5거래일 풋(PUT) 순매수 추이 (상단 내부 가로형 범례)
    # ----------------------------------------------------
    ax_p_trend.set_facecolor("#1a1a24")
    ax_p_trend.plot(dates_5, p_net_inst, color=color_inst, linestyle="-", marker="x", linewidth=1.2, label="기관")
    ax_p_trend.plot(dates_5, p_net_ind, color=color_ind, linestyle="-", marker="x", linewidth=1.2, label="개인")
    ax_p_trend.plot(dates_5, p_net_frg, color=color_frg, linestyle="-", marker="x", linewidth=1.2, label="외인")
    ax_p_trend.axhline(0, color="#57606f", linestyle="-", linewidth=1.2, alpha=0.8)
    
    ax_p_trend.set_title(f"■ 최근 5거래일 풋(PUT) 옵션 주체별 순거래 추이", 
    fontsize=16, fontweight="bold", pad=12, color="#ffffff", loc="left")
    ax_p_trend.tick_params(axis='x', colors="#dee2e6", labelsize=14)
    ax_p_trend.tick_params(axis='y', colors="#adb5bd", labelsize=10)

    # 상단 내부 가로 정렬 배치 (ncol=3)
    ax_p_trend.legend(loc="best", ncol=3, 
    frameon=True, facecolor="#1a1a24", edgecolor="none", fontsize=14)
    ax_p_trend.grid(True, axis="both", color="#2d2d3a", linestyle="-", linewidth=0.5)
    for spine in ax_p_trend.spines.values():
        spine.set_visible(False)

    # 데이터 플롯이 상단 가로 범례 박스와 물리적으로 겹치지 않도록 Y축 상단 마진 자동 보정 처리
    all_p_vals = p_net_inst + p_net_ind + p_net_frg
    p_min, p_max = min(all_p_vals), max(all_p_vals)
    p_range = (p_max - p_min) * 0.35 if (p_max - p_min) > 0 else 10
    ax_p_trend.set_ylim(p_min - (p_range*0.45), p_max + (p_range * 0.45))

    for i in range(len(dates_5)):
        y_offset = 10 if p_net_frg[i] >= 0 else -16
        v_align = "bottom" if p_net_frg[i] >= 0 else "top"
        ax_p_trend.annotate(
            f"{p_net_frg[i]:+,.0f}",
            xy=(i, p_net_frg[i]),
            textcoords="offset points",
            xytext=(0, y_offset),
            ha="center", 
            va=v_align, 
            fontsize=14, color=color_frg, fontweight="bold"
        )

    # 전체 컴포넌트 여백 조율 및 깔끔한 출력 마감
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.subplots_adjust(hspace=0.40) # 상하 서브플롯 간의 적정 간격 유지
    
    output_plot_path = os.path.join(target_save_dir, f"{file_name}.png")
    plt.savefig(output_plot_path, dpi=400, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    
    print(f"  ✔ [결과 저장 과정] {output_plot_path} 저장 완료")

print("\n[완료] 모든 작업이 완료 되었습니다.")