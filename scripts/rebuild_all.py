"""
기존 restaurants_geo.json 전체를 새 LLM 파이프라인으로 재처리.

- 우선순위: 신뢰도 낮은 항목부터 (D → C → B → A → S)
- state 파일로 진행 상태 저장 → 재실행 시 중단된 곳부터 계속
- 같은 video_id가 여러 엔트리인 경우 LLM 캐시로 중복 호출 방지
- 새 결과가 메타데이터/유사도 모두 충족할 때만 교체

사용법:
  python scripts/rebuild_all.py --limit 200            # 200개만 처리하고 종료
  python scripts/rebuild_all.py --force                # 처리한 항목도 재처리
  python scripts/rebuild_all.py --grades B,C,D         # 특정 등급만
  python scripts/rebuild_all.py --reset                # state 초기화
"""
import json, sys, time, argparse, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import auto_update as au
from audit_data_quality import grade as audit_grade

ROOT = Path(__file__).parent.parent
GEO_FILE      = ROOT / "public" / "data" / "restaurants_geo.json"
STATE_FILE    = ROOT / "scripts" / ".rebuild_state.json"
FAIL_LOG_FILE = ROOT / "scripts" / ".rebuild_failures.json"
BAK_FILE      = ROOT / "public" / "data" / "restaurants_geo.json.bak2"

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=300, help="이 실행 최대 처리 수")
ap.add_argument("--force", action="store_true", help="처리한 항목도 재처리")
ap.add_argument("--grades", type=str, default="B,C,D", help="처리할 등급 (콤마)")
ap.add_argument("--reset", action="store_true", help="state 초기화")
ap.add_argument("--dry-run", action="store_true", help="저장 안 함")
ap.add_argument("--failures-only", action="store_true",
                help="이전 실패 목록(.rebuild_failures.json)만 재처리")
args = ap.parse_args()

# state 관리
if args.reset and STATE_FILE.exists():
    STATE_FILE.unlink()
    print("state 초기화 완료")

state = {}
if STATE_FILE.exists():
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
processed_ids = set(state.get("processed_video_ids", []))

# 실패 로그 (재처리용)
failures = []
if FAIL_LOG_FILE.exists():
    try: failures = json.loads(FAIL_LOG_FILE.read_text(encoding="utf-8"))
    except: failures = []

# 데이터 로드 + 백업
data = json.loads(GEO_FILE.read_text(encoding="utf-8"))
if not BAK_FILE.exists():
    BAK_FILE.write_text(GEO_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"백업 생성: {BAK_FILE.name}")

# 등급 매기기
target_grades = set(g.strip().upper() for g in args.grades.split(","))
print(f"전체: {len(data)}개")
print(f"대상 등급: {target_grades}")
print(f"이미 처리됨: {len(processed_ids)}개\n")

# 대상 엔트리 선별 (우선순위: D → C → B → A → S)
GRADE_PRIORITY = {"D": 0, "C": 1, "B": 2, "A": 3, "S": 4}
candidates = []

# --failures-only: 실패 목록의 video_id만 대상
failure_vids = set()
if args.failures_only:
    if not FAIL_LOG_FILE.exists():
        print("실패 로그 파일 없음 — 종료")
        sys.exit(0)
    failure_list = json.loads(FAIL_LOG_FILE.read_text(encoding="utf-8"))
    failure_vids = {f["video_id"] for f in failure_list}
    print(f"실패 재처리 모드: {len(failure_vids)}개 video_id 대상")
    # state 초기화 (실패만 다시 처리하기 위해)
    processed_ids = processed_ids - failure_vids

for i, r in enumerate(data):
    g = audit_grade(r)
    if g not in target_grades: continue
    vid = r.get("video_id")
    if not vid: continue
    if args.failures_only and vid not in failure_vids: continue
    if vid in processed_ids and not args.force: continue
    candidates.append((GRADE_PRIORITY.get(g, 5), i, r, g))

candidates.sort(key=lambda x: x[0])  # 낮은 등급 먼저

# --failures-only일 때 실패 목록 초기화 (다시 채울 거니까)
if args.failures_only:
    failures = []
print(f"처리 대상: {len(candidates)}개 (이번 실행: 최대 {args.limit}개)\n")

if not candidates:
    print("처리할 항목 없음 — 완료")
    sys.exit(0)

# LLM 결과 캐시 (같은 video_id 중복 호출 방지)
llm_cache = {}

updated, kept, failed = 0, 0, 0
t_start = time.time()

