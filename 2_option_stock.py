import os
import sys
import glob
import re
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# Windows cp949 환경에서 이모지 출력 시 터미널 크래시 방지
if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ==========================================
# [설정] 기본 경로 정의
# ==========================================
src_daily_dir = "./daily_op"
output_dir = "./picture/option_analysis"
csv_output_dir = "./op_raw"

for path in [output_dir, csv_output_dir]:
    if not os.path.exists(path):
        os.makedirs(path)

print("=" * 50)
print(" 주식 옵션 프로파일 분석 범위 설정 ")
print("=" * 50)

# 1. 분석할 주식 티커 입력 받기 (대소문자 무관하도록 upper 처리)
target_input = input("▶ 분석할 주식 종목 티커 입력 (예: sec, skh 등) (기본값 sec): ").strip()
target_prod = target_input.upper() if target_input else "SEC"

# 2. 행사가 조회 범위 동적 입력 받기 (주식 스케일에 맞춰 엔터 시 기본값 sec 기준 적용)
try:
    val_start = input("▶ 분석 시작 행사가(START_STRIKE) 입력 (기본값 230000): ").strip()
    START_STRIKE = float(val_start) if val_start else 230000.0

    val_end = input("▶ 분석 종료 행사가(END_STRIKE) 입력 (기본값 440000): ").strip()
    END_STRIKE = float(val_end) if val_end else 440000.0
except ValueError:
    print("⚠ 입력 값이 올바르지 않아 기본값(230000 ~ 440000)으로 진행합니다.")
    START_STRIKE = 230000.0
    END_STRIKE = 440000.0

print(f"-> [설정 완료] 종목: {target_prod} | 범위: {START_STRIKE:,.0f} 원 ~ {END_STRIKE:,.0f} 원")
print("=" * 50)

if not os.path.exists(output_dir):
    os.makedirs(output_dir)

import koreanize_matplotlib
# 스타일 정의 (다크 모드 유지)
plt.style.use("dark_background")
plt.rcParams["axes.unicode_minus"] = False
plt.style.use("ggplot")

# ==========================================
# [함수] KRX 옵션 CSV 전처리
# ==========================================
def load_and_preprocess_option(file_path):
    df = None
    for enc in ["cp949", "utf-8-sig", "euc-kr", "utf-8"]:
        try:
            df = pd.read_csv(file_path, encoding=enc)
            break
        except Exception:
            continue

    if df is None:
        return pd.DataFrame(columns=['종목명', '유형', '행사가', '미결제약정', '내재변동성', '거래량'])

    df.columns = df.columns.str.strip().str.replace('"', '').str.replace("'", "")

    if '종목명' not in df.columns:
        # 혹시 컬럼명이 따옴표 깨짐 등으로 안 맞을 때를 대비해 2번째 컬럼을 종목명으로 강제 지정
        if df.shape[1] > 1:
            df.rename(columns={df.columns[1]: '종목명'}, inplace=True)
        else:
            return pd.DataFrame(columns=['종목명', '유형', '행사가', '미결제약정', '내재변동성', '거래량'])

    # 유형 분류 (문자열 공백 제거 후 비교)
    df['종목명_네임'] = df['종목명'].astype(str).str.strip()
    df['유형'] = df['종목명_네임'].apply(lambda x: '콜(CALL)' if ' C ' in x else ('풋(PUT)' if ' P ' in x else '기타'))

    # 위클리/정규물 통합 안전 행사가 추출기
    def extract_strike(name):
        name_str = str(name).strip()
        # 1. 괄호 제거 (예: "(주간)" 또는 "(야간)" 등이 붙어있으면 제거)
        name_clean = re.sub(r'\(.*\)', '', name_str).strip()

        # 2. 맨 우측의 공백을 기준으로 토큰 분할
        tokens = name_clean.split()
        if not tokens:
            return 0.0

        # 3. 맨 마지막 토큰에서 쉼표 제거 후 부동소수점 변환
        clean_token = tokens[-1].replace(',', '').strip()
        try:
            return float(clean_token)
        except ValueError:
            # 만약 정규식 추출이 더 안전한 구조라면 서브 타겟 적용
            match = re.search(r'([\d,]+\.\d+|\d+)$', name_clean)
            if match:
                return float(match.group(1).replace(',', ''))
            return 0.0

    df['행사가'] = df['종목명_네임'].apply(extract_strike)

    # 연산에 필요한 주요 수치형 컬럼 캐스팅 정형화
    target_cols = ['미결제약정', '내재변동성', '거래량']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0)
        else:
            # 위클리 파일에 해당 컬럼이 누락되어 있다면 0으로 생성하여 에러 방지
            df[col] = 0.0

    return df

