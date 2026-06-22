import os
import sys
import glob
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from scipy.stats import norm
import urllib.request
import json

# Windows cp949 환경에서 이모지 출력 시 터미널 크래시 방지
if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ==========================================
# [함수] 환경 변수 로더 및 ECOS 금리 조회
# ==========================================
def load_env(path=".env"):
    """
    외부 패키지 없이 .env 파일을 읽어 os.environ에 등록하는 Vanilla Python 함수
    """
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()

def fetch_ecos_rate(api_key):
    """
    한국은행 ECOS API를 통해 최근 7일 내의 국고채 3년물 시장금리를 조회하여 반환
    """
    if not api_key:
        return None
    
    today_dt = datetime.today()
    start_dt = today_dt - timedelta(days=7)
    
    start_date = start_dt.strftime("%Y%m%d")
    end_date = today_dt.strftime("%Y%m%d")
    
    # 시장금리(일별) 통계표: 817Y002 / 국고채(3년) 항목: 010200000 / 주기: D
    url = f"http://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/10/817Y002/D/{start_date}/{end_date}/010200000"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            if "StatisticSearch" in res_data and "row" in res_data["StatisticSearch"]:
                rows = res_data["StatisticSearch"]["row"]
                if rows:
                    sorted_rows = sorted(rows, key=lambda x: x.get("TIME", ""), reverse=True)
                    latest_val = sorted_rows[0].get("DATA_VALUE")
                    if latest_val:
                        rate = float(latest_val) / 100.0
                        print(f"▶ [ECOS 연동 성공] 최근 영업일({sorted_rows[0].get('TIME')}) 국고채 3년 금리: {latest_val}% -> 적용 금리: {rate:.5f}")
                        return rate
    except Exception as e:
        print(f"⚠ [ECOS 연동 실패] 한국은행 금리 데이터를 가져오지 못했습니다: {e}")
    return None

# 환경 변수 로드
load_env()


# ==========================================
# [설정 1] 경로 정의 (1단 구성 계승)
# ==========================================
src_daily_dir = os.path.normpath("./daily_op")
output_dir = os.path.normpath("./picture/option_greeks")
csv_output_dir = os.path.normpath("./op_greeks_raw")

for path in [output_dir, csv_output_dir]:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

import koreanize_matplotlib
# 스타일 정의 (다크 모드 및 Pretendard 폰트 유지)
plt.style.use("dark_background")
plt.rcParams["axes.unicode_minus"] = False
plt.style.use("ggplot")

# ==========================================
# [설정 2] 실행 시 수동 변수 입력 구역 (동적 입력 전환)
# ==========================================
print("=" * 50)
print(" 국장 주식 옵션입체 그릭스 분석 설정 ")
print("=" * 50)


target_input = input("▶ 분석할 주식 티커 입력 (예: sec, skh) ").strip().upper()
target_prod = target_input if target_input else "sec"
target_products = [target_prod]

# 1. 기초자산 및 이자율 입력
try:
    val_S = input("▶ 기초자산 가격 입력 (기본값 353500): ").strip()
    S = float(val_S) if val_S else 353500.0
    
    ecos_key = os.environ.get("ECOS_API_KEY")
    fetched_r = fetch_ecos_rate(ecos_key)
    
    default_r = fetched_r if fetched_r is not None else 0.0253
    default_r_percent = default_r * 100
    
    val_r = input(f"▶ 무위험 이자율 입력 (예: {default_r_percent:.2f}% -> {default_r:.4f}) (기본값 {default_r:.4f}): ").strip()
    r = float(val_r) if val_r else default_r
except ValueError:
    default_r = 0.0253
    print(f"⚠ 입력 값이 올바르지 않아 기본값(S=353500, r={default_r:.4f})으로 진행합니다.")
    S = 353500.0
    r = default_r

# 2. 상품별 만기일수(T_days) 입력 처리
expiry_dict = {}
print("\n[각 주식 상품별 잔여 만기 영업일수(T_days) 입력]")
print("※ 그냥 엔터를 누르면 기본값(14일)이 적용됩니다.")

try:
    t_sec = input(f" - {target_prod.upper()} 옵션 잔여 만기일수 (기본 14): ").strip()
    expiry_dict[target_prod] = float(t_sec) if t_sec else 14.0
except ValueError:
    print("⚠ 입력 오류로 인해 만기일수가 기본값으로 셋팅됩니다.")
    expiry_dict = {target_prod: 14.0}

print("=" * 50)

