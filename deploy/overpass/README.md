# 자체 Overpass 띄우기 (상용/안정 운영)

무료 공개 Overpass는 불안정 + 상용 금지입니다. 직접 1대 띄우면 한국 전역 도로/건물을
무제한·안정적으로 쓸 수 있고, 백엔드는 환경변수만 바꾸면 됩니다.

## 0. 준비물
- 서버 1대 (VPS/클라우드). 권장: **vCPU 2, RAM 4GB+, 디스크 20GB+**
  - 예) AWS Lightsail / DigitalOcean / Vultr / Oracle Cloud Free 등 월 $5~20대
- 도커 설치된 Linux (Ubuntu 22.04 권장)

## 1. 띄우기
```bash
# 도커 설치 (Ubuntu 예시)
curl -fsSL https://get.docker.com | sh

# 이 폴더(deploy/overpass)를 서버로 복사한 뒤
docker compose up -d

# 최초 1회 한국 OSM 다운로드+인덱싱: 수십 분~1시간 (사양에 따라)
docker compose logs -f overpass     # "Overpass API ready" 비슷한 로그가 뜨면 완료
```

## 2. 동작 확인
```bash
# 같은 서버에서
curl "http://localhost:12345/api/interpreter?data=[out:json][timeout:25];way[\"highway\"](35.886,128.605,35.894,128.616);out 1;"
# 방화벽에서 12345 포트 열기 (또는 nginx로 443 프록시 + 도메인 권장)
```

## 3. 백엔드(ShadoWay API)에 연결
Render(또는 운영 호스트) 환경변수에 추가:
```
OVERPASS_URLS = http://<서버_공인IP>:12345/api/interpreter
OVERPASS_TIMEOUT = 60
```
- 여러 대면 콤마로: `OVERPASS_URLS=https://op1.example.com/api/interpreter,https://op2.example.com/api/interpreter`
- 저장 후 백엔드 재배포 → 이제 **전국 어디든** 이 Overpass로 안정 조회.

## 4. 운영 팁
- **HTTPS**: 프론트가 https면 백엔드→Overpass는 서버-서버라 http 허용. 단, 가능하면 nginx+Let's Encrypt로 https 프록시 + 도메인.
- **업데이트**: `OVERPASS_DIFF_URL` 설정으로 일 단위 자동 갱신.
- **메모리 절약**: 히스토리 불필요 시 `OVERPASS_META: "no"`.
- **지역 한정**: 한국 전역 대신 특정 시/도만 필요하면 더 작은 추출본(BBBike 커스텀 bbox)으로 교체해 가볍게.
