"""최근 upload_date 15개 영상 매장을 재점검 — 자막/댓글/LLM 재추출.

기존 데이터와 비교해서 차이가 있으면 사용자에게 표시.
확정하면 별도 명령으로 반영 (자동 반영 X).
"""
import sys, json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import auto_update as au

GEO = ROOT / "public" / "data" / "restaurants_geo.json"
data = json.loads(GEO.read_text(encoding="utf-8"))

# upload_date 기준 최근 유니크 영상 15개
data.sort(key=lambda r: r.get("upload_date","") or "", reverse=True)
seen = set()
targets = []
for r in data:
    vid = r.get("video_id","")
    if not vid or vid in seen: continue
    seen.add(vid)
    targets.append({
        "video_id": vid,
        "video_title": r.get("video_title",""),
        "video_url": r.get("video_url", f"https://www.youtube.com/watch?v={vid}"),
        "thumbnail": r.get("thumbnail", f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"),
        "upload_date": r.get("upload_date",""),
    })
    if len(targets) >= 15: break

print(f"재점검 대상: {len(targets)}개 영상\n")

# 각 영상 처리 (auto_update.process_new_video)
results = []
for i, v in enumerate(targets):
    print(f"[{i+1}/{len(targets)}] [{v['upload_date']}] {v['video_title'][:60]}")

    # 기존 매장 목록
    old_entries = [r for r in data if r.get("video_id") == v["video_id"]]
    for oe in old_entries:
        print(f"    기존: {oe.get('name','')[:22]:22} @ {(oe.get('address','') or '')[:35]}")

    # 재추출
    video_arg = {"id": v["video_id"], "title": v["video_title"],
                 "url": v["video_url"], "thumbnail": v["thumbnail"],
                 "channel": "tzuyang"}
    try:
        new_entries = au.process_new_video(video_arg) or []
    except Exception as e:
        print(f"    ✗ 재추출 예외: {e}")
        new_entries = []

    if new_entries:
        for ne in new_entries:
            print(f"    신규: {ne.get('name','')[:22]:22} @ {(ne.get('address','') or '')[:35]}")
    else:
        print(f"    ✗ 신규 결과 없음")

    # 비교 (매장명 + 주소 조합)
    old_keys = {(oe.get("name","") + "|" + (oe.get("address","") or "")) for oe in old_entries}
    new_keys = {(ne.get("name","") + "|" + (ne.get("address","") or "")) for ne in new_entries}
    changed = old_keys != new_keys

    results.append({
        "video_id": v["video_id"],
        "video_title": v["video_title"],
        "upload_date": v["upload_date"],
        "old_entries": [{"name": oe.get("name",""), "address": oe.get("address","")} for oe in old_entries],
        "new_entries": [dict(ne) for ne in new_entries],
        "changed": changed,
    })
    print(f"    {'⚠️  변경 감지' if changed else '✓ 동일'}\n")

# 저장
out = ROOT / "scripts" / ".recheck_recent.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

changed_n = sum(1 for r in results if r["changed"])
print(f"\n=== 요약 ===")
print(f"전체: {len(results)}개")
print(f"변경 감지: {changed_n}개")
print(f"결과 저장: {out.name}")