for idx, (prio, data_i, r, g) in enumerate(candidates[:args.limit]):
    vid = r["video_id"]
    title = r.get("video_title", "")
    print(f"[{idx+1}/{min(args.limit, len(candidates))}] [{g}] {title[:50]}")
    print(f"  현재: {r.get('name','')} @ {(r.get('address','') or '')[:35]}")

    # 같은 영상 캐시 활용
    if vid in llm_cache:
        new_entry = llm_cache[vid]
        print(f"  (캐시 재사용)")
    else:
        video = {
            "id": vid, "title": title,
            "url": r.get("video_url", f"https://www.youtube.com/watch?v={vid}"),
            "thumbnail": r.get("thumbnail", f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"),
            "channel": r.get("channel", "tzuyang"),
        }
        try:
            new_entry = au.process_new_video(video)
        except Exception as e:
            print(f"  ✗ 예외: {type(e).__name__}: {str(e)[:80]}")
            new_entry = None
        llm_cache[vid] = new_entry

    processed_ids.add(vid)

    if not new_entry:
        failed += 1
        failures.append({
            "video_id": vid,
            "title": title[:80],
            "old_name": r.get("name", ""),
            "old_address": r.get("address", ""),
            "grade": g,
        })
        print(f"  ✗ 추출 실패\n")
    else:
        old_meta = bool(r.get("phone") or r.get("place_url"))
        new_meta = bool(new_entry.get("phone") or new_entry.get("place_url"))
        old_name = r.get("name", "") or ""
        new_name = new_entry.get("name", "") or ""

        # 교체 정책 (기존 검증 데이터를 잘못 덮어쓰지 않도록 보수적)
        old_is_generic = (old_name in au.GENERIC_NAMES) or (not old_name)
        new_is_generic = (new_name in au.GENERIC_NAMES) or (not new_name)
        should_replace = False
        reason = ""

        if new_meta and old_meta:
            # 둘 다 메타 있음 → 이름 유사도로 판단
            sim = au.name_similarity(old_name, new_name)
            if sim >= 0.5:
                should_replace = True
                reason = f"표준화 (sim={sim:.2f})"
            else:
                reason = f"기존 검증 보존 (이름 상이 sim={sim:.2f})"
        elif new_meta and not old_meta:
            should_replace = True
            reason = "신규에 Kakao 메타 추가"
        elif not new_meta and not old_meta:
            if not new_is_generic and old_is_generic:
                should_replace = True
                reason = "이름 구체화"
            else:
                reason = "둘 다 메타 없음, 신규 개선 없음"
        else:  # old_meta but not new_meta
            reason = "기존이 더 신뢰도 높음 (메타 유지)"

        if should_replace:
            # 원본 영상 메타데이터 보존
            new_entry["upload_date"] = r.get("upload_date") or new_entry.get("upload_date")
            new_entry["video_title"] = r.get("video_title") or new_entry.get("video_title")
            new_entry["video_url"]   = r.get("video_url")   or new_entry.get("video_url")
            new_entry["thumbnail"]   = r.get("thumbnail")   or new_entry.get("thumbnail")
            if not args.dry_run:
                data[data_i] = new_entry
            updated += 1
            print(f"  ✓ 업데이트 ({reason}): {new_name} @ {(new_entry.get('address','') or '')[:35]}\n")
        else:
            kept += 1
            print(f"  ⊘ 유지 (신규 정보 부족: {new_name})\n")

    # 10개마다 중간 저장 + 진행률
    if (idx + 1) % 10 == 0:
        elapsed = time.time() - t_start
        rate = (idx + 1) / elapsed
        remaining = (min(args.limit, len(candidates)) - idx - 1) / rate
        print(f"  ─── 누적: 업데이트 {updated} / 유지 {kept} / 실패 {failed} "
              f"| 진행 {idx+1}/{args.limit} | 남은 시간 ~{remaining/60:.1f}분 ───\n")
        if not args.dry_run:
            STATE_FILE.write_text(
                json.dumps({"processed_video_ids": list(processed_ids)}, ensure_ascii=False),
                encoding="utf-8")
            FAIL_LOG_FILE.write_text(
                json.dumps(failures, ensure_ascii=False, indent=2),
                encoding="utf-8")
            GEO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# 최종 저장
if not args.dry_run:
    STATE_FILE.write_text(
        json.dumps({"processed_video_ids": list(processed_ids)}, ensure_ascii=False),
        encoding="utf-8")
    FAIL_LOG_FILE.write_text(
        json.dumps(failures, ensure_ascii=False, indent=2),
        encoding="utf-8")
    GEO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

print()
print("=" * 60)
print(f"완료 — 업데이트 {updated} / 유지 {kept} / 실패 {failed}")
print(f"누적 처리: {len(processed_ids)} / 남은 후보: {len(candidates) - args.limit}")
print(f"소요 시간: {(time.time() - t_start)/60:.1f}분")
print("=" * 60)
