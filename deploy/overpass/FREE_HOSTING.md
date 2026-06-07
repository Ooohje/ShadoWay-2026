# 무료로 24시간 Overpass 띄우기 (Oracle Cloud Always Free)

당신 컴퓨터 없이, **평생 무료** 클라우드 VM에 Overpass를 띄우는 방법.
(Oracle Cloud "Always Free"는 신용카드 본인확인만 하고 과금 안 됨. VM은 24시간 클라우드에서 가동)

## 왜 Oracle Always Free?
- 대부분 무료 티어(AWS/GCP)는 RAM 1GB라 한국 Overpass 빌드가 안 됨.
- Oracle Always Free의 **Ampere A1 (ARM)** 은 최대 **4 OCPU / 24GB RAM / 200GB 디스크** 무료 → 충분.

## 단계
### 1) 무료 VM 생성
1. https://www.oracle.com/cloud/free/ 가입 (카드 본인확인, 과금X)
2. Compute → Instances → Create
   - Image: **Ubuntu 22.04**
   - Shape: **VM.Standard.A1.Flex** (Ampere) — OCPU 2~4, RAM 12~24GB
   - SSH 키 등록(다운로드)
3. 생성 후 **Public IP** 기록
4. 네트워킹 → VCN Security List 에 **인그레스 규칙** 추가: TCP **12345** (또는 80/443) 0.0.0.0/0

### 2) 서버에서 Overpass 기동 (ARM)
```bash
ssh ubuntu@<PUBLIC_IP>
curl -fsSL https://get.docker.com | sh
sudo mkdir -p /opt/overpass && cd /opt/overpass

# 한국 전역 대신 '대구·경북'만 쓰면 더 가볍고 빠름(원하면 URL만 교체)
sudo docker run -d --name overpass --restart unless-stopped \
  -p 12345:80 \
  -e OVERPASS_META=no \
  -e OVERPASS_MODE=init \
  -e OVERPASS_PLANET_URL=https://download.geofabrik.de/asia/south-korea-latest.osm.pbf \
  -e OVERPASS_DIFF_URL=https://download.geofabrik.de/asia/south-korea-updates/ \
  -e OVERPASS_RULES_LOAD=10 \
  -v /opt/overpass/db:/db \
  wiktorn/overpass-api:latest

sudo docker logs -f overpass     # 최초 빌드 수십 분. ready 뜨면 완료
```
> ARM에서 이미지가 안 뜨면: `--platform linux/amd64` 추가하거나, 더 작은 지역 추출본 사용.

### 3) 동작 확인 + 우분투 방화벽
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 12345 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true
curl "http://localhost:12345/api/interpreter?data=[out:json][timeout:25];way[\"highway\"](35.86,128.59,35.90,128.62);out 1;"
```

### 4) 백엔드(Render) 환경변수 연결
Render 대시보드 → ShadoWay API → Environment:
```
OVERPASS_URLS = http://<PUBLIC_IP>:12345/api/interpreter
OVERPASS_TIMEOUT = 60
```
저장 → 재배포. 끝. 이제 전국 어디든 이 무료 VM의 Overpass로 안정 동작.

> 보안 권장: 12345 직노출 대신 nginx + 도메인 + Let's Encrypt(https)로 감싸기.
> 그러면 `OVERPASS_URLS=https://overpass.yourdomain.com/api/interpreter`.
