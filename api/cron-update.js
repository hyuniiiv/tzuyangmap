// Vercel Cron 엔드포인트 — 매일 자정에 GitHub Actions auto_update 워크플로우 트리거
// GitHub Actions의 schedule이 자주 스킵되는 문제 해결용 (Vercel cron은 신뢰성 높음)

export default async function handler(req, res) {
  // 보안: Vercel cron만 호출 가능하게
  const authHeader = req.headers.authorization || "";
  const secret = process.env.CRON_SECRET;
  if (secret && authHeader !== `Bearer ${secret}`) {
    return res.status(401).json({ error: "unauthorized" });
  }

  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    return res.status(500).json({ error: "GITHUB_TOKEN not set" });
  }

  try {
    const resp = await fetch(
      "https://api.github.com/repos/hyuniiiv/tzuyangmap/actions/workflows/update.yml/dispatches",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "tzuyangmap-vercel-cron",
        },
        body: JSON.stringify({ ref: "master" }),
      }
    );

    if (resp.ok) {
      return res.status(200).json({
        ok: true,
        triggered_at: new Date().toISOString(),
        message: "GitHub Actions workflow dispatched",
      });
    } else {
      const text = await resp.text();
      return res.status(resp.status).json({ ok: false, error: text });
    }
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e) });
  }
}
