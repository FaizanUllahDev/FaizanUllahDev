import datetime as dt, html, json, os, re, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

USER=os.environ.get("PROFILE_LOGIN","FaizanUllahDev")
TOKEN=os.environ.get("GH_METRICS_TOKEN","")
DEST=Path("assets/github-metrics.svg")
calls=0
class EmptyCommitHistory(Exception):
    """GitHub reports an empty/uninitialized Git repository."""


def get(path,params={}):
    global calls
    if calls>=450: raise RuntimeError("API budget exceeded")
    calls+=1
    url="https://api.github.com"+path+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"Authorization":"Bearer "+TOKEN,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"profile-metrics"})
    for retry in range(3):
        try:
            with urllib.request.urlopen(req,timeout=25) as response: return json.load(response)
        except urllib.error.HTTPError as error:
            remaining = error.headers.get("X-RateLimit-Remaining", "unknown")
            reset = error.headers.get("X-RateLimit-Reset", "unknown")
            accepted = error.headers.get("X-Accepted-GitHub-Permissions", "not specified")
            if error.code in (429,500,502,503,504) and retry<2:
                time.sleep(2**retry)
                continue
            if error.code == 403:
                if remaining == "0":
                    raise RuntimeError("GitHub API rate limit exhausted; reset epoch %s. Previous metrics preserved." % reset) from None
                raise RuntimeError(
                    "GitHub returned HTTP 403 when accessing a %s endpoint. "
                    "Required API permissions: %s. Verify GH_METRICS_TOKEN has "
                    "Contents: Read for each selected private/public repository; "
                    "organization repositories may require separate owner approval. "
                    "No partial chart will be published." %
                    ("commit-history" if path.endswith("/commits") else "other", accepted)
                ) from None
            if error.code == 409 and path.endswith("/commits"):
                raise EmptyCommitHistory() from None
            if error.code == 404:
                raise RuntimeError(
                    "Repository/API path not available to GH_METRICS_TOKEN (HTTP 404). "
                    "Check selected repository access and Contents: Read; no partial chart published."
                ) from None
            raise RuntimeError("GitHub API returned HTTP %s; previous chart preserved" % error.code) from None
    raise RuntimeError("GitHub API unavailable")

def pages(path,params={},max_pages=80):
    for page in range(1,max_pages+1):
        data=get(path,dict(params,per_page=100,page=page))
        if not isinstance(data,list):raise RuntimeError("Non-list API result")
        yield from data
        if len(data)<100:return
    raise RuntimeError("Incomplete pagination")

def render(counts):
    """Render accurate account stats and a clearly defined activity tier."""
    tier = "A+" if counts["commits"] >= 200 and counts["prs"] >= 25 else (
        "A" if counts["commits"] >= 100 and counts["prs"] >= 10 else
        "B" if counts["commits"] >= 25 or counts["prs"] >= 5 else "C")
    items = [("Repositories", counts["total"]), ("Public / private", "%s / %s" % (counts["public"], counts["private"])),
             ("Commits YTD", counts["commits"]), ("Authored PRs", counts["prs"])]
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="620" height="288" viewBox="0 0 620 288" role="img" aria-label="Authenticated GitHub statistics and activity tier">',
           '<rect x="1" y="1" width="618" height="286" rx="14" fill="#0d1117" stroke="#30363d" stroke-width="2"/>',
           '<text x="26" y="41" font-family="Arial,sans-serif" font-size="23" font-weight="700" fill="#e6edf3">GitHub Stats</text>',
           '<text x="26" y="65" font-family="Arial,sans-serif" font-size="12" fill="#8b949e">Authorized public + private activity</text>']
    for i, (label, value) in enumerate(items):
        y = 105 + i * 38
        out.append('<text x="34" y="%s" font-size="15" font-family="Arial,sans-serif" fill="#c9d1d9">%s</text>' % (y, html.escape(label)))
        out.append('<text x="325" y="%s" text-anchor="end" font-size="20" font-family="Arial,sans-serif" font-weight="700" fill="#79c0ff">%s</text>' % (y+2, html.escape(str(value))))
    out.extend([
        '<circle cx="487" cy="142" r="70" fill="none" stroke="#30363d" stroke-width="13"/>',
        '<circle cx="487" cy="142" r="70" fill="none" stroke="#79c0ff" stroke-width="13" stroke-dasharray="330 440" transform="rotate(-90 487 142)" stroke-linecap="round"/>',
        '<text x="487" y="151" text-anchor="middle" font-family="Arial,sans-serif" font-size="39" font-weight="700" fill="#e6edf3">%s</text>' % html.escape(tier),
        '<text x="487" y="175" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#8b949e">Activity tier</text>',
        '<text x="26" y="272" font-family="Arial,sans-serif" font-size="11" fill="#8b949e">Updated %s UTC · default-branch commits</text>' % html.escape(counts["date"]),
        '</svg>'])
    return "\n".join(out) + "\n"


if not TOKEN:raise SystemExit("Configure GH_METRICS_TOKEN repository Actions secret first")
me=get("/user")
if me.get("login","").lower()!=USER.lower():raise RuntimeError("Token identity mismatch")
repos=list(pages("/user/repos",{"affiliation":"owner,collaborator,organization_member","sort":"full_name"}))
private=sum(bool(r.get("private")) for r in repos)
since=dt.datetime.now(dt.timezone.utc).strftime("%Y-01-01T00:00:00Z")
commits=0
for r in repos:
    if not r.get("default_branch") or r.get("disabled") or r.get("archived"):continue
    path="/repos/"+"/".join(urllib.parse.quote(p,safe="") for p in r["full_name"].split("/"))+"/commits"
    try:
        for _ in pages(path,{"sha":r["default_branch"],"author":USER,"since":since},max_pages=30):
            commits+=1
    except EmptyCommitHistory:
        # GitHub returns HTTP 409 for empty / not-yet-initialized Git histories.
        # Do not ignore other API errors; those may indicate partial counts.
        print("Skipping repository without available commit history")
        continue
prs=get("/search/issues",{"q":"type:pr author:"+USER,"per_page":1})
if prs.get("incomplete_results"):raise RuntimeError("Incomplete PR search")
counts={"total":len(repos),"public":len(repos)-private,"private":private,"prs":prs["total_count"],"commits":commits,"date":dt.datetime.now(dt.timezone.utc).strftime("%d %b %Y %H:%M")}
output=render(counts)
DEST.parent.mkdir(exist_ok=True,parents=True)
if DEST.exists():
    stable=lambda t:re.sub(r"Updated [^<]+ UTC","Updated TIMESTAMP UTC",t)
    if stable(DEST.read_text())==stable(output):
        print("Unchanged");raise SystemExit(0)
DEST.write_text(output)
print("Updated aggregated metric chart")
