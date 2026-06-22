# KOSPI & 개별 주식 옵션 입체 분석 및 AI 브리핑 시스템
(KOSPI Option Visualization & Briefing System)

본 프로젝트는 한국거래소(KRX)의 지수 및 개별 주식 옵션 데이터를 전처리하여 마켓 프로파일을 시각화하고, 블랙-숄즈(Black-Scholes) 모형 기반의 입체 그릭스(Greeks - Delta, Gamma, Vanna, Theta) 노출도를 산출하며, Gemini 3.5 Flash API를 활용하여 퀀트 관점의 종합 금융 분석 보고서를 자동으로 생성 및 발행하는 원스톱 파이프라인입니다.

---

## 🛠️ 기술 스택 (Technology Stack)

*   **언어 및 실행 인프라**: `Python 3.14+` 및 `uv` (가장 빠른 파이썬 가상환경 및 패키지 관리자)
*   **데이터 핸들링 및 수학 연산**: `pandas`, `numpy`, `scipy` (블랙-숄즈 확률 밀도 및 누적 분포 함수 연산)
*   **시각화 (Visualization)**: 
    *   `matplotlib` (다크 테마 기반 고해상도 대시보드 작도)
    *   `koreanize-matplotlib` (윈도우/리눅스 환경의 한글 폰트 깨짐 및 사각형 출력을 자동 방어하는 내장 한글 폰트 패키지)
*   **외부 경제 데이터 API**: 한국은행 ECOS API (`817Y002` 일별 시장금리 테이블 연동)
*   **대형 언어 모델 (LLM)**: `google-genai` SDK (멀티모달 이미지 판독을 위한 `gemini-3.5-flash` 연동)
*   **윈도우 터미널 인코딩 교정**: `io.TextIOWrapper` 표준 입출력 오버라이드 기법 (cp949 크래시 원천 차단)

---

## 📂 파일 구성 및 역할 (Project Architecture)

이 프로젝트는 총 5개의 분석 코어 파일과 환경 설정 파일로 구성되어 있습니다.

### 1. `vol_prcs.py` (투자 주체별 실적 분석)
*   **기능**: 일별로 축적되는 투자자(기관합계+기타법인 ➡️ 기관, 개인, 외인)의 콜/풋 옵션 거래량 및 거래대금을 취합하여 역사적 5거래일 순거래 매집 동향 차트(4단 구성)를 생성합니다.
*   **산출물**: `picture/{날짜}/` 폴더 하위에 주체별 거래 동향 대시보드 이미지 생성.

### 2. `1_option.py` & `1_option_stock.py` (지수 및 주식 옵션 프로파일링)
*   **기능**: 사용자가 입력한 행사가 조회 범위를 바탕으로, 당일 및 전일 옵션 데이터를 대조하여 미결제약정 잔고 현황, 변동성 스마일(Volatility Smile), 전일 대비 미결제약정 순증감량을 3단 대시보드로 시각화합니다.
*   **산출물**: `picture/option_analysis/option_profile_{상품}_{날짜}.png`

### 3. `2_option.py` & `2_option_stock.py` (입체 그릭스 시뮬레이션 및 AI 리포트)
*   **기능**: 블랙-숄즈 모형을 통해 옵션 그릭스를 연산한 뒤, 미결제약정을 가중치로 곱해 시장의 실질 델타 노출도(DEX), 감마 노출도(GEX), 바나 노출도(VEX), 세타 노출도(TEX)를 입체 매물대와 시계열 곡선으로 도출합니다.
*   **Gemini AI 연동**: 생성 완료된 대시보드 이미지를 Gemini 3.5 Flash 모델에 공급하여, 딜러들의 헤징 변곡점인 감마 트랩(Gamma Trap)과 상하방 위험 밴드를 해석한 공식 퀀트 마켓 브리핑 리포트 텍스트(.txt)를 자동 생성합니다.
*   **산출물**: 
    *   `picture/option_greeks/option_greeks_dashboard_{상품}_{날짜}.png`
    *   `picture/option_greeks/option_analysis_report_{상품}_{날짜}.txt`

### 4. `.env` (보안 및 API 설정 키)
*   프로젝트 루트에 생성하며, 소스 코드와 민감한 키값을 분리하여 관리합니다.
```env
ECOS_API_KEY=your_ecos_api_key      # 한국은행 ECOS API 인증키
GEMINI_API_KEY=your_gemini_api_key  # 구글 AI Gemini API 키
```

---

## ⚡ 주요 개선 및 고도화 내역 (Feature Enhancements)

1.  **한국은행 금리 실시간 수집 자동화**:
    *   매번 사용자가 입력해야 했던 무위험 이자율 `r`을, 한국은행 ECOS API를 통해 가장 최근에 고시된 실물 **국고채 3년물 금리**를 자동으로 역산하여 대화형 프롬프트의 기본값으로 자동 제안 및 매핑합니다.
2.  **한글 깨짐 현상 (두부 현상) 원천 차단**:
    *   시스템에 특정 한글 폰트가 설치되어 있지 않아 Matplotlib 차트 내부의 한글이 깨지던 결함을 `koreanize-matplotlib` 연동을 통해 시스템 독립적으로 영구 해결했습니다.
3.  **Windows 터미널 인코딩 강건성 확보**:
    *   윈도우 PowerShell 및 CMD의 `cp949` 터미널 환경에서 이모지 출력 시 강제 종료되던 `UnicodeEncodeError` 현상을 sys.stdout/stderr 표준 인코딩 가로채기(Wrapper) 코드를 삽입하여 완전히 차단했습니다.
4.  **주식 옵션 NameError 버그 디버깅**:
    *   `2_option_stock.py`에서 지정한 날짜의 CSV 파일이 존재하지 않아 비정상 종료 시, 변수 스코프 문제로 나던 NameError를 해결하여 안전한 예외 처리가 작동하도록 정비하였습니다.

---

## 🚀 실행 방법 (How to Run)

### 1. 가상환경 구축 및 의존성 설치
`uv`를 활용하여 초고속으로 환경을 빌드하고 의존성을 구성합니다.
```bash
# 가상환경 생성
uv venv

# 패키지 일괄 설치 (matplotlib 한글 폰트 및 최신 Python 3.14 distutils 우회 호환을 위한 setuptools 포함)
uv pip install numpy pandas matplotlib scipy google-genai pillow koreanize-matplotlib setuptools
```

### 2. 데이터 적재 규칙
한국거래소(KRX) Data Marketplace 등에서 내려받은 일별 시세 CSV 데이터를 아래 파일명 규칙에 맞춰 [daily_op](file:///./daily_op) 폴더에 넣어줍니다.
*   **지수 옵션**: `200_YYYYMMDD.csv`, `w_YYYYMMDD.csv`, `w2_YYYYMMDD.csv`, `m_YYYYMMDD.csv`
*   **주식 옵션**: `종목명_YYYYMMDD.csv` (예: `삼성전자_20260619.csv` 또는 `sec_20260619.csv`)

### 3. 분석기 가동
```bash
# 지수 옵션 입체 그릭스 및 Gemini AI 금융 분석 실행
.venv\Scripts\python 2_option.py

# 주식 옵션 입체 그릭스 및 Gemini AI 금융 분석 실행
.venv\Scripts\python 2_option_stock.py
```
실행 후 프롬프트에 기초자산 지수(또는 개별 주가)를 입력하고 무위험 이자율 기본 제안값(한국은행 연동 값)을 확인한 뒤 **엔터(Enter)**만 입력하면 분석 및 AI 보고서 작성이 자동으로 마감됩니다.