# ==========================================
# [함수] 블랙-숄즈 그릭스 계산 엔진
# ==========================================
def calculate_bs_greeks(S, K, T, r, sigma, option_type='call'):
    if T <= 0 or sigma <= 0:
        return 0.0, 0.0, 0.0, 0.0

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    # 1. 델타
    if option_type == 'call':
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1.0

    # 2. 감마
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))

    # 3. 바나 (Vanna)
    vanna = -norm.pdf(d1) * d2 / sigma

    # 4. 세타 (Theta)
    if option_type == 'call':
        theta = (- (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 252.0
    else:
        theta = (- (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 252.0

    return delta, gamma, vanna, theta

# ==========================================
# [함수] 전통적 MaxPain 계산기
# ==========================================
def calculate_traditional_max_pain(df_filtered):
    strikes = df_filtered['행사가'].unique()
    pain_table = {}
    
    for target_k in strikes:
        total_pain = 0.0
        for _, row in df_filtered.iterrows():
            k = row['행사가']
            oi = row['미결제약정']
            opt_type = 'call' if row['유형'] == '콜(CALL)' else 'put'
            
            if opt_type == 'call':
                payoff = max(target_k - k, 0)
            else:
                payoff = max(k - target_k, 0)
            total_pain += payoff * oi
        pain_table[target_k] = total_pain
        
    if pain_table:
        return min(pain_table, key=pain_table.get)
    return S

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
        return pd.DataFrame()
    df.columns = df.columns.str.strip().str.replace('"', '').str.replace("'", "")
    
    if '종목명' not in df.columns:
        if df.shape[1] > 1:
            df.rename(columns={df.columns[1]: '종목명'}, inplace=True)
        else:
            return pd.DataFrame()

    df['종목명_네임'] = df['종목명'].astype(str).str.strip()
    df['유형'] = df['종목명_네임'].apply(lambda x: '콜(CALL)' if ' C ' in x else ('풋(PUT)' if ' P ' in x else '기타'))
    
    def extract_strike(name):
        name_clean = re.sub(r'\(.*\)', '', str(name)).strip()
        tokens = name_clean.split()
        if not tokens: return 0.0
        try: return float(tokens[-1].replace(',', '').strip())
        except: return 0.0

    df['행사가'] = df['종목명_네임'].apply(extract_strike)
    
    # 종가 데이터 확보 (없을 경우 0.0 방어)
    if '종가' not in df.columns:
        df['종가'] = 0.0
    else:
        df['종가'] = pd.to_numeric(df['종가'].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0.0)
    
    for col in ['미결제약정', '내재변동성', '거래량']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0)
        else:
            df[col] = 0.0
    return df

# ==========================================
# MAIN EXECUTION
# ==========================================
target_products_upper = [p.upper() for p in target_products]
all_files = glob.glob(os.path.join(src_daily_dir, "*.csv"))
valid_data_list = []

for fpath in all_files:
    fname = os.path.basename(fpath)
    match = re.match(r"^([a-zA-Z0-9]+)[_-](\d{8})\.csv$", fname)
    if match:
        prod, dt_str = match.groups()
        prod_upper = prod.strip().upper()
        if prod_upper in target_products_upper:
            valid_data_list.append({
                'path': fpath, 'product': prod.lower(), 'date_str': dt_str,
                'date_obj': datetime.strptime(dt_str, "%Y%m%d")
            })

if not valid_data_list:
    print(f"⚠ [{target_prod.upper()}]에 해당하는 대상 CSV 파일이 {src_daily_dir} 폴더에 없습니다.")
    print(f"   (탐색 타겟: {target_products_upper}, 발견된 총 마킹 파일 수: {len(all_files)}개)")
    exit()

files_df = pd.DataFrame(valid_data_list).sort_values(by=['product', 'date_obj']).reset_index(drop=True)

print(f"\n[정렬 완료 데이터 요약]")
print(files_df[['product', 'date_str']])
print("-" * 50)

target_products_loop = [str(p).strip().upper() for p in target_products]

for prod in target_products_loop:
    plt.close('all')
    prod_files = files_df[files_df['product'].str.strip().str.upper() == prod]
    if len(prod_files) < 1: 
        print(f"⚠ [{prod}] 티커에 해당하는 정제된 데이터셋(prod_files)이 비어있어 루프를 건너뜁니다.")
        continue
        
    today_row = prod_files.iloc[-1]
    today_file_path = today_row['path']
    today_date_str = today_row['date_str']

    try:
        days_to_expiry = expiry_dict.get(prod.lower(), expiry_dict.get(prod, 14.0))
        if days_to_expiry <= 0:
            days_to_expiry = 0.5
            
        # 연 단위 만기 변환 (영업일 기준 252 적용)
        T = days_to_expiry / 252.0
        
        print(f"\n🚀 [{prod}] 최종 시뮬레이션 진입 완료!")
        print(f"   -> 사용 파일: {today_file_path}")
        print(f"   -> 적용 만기 시차(T): {T:.5f}")
        
        df_today = load_and_preprocess_option(today_file_path)
        if df_today.empty: continue

        df_base = df_today[df_today['유형'].isin(['콜(CALL)', '풋(PUT)'])].copy()
        if df_base.empty: continue

        base_greeks = []
        for _, row in df_base.iterrows():
            k = row['행사가']
            opt_type = 'call' if row['유형'] == '콜(CALL)' else 'put'
            iv = row['내재변동성'] / 100.0 if row['내재변동성'] > 1.0 else row['내재변동성']
            if iv <= 0: iv = 0.20

            delta, _, _, _ = calculate_bs_greeks(S, k, T, r, iv, option_type=opt_type)
            base_greeks.append({"행사가": k, "유형": row['유형'], "순수델타": delta, "row_data": row})

        df_calc = pd.DataFrame(base_greeks)

        # ------------------------------------------
        # 2. [핵심] 콜 델타 0.25 / 풋 델타 -0.25 기반 동적 밴드 탐색
        # ------------------------------------------
        c_deltas = df_calc[df_calc['유형'] == '콜(CALL)']
        p_deltas = df_calc[df_calc['유형'] == '풋(PUT)']

        # 전수 유효 행사가 목록 정렬 수집
        all_sorted_strikes = sorted(df_calc['행사가'].unique())
        
        # 델타 마일스톤 행사가 탐색
        strike_at_delta_25 = c_deltas.loc[(c_deltas['순수델타'] - 0.25).abs().idxmin(), '행사가'] if not c_deltas.empty else S
        strike_at_put_25   = p_deltas.loc[(p_deltas['순수델타'] - (-0.25)).abs().idxmin(), '행사가'] if not p_deltas.empty else S

        # 정렬된 리스트에서의 인덱스 위치 추출
        try:
            put_25_idx = all_sorted_strikes.index(strike_at_put_25)
            # 풋 -0.25 지점으로부터 하방으로 12개 행사가 이동 (없다면 최하단 0번 인덱스 방어)
            start_idx = max(0, put_25_idx - 5)
            START_STRIKE = all_sorted_strikes[start_idx]
        except (ValueError, IndexError):
            START_STRIKE = all_sorted_strikes[0]

        try:
            call_25_idx = all_sorted_strikes.index(strike_at_delta_25)
            # 콜 0.25 지점으로부터 상방으로 12개 행사가 이동 (없다면 최상단 마지막 인덱스 방어)
            end_idx = min(len(all_sorted_strikes) - 1, call_25_idx + 5)
            END_STRIKE = all_sorted_strikes[end_idx]
        except (ValueError, IndexError):
            END_STRIKE = all_sorted_strikes[-1]

        print(f"   -> [동적 밴드 확정] 기준마디: Put_25({strike_at_put_25:,.0f}) ~ Call_25({strike_at_delta_25:,.0f})")
        print(f"   -> [최종 시각화 범위]: {START_STRIKE:,.0f} ~ {END_STRIKE:,.0f} (총 {end_idx - start_idx + 1}개 행사가 마디)")

        # ------------------------------------------
        # 3. 확정된 동적 범위를 기준으로 최종 필터링 데이터셋 빌드
        # ------------------------------------------
        df_filtered = df_base[(df_base['행사가'] >= START_STRIKE) & (df_base['행사가'] <= END_STRIKE)].sort_values('행사가')
        if df_filtered.empty: continue

        # 4) 전통적 맥스페인 계산 및 최종 그릭스 노출도 집계 진입
        traditional_max_pain = calculate_traditional_max_pain(df_filtered)

        greeks_results = []
        for _, row in df_filtered.iterrows():
            k = row['행사가']
            opt_type = 'call' if row['유형'] == '콜(CALL)' else 'put'
            iv = row['내재변동성'] / 100.0 if row['내재변동성'] > 1.0 else row['내재변동성']
            if iv <= 0: iv = 0.20

            delta, gamma, vanna, theta = calculate_bs_greeks(S, k, T, r, iv, option_type=opt_type)
            
            multiplier = 1.0 if opt_type == 'call' else -1.0
            oi = row['미결제약정']
            price = row['종가']
            
            dex = delta * oi * S * multiplier * 0.1
            gex = gamma * oi * S * multiplier
            vex = vanna * oi * S * multiplier
            tex = theta * oi * multiplier

            greeks_results.append({
                "행사가": k, "유형": row['유형'], "미결제약정": oi, "종가": price, "내재변동성_raw": row['내재변동성'],
                "순수델타": delta, "순수감마": gamma, "순수바나": vanna, "순수세타": theta,
                "DEX": dex, "GEX": gex, "Vanna_Exp": vex, "Theta_Exp": tex
            })

        res_df = pd.DataFrame(greeks_results)
        
        # Raw 데이터 CSV 백업 저장
        csv_path = os.path.join(csv_output_dir, f"option_greeks_{prod}_{today_date_str}.csv")
        res_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        
        call_df = res_df[res_df['유형'] == '콜(CALL)'].set_index('행사가')
        put_df = res_df[res_df['유형'] == '풋(PUT)'].set_index('행사가')
        
        strike_axis = call_df.index.union(put_df.index).sort_values()
        call_df = call_df.reindex(strike_axis, fill_value=0)
        put_df = put_df.reindex(strike_axis, fill_value=0)

        # Net 데이터 통합 합산
        net_dex = call_df['DEX'] + put_df['DEX']
        net_gex = call_df['GEX'] + put_df['GEX']
        net_vex = call_df['Vanna_Exp'] + put_df['Vanna_Exp']
        net_tex = call_df['Theta_Exp'] + put_df['Theta_Exp']

        # 델타 기반 타겟 행사가 추적
        call_pure_deltas = call_df['순수델타']
        put_pure_deltas = put_df['순수델타']
        
        # .loc[]을 제거하여 델타 값이 아닌 '행사가 가격(인덱스)'을 정확하게 바인딩합니다.
        strike_at_delta_25 = call_pure_deltas.abs().sub(0.25).abs().idxmin() if not call_pure_deltas.empty else S
        strike_at_put_25   = put_pure_deltas.abs().sub(0.25).abs().idxmin() if not put_pure_deltas.empty else S
        atm_strike         = strike_axis[np.abs(strike_axis.to_numpy() - S).argmin()]

        # ------------------------------------------
        # [수정] 동적 가상 시뮬레이션 기반 DEX 중립 Max Pain 계산
        # ------------------------------------------
        max_pain_strike = S  
        min_abs_dex_sum = float('inf')
        
        for virtual_S in strike_axis:
            virtual_dex_sum = 0.0
            
            for _, row in df_filtered.iterrows():
                k = row['행사가']
                opt_type = 'call' if row['유형'] == '콜(CALL)' else 'put'
                iv = row['내재변동성'] / 100.0 if row['내재변동성'] > 1.0 else row['내재변동성']
                if iv <= 0: iv = 0.20
                
                # 가상 주가 수준에 기반한 실시간 델타 재정리
                v_delta, _, _, _ = calculate_bs_greeks(virtual_S, k, T, r, iv, option_type=opt_type)
                
                multiplier = 1.0 if opt_type == 'call' else -1.0
                oi = row['미결제약정']
                
                v_dex = v_delta * oi * virtual_S * multiplier * 0.1
                virtual_dex_sum += v_dex
            
            if abs(virtual_dex_sum) < min_abs_dex_sum:
                min_abs_dex_sum = abs(virtual_dex_sum)
                max_pain_strike = virtual_S

        # IV SKEW 테이블 추출 전용 내부 매핑
        def get_skew_row(target_strike, label):
            c_iv = call_df.loc[target_strike, '내재변동성_raw'] if target_strike in call_df.index and call_df.loc[target_strike, '내재변동성_raw'] > 0 else 0.0
            p_iv = put_df.loc[target_strike, '내재변동성_raw'] if target_strike in put_df.index and put_df.loc[target_strike, '내재변동성_raw'] > 0 else 0.0
            
            c_pr = call_df.loc[target_strike, '종가'] if target_strike in call_df.index and call_df.loc[target_strike, '종가'] > 0 else "-"
            p_pr = put_df.loc[target_strike, '종가'] if target_strike in put_df.index and put_df.loc[target_strike, '종가'] > 0 else "-"
            
            c_pr_str = f"{c_pr:,.0f}" if isinstance(c_pr, (int, float)) else "-"
            p_pr_str = f"{p_pr:,.0f}" if isinstance(p_pr, (int, float)) else "-"
            
            c_iv_str = f"{c_iv:.1f}%" if c_iv > 0 else "-"
            p_iv_str = f"{p_iv:.1f}%" if p_iv > 0 else "-"
            
            return [label, f"{target_strike:,.0f}", c_iv_str, p_iv_str, c_pr_str, p_pr_str]

        skew_data = [
            get_skew_row(strike_at_delta_25, "Call Delta 0.25 (OTM Call)"),
            get_skew_row(atm_strike, "ATM Level (등가격)"),
            get_skew_row(strike_at_put_25, "Put Delta -0.25 (OTM Put)")
        ]

        # 통계 지표 및 추정 위험 범위 도출
        gamma_trap_strike = net_gex.abs().idxmax()
        upper_candidates = net_gex[net_gex.index > S]
        if not upper_candidates.empty and upper_candidates.max() > 0:
            u_threshold = upper_candidates.quantile(0.85)
            upper_band = upper_candidates[upper_candidates >= u_threshold].index.min()
        else:
            upper_band = S * 1.05

        lower_candidates = net_gex[net_gex.index < S]
        if not lower_candidates.empty and lower_candidates.min() < 0:
            l_threshold = lower_candidates.quantile(0.15)
            lower_band = lower_candidates[lower_candidates <= l_threshold].index.max()
        else:
            lower_band = S * 0.95

        abs_total = net_dex.abs() + net_gex.abs() + net_vex.abs()
        top5_strikes = abs_total.nlargest(5).index.tolist()
        top5_str = ", ".join([f"{x:,.0f}" for x in top5_strikes])

        # ==========================================
        # STEP 3. 대시보드 시각화 레이아웃 드로잉
        # ==========================================
        fig = plt.figure(figsize=(18, 42)) 
        fig.patch.set_facecolor("#21212A")
        
        title_suffix = f"({prod.upper()} / {today_date_str} / 기초자산: {S:,.0f})"
        fig.suptitle(f"주식 옵션 입체 그릭스 분석 대시보드 {title_suffix}", 
                     fontsize=28, fontweight="bold", color="#ffffff", y=0.985)

        gs = fig.add_gridspec(5, 2, height_ratios=[1.0, 0.22, 1.8, 1.1, 1.2], hspace=0.15, wspace=0.15)
        
        ax_dex = fig.add_subplot(gs[0, :])
        ax_table = fig.add_subplot(gs[1, :]) 
        ax_gex = fig.add_subplot(gs[2, 0])
        ax_vex = fig.add_subplot(gs[2, 1])
        ax_the = fig.add_subplot(gs[3, :])
        ax_report = fig.add_subplot(gs[4, :]) 

        fig.subplots_adjust(top=0.95, bottom=0.05, left=0.07, right=0.93)

        y_indexes = np.arange(len(strike_axis))
        # 주식 스케일에 알맞게 일정한 마디 가격마다 라벨링되도록 유연화 처리
        y_labels = [f"{x:,.0f}" if i % 2 == 0 else "" for i, x in enumerate(strike_axis)]

        c_color = "#FFC000"       # 콜: 골드
        p_color = "#00B0F0"       # 풋: 스카이블루
        net_bar_color = "#ff0066"  # Net선 마킹

        # ------------------------------------------
        # ① 델타 익스포져 (DEX) + 마킹 수직선들
        # ------------------------------------------
        ax_dex.set_facecolor("#161622")
        ax_dex.bar(y_indexes, call_df['DEX'], width=0.6, color=c_color, alpha=0.85, label="콜 DEX")
        ax_dex.bar(y_indexes, put_df['DEX'], width=0.6, color=p_color, alpha=0.85, label="풋 DEX")
        
        curr_y_pos = np.abs(strike_axis.to_numpy() - S).argmin()
        ax_dex.axvline(curr_y_pos, color="#FFFF00", linestyle=":", linewidth=1.5, label=f"현재가 위치 ({S:,.0f})")
        
        idx_c25 = strike_axis.get_loc(strike_at_delta_25)
        idx_p25 = strike_axis.get_loc(strike_at_put_25)
        ax_dex.axvline(idx_c25, color="#00FFCC", linestyle="--", linewidth=1.5, label=f"Delta 0.25 ({strike_at_delta_25:,.0f})")
        ax_dex.axvline(idx_p25, color="#FF00FF", linestyle="--", linewidth=1.5, label=f"Delta -0.25 ({strike_at_put_25:,.0f})")

        ax_dex.set_title("■ 델타 익스포져 (Delta Exposure - DEX)", fontsize=18, fontweight="semibold", pad=12, loc="left", color="#ffffff")
        ax_dex.set_xticks(y_indexes)
        ax_dex.set_xticklabels(y_labels, color="#ffffff", fontsize=14, rotation=45)
        ax_dex.grid(True, axis='y', color="#2d2d3a", linewidth=0.5, linestyle=":", alpha=0.6)
        ax_dex.grid(True, axis='x', color="#2d2d3a", linewidth=0.5, linestyle=":", alpha=0.6)
        ax_dex.legend(loc="upper right", frameon=False, fontsize=13)
        for spine in ax_dex.spines.values(): spine.set_visible(False)

        # ------------------------------------------
        # ② IV SKEW & 듀얼 MAXPAIN 출력용 보드 테이블
        # ------------------------------------------
        ax_table.set_facecolor("#21212A")
        ax_table.axis('off')
        
        table_columns = ["구분", "기준 행사가", "콜 IV", "풋 IV", "콜 종가", "풋 종가"]
        table_obj = ax_table.table(cellText=skew_data, colLabels=table_columns, loc="center", cellLoc="center", colColours=["#222230"] * 6)
        table_obj.auto_set_font_size(False)
        table_obj.set_fontsize(14)
        table_obj.scale(1.0, 1.8)
        
        for (row, col), cell in table_obj.get_celld().items():
            cell.set_text_props(color="#ffffff", fontweight="medium")
            cell.set_edgecolor("#2d2d3a")
            if row == 0:
                cell.set_text_props(fontweight="bold", color="#FFC000")
                cell.set_facecolor("#1d1d2b")
            else:
                cell.set_facecolor("#161622")

        pain_text = f" [전통적 MaxPain]: {traditional_max_pain:,.0f} 원   |   [DEX 총합 중립 MaxPain]: {max_pain_strike:,.0f} 원"
        ax_table.text(0.5, -0.1, pain_text, color="#00FFCC", fontsize=16, fontweight="bold", ha="center", va="center",
                      bbox=dict(facecolor='#1d1d29', alpha=0.8, edgecolor='#ff0066', boxstyle="round,pad=0.5"))

        # ------------------------------------------
        # ③ 감마 익스포져 (GEX 매물대벽)
        # ------------------------------------------
        ax_gex.set_facecolor("#161622")
        ax_gex.barh(y_indexes, call_df['GEX'], height=0.6, color=c_color, alpha=0.75, label="콜 GEX", zorder=2)
        ax_gex.barh(y_indexes, put_df['GEX'], height=0.6, color=p_color, alpha=0.75, label="풋 GEX", zorder=2)
        ax_gex.barh(y_indexes, net_gex, height=0.6, color=net_bar_color, alpha=0.9, label="Net GEX", zorder=4)

        ax_gex.axhline(idx_c25, color="#00FFCC", linestyle="--", linewidth=1.5, label=f"Delta 0.25 ({strike_at_delta_25:,.0f})")
        ax_gex.axhline(idx_p25, color="#FF00FF", linestyle="--", linewidth=1.5, label=f"Delta -0.25 ({strike_at_put_25:,.0f})")
        ax_gex.axhline(curr_y_pos, color="#FFFF00", linestyle=":", linewidth=1.5)

        ax_gex.set_title("■ 감마 익스포져 (GEX & Net)", fontsize=18, fontweight="semibold", pad=12, loc="left", color="#ffffff")
        ax_gex.set_yticks(y_indexes)
        ax_gex.set_yticklabels(y_labels, color="#ffffff", fontsize=14)
        ax_gex.axvline(0, color="#ffffff", linewidth=0.8, alpha=0.8, zorder=1)
        ax_gex.grid(True, axis='x', color="#2d2d3a", linewidth=0.5, linestyle=":", zorder=1, alpha=0.6)
        ax_gex.grid(True, axis='y', color="#2d2d3a", linewidth=0.5, linestyle=":", zorder=1, alpha=0.6)
        ax_gex.legend(loc="lower right", frameon=False, fontsize=13)
        for spine in ax_gex.spines.values(): spine.set_visible(False)

        # ------------------------------------------
        # ④ 바나 익스포져 (VEX 매물대벽)
        # ------------------------------------------
        ax_vex.set_facecolor("#161622")
        ax_vex.barh(y_indexes, call_df['Vanna_Exp'], height=0.6, color=c_color, alpha=0.75, label="콜 Vanna", zorder=2)
        ax_vex.barh(y_indexes, put_df['Vanna_Exp'], height=0.6, color=p_color, alpha=0.75, label="풋 Vanna", zorder=2)
        ax_vex.barh(y_indexes, net_vex, height=0.6, color=net_bar_color, alpha=0.9, label="Net Vanna", zorder=4)
        
        ax_vex.axhline(idx_c25, color="#00FFCC", linestyle="--", linewidth=1.5, label=f"Delta 0.25 ({strike_at_delta_25:,.0f})")
        ax_vex.axhline(idx_p25, color="#FF00FF", linestyle="--", linewidth=1.5, label=f"Delta -0.25 ({strike_at_put_25:,.0f})")
        ax_vex.axhline(curr_y_pos, color="#FFFF00", linestyle=":", linewidth=1.5)

        ax_vex.set_title("■ 바나 익스포져 (VEX & Net)", fontsize=18, fontweight="semibold", pad=12, loc="left", color="#ffffff")
        ax_vex.set_yticks(y_indexes)
        ax_vex.set_yticklabels(y_labels, color="#ffffff", fontsize=14)
        ax_vex.axvline(0, color="#ffffff", linewidth=0.8, alpha=0.8, zorder=1)
        ax_vex.grid(True, axis='x', color="#2d2d3a", linewidth=0.5, linestyle=":", zorder=1, alpha=0.6)
        ax_vex.grid(True, axis='y', color="#2d2d3a", linewidth=0.5, linestyle=":", zorder=1, alpha=0.6)
        ax_vex.legend(loc="lower right", frameon=False, fontsize=13)
        for spine in ax_vex.spines.values(): spine.set_visible(False)

        # ------------------------------------------
        # ⑤ 세타 융합 패널 (Theta Smile & TEX Curve)
        # ------------------------------------------
        ax_the.set_facecolor("#161622")
        ax_the.plot(y_indexes, call_df['순수세타'], color=c_color, linestyle="-", linewidth=1.8, marker="o", markersize=2.5, label="콜 순수 세타")
        ax_the.plot(y_indexes, put_df['순수세타'], color=p_color, linestyle="-", linewidth=1.8, marker="x", markersize=3.5, label="풋 순수 세타")
        ax_the.set_ylabel("쎄타 가치변동", color="#aaaaaa", fontsize=10)
        
        ax_the.axvline(idx_c25, color="#00FFCC", linestyle="--", linewidth=1.5, label=f"Delta 0.25 ({strike_at_delta_25:,.0f})")
        ax_the.axvline(idx_p25, color="#FF00FF", linestyle="--", linewidth=1.5, label=f"Delta -0.25 ({strike_at_put_25:,.0f})")
        ax_the.axvline(curr_y_pos, color="#FFFF00", linestyle=":", linewidth=1.5)

        ax_tex = ax_the.twinx()
        ax_tex.fill_between(y_indexes, call_df['Theta_Exp'], color=c_color, alpha=0.12, label="콜 쎄타 노출도")
        ax_tex.fill_between(y_indexes, put_df['Theta_Exp'], color=p_color, alpha=0.12, label="풋 쎄타 노출도")
        ax_tex.plot(y_indexes, net_tex, color="#ff4d4d", linestyle=":", linewidth=1.2, alpha=0.7, label="Net 쎄타 노출총량")
        ax_tex.set_ylabel("총 쎄타 노출량", color="#aaaaaa", fontsize=10)
        ax_tex.grid(False)

        ax_the.set_title("■ 쎄타 추세 및 쎄타 총 노출도", fontsize=18, fontweight="semibold", pad=12, loc="left", color="#ffffff")
        ax_the.set_xticks(y_indexes)
        ax_the.set_xticklabels(y_labels, color="#ffffff", fontsize=14, rotation=45)
        ax_the.grid(True, color="#2d2d3a", linewidth=0.5, linestyle=":")
        
        lines_1, labels_1 = ax_the.get_legend_handles_labels()
        lines_2, labels_2 = ax_tex.get_legend_handles_labels()
        ax_the.legend(lines_1 + lines_2, labels_1 + labels_2, loc="best", frameon=False, fontsize=13, ncol=2)
        for spine in ax_the.spines.values(): spine.set_visible(False)
        for spine in ax_tex.spines.values(): spine.set_visible(False)

        # ------------------------------------------
        # ⑥ 고급 분석 요약 리포트 패널
        # ------------------------------------------
        ax_report.set_facecolor("#1d1d29")
        ax_report.axis('off') 
        
        report_text = (
            f"■ 입체 분석 리포트\n\n"
            f"  1. 딜러 감마 트랩(Gamma Trap) 고정 레벨 : [ 행사가 {gamma_trap_strike:,.0f} 원 ]\n"
            f"     > 미결제약정이 밀집되어 지수의 추가 변동성을 강하게 압축하고 자석처럼 끌어당기는 핵심 마디\n\n"
            f"  2. GEX 기반 실질적 상하방 추정 위험 밴드 : [ {lower_band:,.0f} 원 ~ {upper_band:,.0f} 원 ]\n"
            f"     > 단순 경계값이 아닌 시장메이커의 헤지 물량이 급격히 교차하는 유력 동적 지지/저항 범위\n\n"
            f"  3. 통합 위험 최선호 스팟 (DEX+GEX+Vanna 절대치 누적 Top 5)\n"
            f"     > [ {top5_str} ] 레벨 진입 시 감마 스퀴즈나 강한 브레이크가 걸릴 확률이 높음.\n\n"
            f"■ 종합 그릭스 기반 옵션 포지셔닝 가이드라인\n\n"
            f"   * [Buy Side (옵션 매수)]: 현재가({S:,.0f}) 부근은 쎄타(Theta) 감쇄 위험이 가장 큽니다. 따라서 데이터상\n"
            f"                      주요 GEX 매물대 벽인 추정 위험 밴드 경계선({lower_band:,.0f} 원 / {upper_band:,.0f} 원)을\n"
            f"                      강하게 돌파하거나, Gamma Flip 변곡점을 지날 때 '외가격(OTM) 모멘텀 계약'을 타겟팅하는 것이\n"
            f"                      시간 가치 손실을 방어하며 딜러의 추격 헤지(감마 스퀴즈) 혜택을 극대화하는 방향입니다.\n\n"
            f"   * [Sell Side (옵션 매도)]: 쎄타 노출도(TEX 면적)가 피크를 찍는 구역과 가로 GEX/Vanna NET 벽이 단단하게 일치하는\n"
            f"                      상하방 외가격 위험 밴드 외부({lower_band:,.0f} 이하 / {upper_band:,.0f} 이상) 지점을 주요 프리미엄 수취 타겟으로 설정합니다."
        )
        
        ax_report.text(0.01, 0.5, report_text, color="#ffffff", fontsize=17, fontweight="medium",
                       va="center", ha="left", linespacing=1.6,
                       bbox=dict(facecolor='#1d1d29', alpha=1.0, edgecolor='#FFC000', boxstyle="round,pad=1.2", linewidth=1.5))

        # ==========================================
        # 결과 이미지 저장 마감 및 AI 분석 스팟 유지
        # ==========================================
        clean_prod = str(prod).strip().replace("\r", "").replace("\n", "")
        clean_date = str(today_date_str).strip().replace("\r", "").replace("\n", "")

        output_filename = f"option_greeks_dashboard_{clean_prod}_{clean_date}.png"
        output_filename = re.sub(r'[\\/*?:"<>|]', "", output_filename)
        output_path = os.path.abspath(os.path.join(output_dir, output_filename))

        plt.savefig(output_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close()

        # ==========================================
        # [추가] 결과 이미지 저장 직후 Gemini API 분석 연동
        # ==========================================
        # 1. 환경변수나 코드 내에 API 키가 설정되어 있는지 확인합니다.
        api_key = os.environ.get("GEMINI_API_KEY")
        
        if api_key and api_key != "":
            try:
                from google import genai
                from google.genai import types
                import PIL.Image

                print(f"   -> [Gemini API] 대시보드 AI 이미지 분석 시작... ({clean_prod})")
                
                # Client 초기화
                client = genai.Client(api_key=api_key)
                
                # 저장된 대시보드 이미지 불러오기
                raw_image = PIL.Image.open(output_path)
                
                # 이미지 분석을 위한 프롬프트 고도화 (Buy-Side/Sell-Side 관점 명시)
                prompt = f"""
                당신은 파생상품 및 옵션 포지션 분석 전문 퀀트(Quant) 애널리스트입니다.
                첨부된 코스피200 옵션 입체 그릭스 대시보드 이미지({output_filename})를 정밀하게 분석하여 마켓 브리핑 리포트를 작성해 주세요.

                리포트에는 다음 내용이 반드시 깊이 있게 포함되어야 합니다:
                1. DEX(델타 익스포져) 분포를 바탕으로 한 현재 시장 참여자들의 상하방 베팅 강도 및 주요 매물대 분석
                2. GEX(감마 익스포져) 및 Vanna NET 가로막대 벽을 기반으로 한 지수의 강력한 지지/저항 예상 마디선 타겟팅
                3. Theta Smile(순수 세타) 및 TEX Curve(총 노출량) 면적을 고려했을 때, 만기 시점까지 프리미엄 감소(Time Decay)가 가장 가파르게 작용할 구간 평가
                4. 최종 결론 및 실전 트레이딩 가이드라인:
                   - 옵션 매수자(Buy Side)가 감마 스퀴즈 및 모멘텀 폭발을 노릴 수 있는 위험 밴드 돌파 시점 포지셔닝 전략
                   - 옵션 매도자(Sell Side)가 안전하게 프리미엄을 수취할 수 있는 최적의 상하방 외가격(OTM) 경계선 제시

                전문적이고 직관적인 한국어 금융 리포트 형식으로 구성해 주세요.
                """
                
                # 멀티모달 모델(gemini-3.5-flash) 호출
                response = client.models.generate_content(
                    model='gemini-3.5-flash',
                    contents=[raw_image, prompt]
                )
                
                # 분석 결과를 텍스트 파일로 자동 저장
                report_filename = f"option_analysis_report_{clean_prod}_{clean_date}.txt"
                report_path = os.path.join(output_dir, report_filename)
                
                with open(report_path, "w", encoding="utf-8") as rf:
                    rf.write(response.text)
                    
                print(f"   -> [Gemini API] AI 금융 분석 리포트 생성 완료: {report_path}")
                print("-" * 60)
                print(response.text[:500] + "\n... (이하 생략) ...")
                print("-" * 60)

            except Exception as ai_err:
                print(f"   ⚠ [Gemini API 오류] AI 리포트 생성 중 예외 발생: {ai_err}")
        else:
            print("   ℹ [Gemini API 안내] GEMINI_API_KEY가 설정되지 않아 AI 이미지 분석을 건너뜁니다.")

        print(f"   -> [{prod.upper()} 분석 완료] 이미지 저장 완료: {output_path}")

    except Exception as e:
        import traceback
        print(f"   ⚠ [가공 오류] {prod} 가공 실패 원인: {e}")
        traceback.print_exc()
    finally:
        plt.close('all')