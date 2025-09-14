# 🌳 SENA: 그늘 우선 경로 추천 시스템
**대구 빅데이터 활용 경진대회 2025 본선 진출작**  

본 프로젝트는 **건물 통합정보**, **가로수 데이터**, 그리고 **실시간 태양 위치 데이터**를 분석하여 **시간대별 그림자 영역**을 계산합니다.  
이 결과를 **다익스트라 알고리즘**에 반영해, 사용자 지정 가중치에 따른 **‘그늘 우선 경로 추천’** 서비스를 제공합니다.  

---

## 🚀 주요 기능
- 건물/가로수 및 태양 위치 기반 **시간대별 그림자 영역 계산**
- 사용자 지정 **거리 vs 그늘 가중치** 반영 경로 탐색
- **Streamlit 웹 애플리케이션** 제공
- **Ngrok HTTPS 서버 연동**으로 외부 접속 지원

---

## 📦 설치 및 실행 방법

### 1. 가상환경 생성 및 활성화
```bash
python -m venv venv
venv\Scripts\activate   # Windows
```

### 2. 라이브러리 설치
```bash
pip install -r requirements.txt
```

### 3. Streamlit 앱 실행
```bash
streamlit run streamlit_app/app.py
```

### 4. HTTPS 서버 실행 (Ngrok)
```bash
python ./streamlit_app/run_ngrok.py
```

---

## 📂 프로젝트 구조
```
proj. SENA/
│
├── streamlit_app/
│   ├── app.py          # 메인 Streamlit 앱
│   ├── run_ngrok.py    # Ngrok 실행 스크립트
│   └── ...
├── requirements.txt
└── README.md
```

---

## 🔧 개발 환경
- Python 3.10.0
- Streamlit 1.49.1
- 주요 라이브러리:
  - folium
  - streamlit-folium
  - geopy
  - pysolar
  - pyngrok
  - networkx
  - pandas / numpy / matplotlib / shapely

---

## 👥 팀 정보
- **팀명**: SENA
- **구성원**: 오제석, 장지원, 안지호
