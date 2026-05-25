# 🗺️ 쯔양맵

쯔양 유튜브 채널이 다녀간 모든 한국 맛집을 모은 지도 웹앱.
GPT-4o-mini와 Kakao Maps API로 영상에서 매장 정보를 자동 추출하고 매일 새 영상을 자동 추가합니다.

🔗 **Live**: [tzuyangmap on Vercel](https://github.com/hyuniiiv/tzuyangmap)

---

## ✨ 주요 기능

- **957개 검증된 맛집** 핀 지도 표시 (Kakao Maps)
- **검색 / 지역·카테고리 필터 / 정렬** (최신순·근처순·이름순·지역순)
- **즐겨찾기 / 방문 체크** (localStorage)
- **공유 링크** (특정 매장 URL `?r=name|address`)
- **모바일 PWA** (홈화면 추가, 오프라인 캐시)
- **다중 매장 영상 지원** (망원동 3대빵집 → 3개 매장)
- **매일 자정 자동 업데이트** (GitHub Actions)

## 🎨 디자인

Apple 라이트 디자인 시스템 적용:
- 파치먼트(`#f5f5f7`) 배경 + Pretendard Variable 폰트
- Action Blue(`#0066cc`) 단일 액센트
- 18px 라운드 카드 + 헤어라인(`#e0e0e0`)
- 풀-필 CTA, 슬림 글로벌 내브

---

## 🏗️ 아키텍처

```
사용자 → Vercel (정적 호스팅)
              ↓
        public/index.html
              ↓
        Kakao Maps SDK
              ↓
        restaurants_geo.json (957개)
              ↑
GitHub Actions cron (매일 KST 00:17)
              ↓
        scripts/auto_update.py
              ↓
 ┌──── 자막 수집 ────┐
 │ youtube-transcript-api │  ① 우선
 │ yt-dlp                 │  ② 폴백
 │ Whisper STT            │  ③ 자막 없을 때
 └────────────────┘
              ↓
 ┌──── 신호 통합 ────┐
 │ 자막 / 댓글(100개) │
 │ 영상 설명 / 웹검색  │
 │ 썸네일 (Vision)    │
 └────────────────┘
              ↓
        GPT-4o-mini (JSON Schema)
              ↓
        Kakao 검증 (이름 재검색 + 좌표 매칭)
              ↓
        restaurants_geo.json 자동 push
```

## 🔍 매장 추출 파이프라인

LLM이 다음 신호를 종합 분석해 매장(들) 추출:

| 신호 | 도구 | 역할 |
|---|---|---|
| 영상 자막 | youtube-transcript-api → yt-dlp → Whisper | 사장님/쯔양 발언, 위치 단서 |
| 댓글 (상위 100) | youtube-comment-downloader | 팬들의 지점/주소 언급 |
| 영상 설명 | yt-dlp `--print description` | 협찬/주소 명시 |
| 웹 검색 | Naver search | 블로그/뉴스 본문 |
| 썸네일 | GPT-4o-mini Vision | 간판/로고/메뉴판 |

**검증 단계**:
1. LLM이 매장명/주소 추출 (JSON Schema 강제)
2. Kakao 매장 재검색 (이름 + 지역, suffix 제거 폴백)
3. 좌표 100m 내 매장 cross-verify
4. 신뢰도 격자 (sim≥0.85 / 0.5+30km / 0.4+10km / 0.3+5km)
5. 일반명사·메뉴명·협찬 영상 자동 거부

### 댓글 지역 폴백 (특수 케이스)
영상이 매장명 의도적으로 숨겨도 댓글에서 지역 단서 추출 후 Kakao 검색:
- *매니저가 5년간 숨겨온 맛집* → 댓글 "노원구 쪽에 삼겹살" → **웅가네 개성김치녹차삼겹살**

---

## 🛠️ 기술 스택

**Frontend**
- 순수 HTML/CSS/JS (프레임워크 없음)
- Kakao Maps JavaScript SDK + MarkerClusterer
- Pretendard Variable 폰트

**Backend (자동 추출)**
- Python 3.11
- `yt-dlp` — 영상 메타데이터
- `youtube-transcript-api` — 자막 (봇 차단 우회)
- `youtube-comment-downloader` — 댓글
- `faster-whisper` — 자막 없는 영상 STT
- `OpenAI GPT-4o-mini` — Vision LLM
- `Kakao Local Search API` — 매장 검증 + 지오코딩

**인프라**
- Vercel (정적 호스팅)
- GitHub Actions (cron 자동 업데이트)
- GitHub Secrets (API 키 관리)

---

## 📂 디렉토리 구조

```
tzuyangmap/
├── public/
│   ├── index.html          # 메인 웹앱
│   ├── manifest.json       # PWA 매니페스트
│   ├── sw.js               # 서비스 워커
│   ├── icon.svg            # PWA 아이콘
│   └── data/
│       └── restaurants_geo.json   # 데이터 (957개)
├── scripts/
│   ├── auto_update.py             # 매일 자동 추출
│   ├── audit_data_quality.py      # 데이터 품질 감사
│   ├── backfill_kakao_details.py  # 메타데이터 백필
│   ├── backfill_upload_dates.py   # 영상 게시일 백필
│   └── test_*.py                  # 테스트 스크립트
├── .github/workflows/
│   ├── update.yml          # 매일 자동 업데이트 (KST 00:17)
│   ├── test_video.yml      # 단일 영상 추출 테스트
│   ├── test_recent.yml     # 최근 N개 영상 테스트
│   └── rebuild_all.yml     # 전체 재처리
└── vercel.json
```

---

## ⚙️ 자동 업데이트

매일 KST 00:17에 GitHub Actions 실행 (`.github/workflows/update.yml`):

1. `yt-dlp --flat-playlist` 로 채널 최신 2개 영상 확인
2. 기존 데이터에 없는 신규 영상 식별
3. 각 영상에 대해 `process_new_video()` 실행
4. 추출된 매장 entries 추가 후 git commit/push
5. Vercel 자동 배포

**비용 (월)**:
- LLM (GPT-4o-mini): ~$0.04
- 일 2영상, 영상당 ~$0.0006

**거부 정책**:
- 해외 영상 (라스베가스, 발리, 도쿄 등)
- 협찬/유료광고 영상 (description 키워드 감지)
- 식당 정보 부재 영상 (LLM low confidence)

---

## 🚀 로컬 개발

```bash
# 의존성 설치
pip install yt-dlp youtube-comment-downloader youtube-transcript-api faster-whisper

# .env 파일 생성 (프로젝트 루트 또는 부모)
KAKAO_REST_API_KEY=your_kakao_key
KAKAO_JAVASCRIPT_KEY=your_kakao_js_key
OPEN_AI_API_KEY=your_openai_key

# 단일 영상 테스트
python scripts/test_one_video.py <VIDEO_ID> "<TITLE>"

# 자동 업데이트 수동 실행
python scripts/auto_update.py

# 정적 서버 (프론트엔드 미리보기)
cd public && python -m http.server 8000
```

---

## 📊 데이터

- **총 957개 매장** (2026-05-25 기준)
- 채널: 쯔양 (`@tzuyang6145`)
- 처리된 unique 영상: ~800개 / 채널 전체 988개
- 미처리: 해외(91) / 비식당(8) / 정보부재(~30) — 모두 정당 거부

**필드**:
```json
{
  "name": "동대문엽기떡볶이 본점홀매장",
  "address": "서울 중구 다산로 257",
  "category": "분식",
  "region": "서울",
  "video_id": "xFGP21Xmn2w",
  "video_title": "엽떡 먹고싶어지는 영상",
  "upload_date": "2025-09-07",
  "lat": 37.566116,
  "lng": 127.015581,
  "phone": "02-2232-0045",
  "place_url": "http://place.map.kakao.com/1120147358",
  "kakao_category": "음식점 > 한식 > 육류,고기 > 삼겹살",
  "source": "auto_kakao"
}
```

---

## 🤝 기여

이슈/PR 환영. 자동 추출이 잘못 잡은 매장 발견하시면 issue로 알려주세요.

## 📝 라이선스

MIT (선언만, 데이터는 쯔양 채널 콘텐츠 기반)
