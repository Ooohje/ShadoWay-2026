# ShadoWay 상용화 가이드

현재 구조는 그대로 두고(지역을 온디맨드로 받아 그늘길 계산), **데이터 소스와 호스팅만**
안정적인 것으로 바꾸면 됩니다.

## 아키텍처
```
[브라우저 PWA]  ──HTTPS──▶  [ShadoWay API (FastAPI)]  ──▶  [도로/건물 데이터 소스]
 GitHub Pages                상시가동 인스턴스              ① 자체 Overpass (도로/건물)
                              (Render 유료 / VPS)           ② VWorld (건물 높이, 선택)
                                                            + 지역 캐시(디스크/DB)
```

## 바꿔야 할 3가지 (무료→상용)

### 1) 도로 데이터: 자체 Overpass  ⭐가장 중요
- 무료 공개 Overpass는 불안정 + **상용 금지**.
- 해결: `deploy/overpass/` 의 docker-compose 로 자체 Overpass 1대 운영 → 백엔드 환경변수만 설정.
  ```
  OVERPASS_URLS=https://overpass.yourdomain.com/api/interpreter
  OVERPASS_TIMEOUT=60
  ```
- 코드는 이미 env 를 읽도록 되어 있어 **수정 불필요**. (poc/osm_loader.py)

### 2) 건물 높이: VWorld 상용 협약 또는 대체 데이터
- VWorld 무료키는 도메인/IP 제한 + 클라우드에서 종종 막힘.
- 상용: VWorld 정식 이용 신청, 또는 건물 높이 데이터셋 확보.
- 없으면 OSM `building:levels`/기본값으로 동작(정확도 ↓).

### 3) 호스팅: 상시 가동 인스턴스
- 무료 Render는 콜드스타트(50초)+약한 CPU → 상용 부적합.
- Render 유료(Starter+) 또는 VPS. CPU/RAM 여유 있으면 그늘 계산도 빨라짐.

## 성능/비용 최적화 (코드에 이미 반영)
- **지역 캐시(메모리)**: 같은 bbox 재요청은 즉시.
- **영속 캐시(디스크)**: 환경변수 `SHADOWAY_CACHE_DIR=/data/cache` 설정 시 재시작에도 유지.
  (영속 디스크가 있는 호스트에서. Render는 Persistent Disk 옵션 필요)
- **STRtree 공간 인덱스**로 간선별 그늘 계산 최적화.
- 더 큰 규모: 그늘을 시간대 버킷별로 미리 계산해 DB 캐시 권장.

## 환경변수 요약
| 변수 | 용도 | 예시 |
|---|---|---|
| `OVERPASS_URLS` | 도로/건물 Overpass 엔드포인트(콤마구분) | `https://op.you.com/api/interpreter` |
| `OVERPASS_TIMEOUT` | Overpass 읽기 타임아웃(초) | `60` |
| `VWORLD_WFS_KEY` | VWorld 건물 높이 키 | `XXXX-...` |
| `SHADOWAY_CACHE_DIR` | 지역 영속 캐시 경로 | `/data/cache` |
| `ALLOW_ORIGINS` | CORS 허용 출처 | `https://yourapp.com` |

## 체크리스트 (당신이 할 일)
- [ ] VPS 1대 준비 (RAM 4GB+, 디스크 20GB+)
- [ ] `deploy/overpass/` 로 자체 Overpass 기동 + 동작 확인
- [ ] 백엔드에 `OVERPASS_URLS`, `OVERPASS_TIMEOUT` 설정 후 재배포
- [ ] (선택) 영속 디스크 + `SHADOWAY_CACHE_DIR`
- [ ] (선택) VWorld 상용 신청, 유료 호스팅 전환
- [ ] 비-경북대 지역 경로가 안정적으로 나오는지 검증
