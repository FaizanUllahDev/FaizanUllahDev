import datetime as dt, html, json, os, re, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

USER=os.environ.get("PROFILE_LOGIN","FaizanUllahDev")
TOKEN=os.environ.get("GH_METRICS_TOKEN","")
DEST=Path("assets/github-metrics.svg")
calls=0
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
    labels=[("Repositories",counts["total"]),("Public",counts["public"]),("Private",counts["private"]),("Authored PRs",counts["prs"]),("Commits YTD",counts["commits"])]
    out=['<svg xmlns="http://www.w3.org/2000/svg" width="890" height="240" viewBox="0 0 890 240" role="img" aria-label="Aggregated GitHub activity">','<rect x="1" y="1" width="888" height="238" rx="16" stroke="#30363d" stroke-width="2" fill="#0d1117"/>','<text x="28" y="38" font-size="21" font-family="Arial,sans-serif" font-weight="bold" fill="#e6edf3">GitHub engineering activity</text>']
    for i,(label,value) in enumerate(labels):
        x=28+i*172
        out+=['<rect x="%s" y="76" width="160" height="107" rx="9" fill="#161b22" stroke="#30363d"/>'%x,'<text x="%s" y="122" text-anchor="middle" font-size="32" font-family="Arial,sans-serif" font-weight="bold" fill="#79c0ff">%s</text>'%(x+80,html.escape(str(value))),'<text x="%s" y="151" text-anchor="middle" font-size="13" font-family="Arial,sans-serif" fill="#c9d1d9">%s</text>'%(x+80,html.escape(label))]
    out+=['<text x="28" y="215" font-size="11" font-family="Arial,sans-serif" fill="#8b949e">Authenticated aggregates · Default-branch commits authored since Jan 1 · Updated %s UTC</text>'%counts["date"],'</svg>']
    return "\n".join(out)+"\n"

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
    for _ in pages(path,{"sha":r["default_branch"],"author":USER,"since":since},max_pages=30): commits+=1
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