# ==========================================
# STEP 1. daily 폴더 내 파일 패턴 스캔 및 대상 선정
# ==========================================
target_products = [target_prod]
all_files = glob.glob(os.path.join(src_daily_dir, "*.csv"))
valid_data_list = []

for fpath in all_files:
    fname = os.path.basename(fpath)
    match = re.match(r"^([a-zA-Z0-9]+)[_-](\d{8})\.csv$", fname)
    if match:
        prod, dt_str = match.groups()
        prod_upper = prod.strip().upper()
        target_products_upper = [p.upper() for p in target_products]
        if prod_upper in target_products_upper:
            valid_data_list.append({
                'path': fpath, 'product': prod.lower(), 'date_str': dt_str,
                'date_obj': datetime.strptime(dt_str, "%Y%m%d")
            })

if not valid_data_list:
    print("⚠ [확인 실패] daily 폴더 내에 일치하는 상품명_날짜 형식의 CSV 파일이 없습니다.")
    exit()

files_df = pd.DataFrame(valid_data_list).sort_values(by=['product', 'date_obj']).reset_index(drop=True)


target_products_loop = [str(p).strip().upper() for p in target_products]
# ==========================================
# STEP 2. 상품별 순회 처리
# ==========================================
for prod in target_products:
    plt.close('all')

    prod_files = files_df[files_df['product'].str.strip().str.upper() == prod]
    if len(prod_files) < 1:
        continue

    today_row = prod_files.iloc[-1]
    today_file_path = today_row['path']
    today_date_str = today_row['date_str']

    has_prev_data = True
    if len(prod_files) >= 2:
        prev_row = prod_files.iloc[-2]
        prev_file_path = prev_row['path']
        prev_date_str = prev_row['date_str']
    else:
        has_prev_data = False
        print(f"ℹ [{prod}] 상품의 전일 데이터가 없습니다. 당일 데이터만 단독 표기하여 진행합니다.")

    try:
        print(f"▶ [{prod}] 가공 시작 -> 대상일: {today_date_str}")

        df_today = load_and_preprocess_option(today_file_path)
        if has_prev_data:
            df_prev = load_and_preprocess_option(prev_file_path)
        else:
            # 전일 데이터가 없으면 오늘 데이터 구조를 복사해 미결제약정이 모두 0인 빈 데이터프레임 생성
            df_prev = df_today.copy()
            df_prev['미결제약정'] = 0.0

        # ----------------------------------------------------
        # ★ [핵심 추가] 전체 행사가 기준 총합 데이터 산출 (필터링 전 원본 기준)
        # ----------------------------------------------------
        total_c_today = df_today[df_today['유형'] == '콜(CALL)']['미결제약정'].sum()
        total_p_today = df_today[df_today['유형'] == '풋(PUT)']['미결제약정'].sum()

        total_c_prev = df_prev[df_prev['유형'] == '콜(CALL)']['미결제약정'].sum() if has_prev_data else 0.0
        total_p_prev = df_prev[df_prev['유형'] == '풋(PUT)']['미결제약정'].sum() if has_prev_data else 0.0

        # 총 변화량 연산
        total_c_chg = total_c_today - total_c_prev
        total_p_chg = total_p_today - total_p_prev

        # ==========================================
        # STEP 3. 등가격(ATM) 추정 및 시각화용 범위 필터링
        # ==========================================
        valid_strikes_today = df_today[df_today['유형'].isin(['콜(CALL)', '풋(PUT)'])]['행사가']
        valid_strikes_prev = df_prev[df_prev['유형'].isin(['콜(CALL)', '풋(PUT)'])]['행사가']

        if valid_strikes_today.empty:
            print(f"⚠ [{prod}] 당일 데이터에 정상적인 옵션 행사가 정보가 없어 건너뜁니다.")
            continue

        # 데이터 내 존재하는 실질 최소/최대값 산출
        data_min_strike = min(valid_strikes_today.min(), valid_strikes_prev.min() if has_prev_data else valid_strikes_today.min())
        data_max_strike = max(valid_strikes_today.max(), valid_strikes_prev.max() if has_prev_data else valid_strikes_today.max())

        # 수동 설정값과 실제 데이터 경계값을 비교하여 유연하게 가변 적용
        current_start = max(START_STRIKE, data_min_strike)
        current_end = min(END_STRIKE, data_max_strike)

        if current_start > current_end:
            print(f"⚠ [{prod}] 수동 지정 범위가 실제 데이터 범위와 전혀 겹치지 않아 가공을 건너뜁니다. (데이터 범위: {data_min_strike} ~ {data_max_strike})")
            continue

        # 조정된 동적 범위로 필터링 실행
        filter_condition = (df_today['행사가'] >= current_start) & (df_today['행사가'] <= current_end)
        atm_today_raw = df_today[filter_condition].sort_values('행사가')

        call_today_raw = atm_today_raw[atm_today_raw['유형'] == '콜(CALL)'].set_index('행사가')
        put_today_raw = atm_today_raw[atm_today_raw['유형'] == '풋(PUT)'].set_index('행사가')
        today_strikes = call_today_raw.index.intersection(put_today_raw.index)

        prev_filter_condition = (df_prev['행사가'] >= current_start) & (df_prev['행사가'] <= current_end)
        atm_prev_raw = df_prev[prev_filter_condition]

        call_prev_raw = atm_prev_raw[atm_prev_raw['유형'] == '콜(CALL)'].set_index('행사가')
        put_prev_raw = atm_prev_raw[atm_prev_raw['유형'] == '풋(PUT)'].set_index('행사가')
        prev_strikes = call_prev_raw.index.intersection(put_prev_raw.index)

        strike_prices = today_strikes.union(prev_strikes).sort_values()

        if strike_prices.empty:
            print(f"⚠ [{prod}] 보정된 범위({current_start} ~ {current_end}) 내에 유효한 교차 행사가가 없습니다.")
            continue

        # 마스터 축 동기화
        call_today = call_today_raw.reindex(strike_prices, fill_value=0)
        put_today = put_today_raw.reindex(strike_prices, fill_value=0)
        call_prev = call_prev_raw.reindex(strike_prices, fill_value=0)
        put_prev = put_prev_raw.reindex(strike_prices, fill_value=0)

        call_today['미결제증감'] = call_today['미결제약정'] - call_prev['미결제약정']
        put_today['미결제증감'] = put_today['미결제약정'] - put_prev['미결제약정']

        # 파일 내보내기
        csv_data_list = []
        for strike in strike_prices:
            csv_data_list.append({
                "행사가": strike,
                "콜_내재변동성": call_today.loc[strike, "내재변동성"],
                "풋_내재변동성": put_today.loc[strike, "내재변동성"],
                "콜_미결제잔고": call_today.loc[strike, "미결제약정"],
                "풋_미결제잔고": put_today.loc[strike, "미결제약정"],
                "콜_미결제증감": call_today.loc[strike, "미결제증감"],
                "풋_미결제증감": put_today.loc[strike, "미결제증감"]
            })
        output_df = pd.DataFrame(csv_data_list)
        csv_output_path = os.path.join(csv_output_dir, f"option_analysis_{prod}_{today_date_str}.csv")
        output_df.to_csv(csv_output_path, index=False, encoding="utf-8-sig")

        # ==========================================
        # STEP 4. 3단 시각화 대시보드 작도 (2단 그리드 및 수직선 버그 완벽 수정본)
        # ==========================================
        fig, (ax_iv, ax_oi, ax_oi_chg) = plt.subplots(3, 1, figsize=(14, 20), gridspec_kw={'height_ratios': [1, 1, 1.1]})
        fig.patch.set_facecolor("#111116")

        title_suffix = f"({prod.upper()} / {today_date_str})"
        fig.suptitle(f"코스피200 옵션 마켓 프로파일 분석 {title_suffix}",
                     fontsize=26, fontweight="bold", y=0.98, color="#ffffff")

        # 테마 컬러
        color_call_up = "#ff2e63"
        color_call_down = "#4a0e1c"
        color_put_up = "#00adb5"
        color_put_down = "#052e3d"

        x_indexes = range(len(strike_prices))
        bar_w = 0.38

        x_labels = [f"{x:,.1f}" if float(x) % 20000 == 0 else "" for x in strike_prices]

        try:
            combined_vol = df_today.set_index('행사가').reindex(strike_prices, fill_value=0)
            atm_strike = strike_prices[combined_vol['거래량'].argmax()]
            atm_idx = list(strike_prices).index(atm_strike)
        except:
            atm_idx = len(strike_prices) // 2
            atm_strike = strike_prices[atm_idx]

        ax_iv.set_facecolor("#161622")
        ax_iv.plot(strike_prices, call_today['내재변동성'], color="#ff2e63", marker='o', linestyle="none", markersize=4, label='콜 IV')
        ax_iv.plot(strike_prices, put_today['내재변동성'], color="#00adb5", marker='s', linestyle="none", markersize=4, label='풋 IV')
        ax_iv.set_title("■ 행사가별 내재변동성 (Volatility Smile)", fontsize=16, fontweight="semibold", pad=10, loc="left", color="#ffffff")
        ax_iv.legend(loc="best", frameon=False, fontsize=15)
        ax_iv.grid(True, color="#2d2d3a", linewidth=0.5, linestyle=":")
        ax_iv.set_xticks(strike_prices)
        ax_iv.set_xticklabels(x_labels, color="#ffffff", fontsize=11, ha="center")
        ax_iv.axvline(atm_strike, color="#f1c40f", linestyle="--", linewidth=1.2, alpha=0.8)
        for spine in ax_iv.spines.values(): spine.set_visible(False)

        ax_oi.set_facecolor("#161622")
        bar_w_oi = 0.35
        ax_oi.bar([x - bar_w_oi/2 for x in x_indexes], call_today['미결제약정'], width=bar_w_oi, color="#ff2e63", alpha=0.85, label='콜 총잔고', zorder=2)
        ax_oi.bar([x + bar_w_oi/2 for x in x_indexes], put_today['미결제약정'], width=bar_w_oi, color="#00adb5", alpha=0.85, label='풋 총잔고', zorder=2)

        ax_oi.set_title(f"■ 행사가별 당일 미결제약정 총 잔고 현황 (추정 ATM: {atm_strike:.1f})", fontsize=16, fontweight="semibold", pad=10, loc="left", color="#ffffff")
        ax_oi.legend(loc="best", frameon=False, fontsize=15)

        x_labels_oi = [f"{x:,.1f}" if float(x) % 20000 == 0 else "" for x in strike_prices]
        ax_oi.set_xticks(x_indexes)
        ax_oi.set_xticklabels(x_labels_oi, color="#ffffff", fontsize=11, ha="center")
        ax_oi.tick_params(axis='x', direction='out', length=4, width=1.0)

        for idx, strike in enumerate(strike_prices):
            if float(strike) % 20 == 0:
                ax_oi.axvline(idx, color="#ffffff", linewidth=0.5, alpha=0.1, zorder=1)

        ax_oi.axvline(atm_idx, color="#f1c40f", linestyle="--", linewidth=1.0, alpha=0.4, zorder=1)
        ax_oi.text(atm_idx, ax_oi.get_ylim()[1], f"⚠ {atm_strike:.1f}", color="#f1c40f", fontsize=11, fontweight="bold", va="center", ha="center", bbox=dict(facecolor='#111116', alpha=0.8, edgecolor='none', pad=3), zorder=4)

        ax_oi.grid(True, axis='y', color="#373743", linewidth=0.5, linestyle=":", zorder=1)
        ax_oi.grid(True, axis='x', color="#2d2d3a", linewidth=0.5, linestyle=":", alpha=0.8, zorder=1)
        for spine in ax_oi.spines.values(): spine.set_visible(False)

        max_oi_val = max(call_today['미결제약정'].max(), put_today['미결제약정'].max())
        if pd.isna(max_oi_val) or max_oi_val <= 0: max_oi_val = 10
        ax_oi.set_ylim(0, max_oi_val * 1.15)

        call_threshold = call_today['미결제약정'].nlargest(5).iloc[-1] if len(call_today) >= 5 else 0
        put_threshold = put_today['미결제약정'].nlargest(5).iloc[-1] if len(put_today) >= 5 else 0

        for idx, val in enumerate(call_today['미결제약정']):
            if val >= call_threshold and val > 500:
                ax_oi.annotate(f"{val:,.0f}", xy=(idx - bar_w_oi/2, val), textcoords="offset points",
                               xytext=(0, 4), ha="center", va="bottom", fontsize=11,
                               color="#ff2e63", fontweight="bold", zorder=3)
        for idx, val in enumerate(put_today['미결제약정']):
            if val >= put_threshold and val > 500:
                ax_oi.annotate(f"{val:,.0f}", xy=(idx + bar_w_oi/2, val), textcoords="offset points",
                               xytext=(0, 4), ha="center", va="bottom", fontsize=11,
                               color="#00adb5", fontweight="bold", zorder=3)

        ax_oi_chg.set_facecolor("#161622")

        if has_prev_data:
            call_display_val = call_today['미결제증감']
            put_display_val = -put_today['미결제증감']

            c_colors = [color_call_up if v >= 0 else color_call_down for v in call_today['미결제증감']]
            p_colors = [color_put_up if v >= 0 else color_put_down for v in put_today['미결제증감']]

            ax_oi_chg.bar(x_indexes, call_display_val, width=0.6, color=c_colors, alpha=0.9, zorder=2)
            ax_oi_chg.bar(x_indexes, put_display_val, width=0.6, color=p_colors, alpha=0.9, zorder=2)

            max_chg_val = max(call_today['미결제증감'].abs().max(), put_today['미결제증감'].abs().max())
            if pd.isna(max_chg_val) or max_chg_val <= 0: max_chg_val = 10
            ax_oi_chg.set_ylim(-max_chg_val * 1.25, max_chg_val * 1.25)

            for idx, val in enumerate(call_today['미결제증감']):
                if abs(val) > (max_chg_val * 0.08):
                    y_off = 3 if val >= 0 else -10
                    v_align = "bottom" if val >= 0 else "top"
                    ax_oi_chg.annotate(f"{val:+,.0f}", xy=(idx, val), textcoords="offset points",
                                       xytext=(0, y_off), ha="center", va=v_align, fontsize=11,
                                       color="#ff2e63", fontweight="bold", zorder=3)

            for idx, val in enumerate(put_today['미결제증감']):
                if abs(val) > (max_chg_val * 0.08):
                    disp_y = -val
                    v_align = "top" if val >= 0 else "bottom"
                    ax_oi_chg.annotate(f"{val:+,.0f}", xy=(idx, disp_y), textcoords="offset points",
                                       xytext=(0, -10 if val >= 0 else 3), ha="center", va=v_align, fontsize=11,
                                       color="#00adb5", fontweight="bold", zorder=3)

            ax_oi_chg.text(0.02, 0.88, "▲ 콜 잔고 증가\n▼ 콜 잔고 감소(청산)", transform=ax_oi_chg.transAxes, color="#ff2e63", fontsize=13, fontweight="semibold")
            ax_oi_chg.text(0.02, 0.05, "▲ 풋 잔고 감소(청산)\n▼ 풋 잔고 증가", transform=ax_oi_chg.transAxes, color="#00adb5", fontsize=13, fontweight="semibold")
        else:
            ax_oi_chg.text(0.5, 0.5, "⚠ 전일 데이터 부재로 인해\n순증감 변동 내역을 출력할 수 없습니다.",
                          transform=ax_oi_chg.transAxes, color="#ff4d4d", alpha=0.8, ha="center", va="center", fontsize=16, fontweight="bold")
            ax_oi_chg.set_ylim(-10, 10)

        ax_oi_chg.axhline(0, color="#ffffff", linewidth=0.8, alpha=0.3, zorder=1)
        ax_oi_chg.axvline(atm_idx, color="#f1c40f", linestyle="--", linewidth=1.0, alpha=0.4, zorder=1)
        ax_oi_chg.text(atm_idx, ax_oi_chg.get_ylim()[1], f"⚠ {atm_strike:.1f}",
                       color="#f1c40f", fontsize=11, fontweight="bold", va="center", ha="center",
                       bbox=dict(facecolor='#111116', alpha=0.8, edgecolor='none', pad=3), zorder=4)

        ax_oi_chg.set_title("■ 행사가별 미결제약정 전일 대비 순증감 (Up: 콜 전장 / Down: 풋 전장)", fontsize=16, fontweight="semibold", pad=10, loc="left", color="#ffffff")
        ax_oi_chg.set_xticks(x_indexes)
        ax_oi_chg.set_xticklabels(x_labels_oi, color="#ffffff", fontsize=11, ha="center")
        ax_oi_chg.tick_params(axis='x', direction='out', length=4, width=1.0)

        for idx, strike in enumerate(strike_prices):
            if float(strike) % 20 == 0:
                ax_oi_chg.axvline(idx, color="#ffffff", linewidth=0.5, alpha=0.1, zorder=1)

        ax_oi_chg.grid(True, axis='y', color="#2d2d3a", linewidth=0.5, linestyle=":", zorder=1)
        ax_oi_chg.grid(True, axis='x', color="#2d2d3a", linewidth=0.5, linestyle=":", alpha=0.5, zorder=1)
        for spine in ax_oi_chg.spines.values(): spine.set_visible(False)

        label_chg_c = f"{total_c_chg:+,.0f}" if has_prev_data else "N/A"
        label_chg_p = f"{total_p_chg:+,.0f}" if has_prev_data else "N/A"

        table_data = [
            [f"{total_c_today:,.0f}", f"{total_p_today:,.0f}"],
            [label_chg_c, label_chg_p]
        ]
        columns = ["총 콜(CALL) 미결제", "총 풋(PUT) 미결제"]
        rows = ["당일 총 미결제 잔고", "전일 대비 총 변화량"]

        c_chg_color = "#ff4d7d" if total_c_chg >= 0 else "#4ade80"
        p_chg_color = "#00ced1" if total_p_chg >= 0 else "#4ade80"
        if not has_prev_data:
            c_chg_color = p_chg_color = "#888888"

        opt_table = ax_oi_chg.table(
            cellText=table_data, rowLabels=rows, colLabels=columns,
            loc="bottom", cellLoc="center", rowLoc="center", bbox=[0.08, -0.45, 0.84, 0.24]
        )

        opt_table.auto_set_font_size(False)
        opt_table.set_fontsize(15)

        for (row, col), cell in opt_table.get_celld().items():
            cell.set_linewidth(0.6)
            cell.set_edgecolor("#3d3d4e")

            if row == 0:
                cell.set_facecolor("#22222a")
                cell.get_text().set_color("#ffffff")
                cell.get_text().set_weight("bold")
            elif col == -1:
                cell.set_facecolor("#1a1a24")
                cell.get_text().set_color("#aaaaaa")
            else:
                cell.set_facecolor("#16161d")
                if row == 1:
                    cell.get_text().set_color(color_call_up if col == 0 else color_put_up)
                    cell.get_text().set_weight("semibold")
                elif row == 2:
                    cell.get_text().set_color(c_chg_color if col == 0 else p_chg_color)
                    cell.get_text().set_weight("semibold")

        plt.tight_layout(rect=[0, 0.05, 1, 0.95])
        plt.subplots_adjust(hspace=0.42)

        output_path = os.path.join(output_dir, f"option_profile_{prod}_{today_date_str}.png")
        plt.savefig(output_path, dpi=400, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close()
        print(f"   -> [분석 가공 완료] 이미지: {output_path} | 데이터: {csv_output_path}")

    except Exception as e:
        print(f"   ⚠ [가공 실패] {prod} 상품 가공 중 예상치 못한 연산 오류 발생: {e}")

    finally:
        plt.close('all')
