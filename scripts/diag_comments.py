"""
유튜브 댓글 가져오기 다양한 방법 진단.
- yt-dlp 기본 / player_client 변경 / 다양한 sort
- youtube-comment-downloader (대체 라이브러리)
- 어떤 방법이 GitHub Actions IP에서 작동하는지 확인
"""
import sys, subprocess, json
from pathlib import Path

vid = sys.argv[1] if len(sys.argv) >= 2 else "4aWsXmyZtOg"
SUB = Path(__file__).parent / "subs"
SUB.mkdir(exist_ok=True)
url = f"https://www.youtube.com/watch?v={vid}"

print("=" * 70)
print(f"댓글 페치 진단: {vid}")
print("=" * 70)


def try_yt_dlp(label, extra_args):
    """yt-dlp 옵션 변형 시도"""
    print(f"\n──── {label} ────")
    info_p = SUB / f"{vid}.info.json"
    if info_p.exists(): info_p.unlink()
    cmd = ["yt-dlp", "--skip-download", "--write-info-json", "--write-comments",
           "--no-warnings", "-o", str(SUB / "%(id)s"), url] + extra_args
    print(f"명령: {' '.join(cmd[6:])}")
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    print(f"exit={r.returncode}")
    if r.stderr:
        print(f"stderr: {r.stderr[:500]}")
    if r.stdout:
        print(f"stdout: {r.stdout[:300]}")
    if info_p.exists():
        try:
            info = json.loads(info_p.read_text(encoding="utf-8"))
            comments = info.get("comments") or []
            print(f"→ 댓글 수: {len(comments)}")
            if comments:
                print(f"   첫번째: {(comments[0].get('text') or '')[:120]}")
            return len(comments)
        except Exception as e:
            print(f"info.json 파싱 실패: {e}")
            return 0
    print("  info.json 생성 안됨")
    return 0


# 1. 기본 옵션
try_yt_dlp("yt-dlp 기본",
           ["--extractor-args", "youtube:max_comments=20,10;comment_sort=top"])

# 2. player_client=android
try_yt_dlp("yt-dlp android client",
           ["--extractor-args", "youtube:player_client=android;max_comments=20,10;comment_sort=top"])

# 3. player_client=mweb (모바일 웹)
try_yt_dlp("yt-dlp mweb client",
           ["--extractor-args", "youtube:player_client=mweb;max_comments=20,10;comment_sort=top"])

# 4. player_client=web
try_yt_dlp("yt-dlp web client",
           ["--extractor-args", "youtube:player_client=web;max_comments=20,10;comment_sort=top"])

# 5. sort=new
try_yt_dlp("yt-dlp sort=new",
           ["--extractor-args", "youtube:max_comments=20,10;comment_sort=new"])


# 대체 라이브러리: youtube-comment-downloader (web scraping)
print("\n──── youtube-comment-downloader ────")
try:
    from youtube_comment_downloader import YoutubeCommentDownloader
    dl = YoutubeCommentDownloader()
    comments = list(dl.get_comments_from_url(url, sort_by=0, language="ko"))[:20]
    print(f"→ 가져온 댓글: {len(comments)}")
    if comments:
        print(f"   첫번째: {(comments[0].get('text') or '')[:150]}")
        print(f"   두번째: {(comments[1].get('text') or '')[:150]}" if len(comments) > 1 else "")
except ImportError:
    print("→ youtube-comment-downloader 미설치 (pip install youtube-comment-downloader)")
except Exception as e:
    print(f"→ 실패: {type(e).__name__}: {e}")
