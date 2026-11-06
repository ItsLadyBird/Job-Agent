"""
Job Search Agent — Daniela Arias
Sources: Remotive, Jobicy, Arbeitnow, HN Algolia, Workable, Otta, WTTJ, HelloWork
Scoring: Google Gemini free tier (rate limit handled automatically)

pip3 install google-genai requests beautifulsoup4 lxml
GEMINI_API_KEY=YOUR_KEY python3 agent.py
"""

import os, json, sqlite3, time, hashlib, argparse
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DB_PATH     = Path(__file__).parent / "jobs.db"
DIGEST_PATH = Path(__file__).parent / "index.html"
MAX_JOBS    = 50
GEMINI_DELAY = 13  # seconds between API calls — stays within free tier (5 req/min)

PROFILE = """
Name: Laura Daniela Arias ("Daniela")
Location: Paris, France. Open to: London, Berlin, Amsterdam, Barcelona, NY, SF, Remote.
Languages: English (native), Spanish (native), French (B2)

TARGET ROLES (priority):
1. VC Investment Associate / Analyst
2. Chief of Staff at VC firm
3. Chief of Staff / CSO / CXO at tech startup (seed–Series B)
4. COO at early-stage startup
5. Growth / UA Manager (consumer apps, health tech, Web3)
6. Ecosystem / Community Lead

INDUSTRIES (strong interest):
- AI, frontier tech, Web3, blockchain, Venture Capital
- Longevity, precision health, biotech, epigenetics
- Cleantech / climate tech
- Consumer apps, mobile gaming, EdTech
- Arts & culture intersecting with technology
- Network states, new governance models

EXCLUDE: legacy corporate, pure execution no strategy access, below 5yr seniority.

CV VERSIONS:
- LDAR_CoS_CV: Chief of Staff at tech startup
- LDAR_CoS_VC_CV: Chief of Staff at VC firm
- LDAR_Growth_UA: Growth / User Acquisition
- LDAR_VC_CV: VC Investment Associate
"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── DATABASE ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT,
        url TEXT, description TEXT, score INTEGER, cv_version TEXT,
        score_reason TEXT, scraped_at TEXT, applied INTEGER DEFAULT 0)""")
    conn.commit()
    return conn

def jid(url):      return hashlib.md5(url.encode()).hexdigest()[:16]
def seen(conn, i): return conn.execute("SELECT 1 FROM jobs WHERE id=?", (i,)).fetchone()

def save(conn, j):
    conn.execute("""INSERT OR IGNORE INTO jobs
        (id,title,company,location,url,description,score,cv_version,score_reason,scraped_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (j["id"], j["title"], j["company"], j["location"], j["url"],
         j.get("description","")[:800], j["score"], j["cv_version"],
         j["score_reason"], datetime.now().isoformat()))
    conn.commit()

# ── SOURCES ───────────────────────────────────────────────────────────────────

def remotive():
    jobs = []
    for cat in ["management-finance", "business-exec", "product", "marketing"]:
        try:
            r = requests.get(f"https://remotive.com/api/remote-jobs",
                params={"category": cat, "limit": 20}, headers=HEADERS, timeout=12)
            for j in r.json().get("jobs", []):
                jobs.append({
                    "title":       j.get("title",""),
                    "company":     j.get("company_name",""),
                    "location":    j.get("candidate_required_location","Remote"),
                    "url":         j.get("url",""),
                    "description": BeautifulSoup(j.get("description",""),"html.parser").get_text()[:2000],
                })
        except Exception as e:
            print(f"  Remotive error ({cat}): {e}")
        time.sleep(1)
    print(f"  Remotive: {len(jobs)} jobs")
    return jobs

def jobicy():
    jobs = []
    for tag in ["operations","management","growth","finance","venture-capital"]:
        try:
            r = requests.get("https://jobicy.com/api/v2/remote-jobs",
                params={"count":10,"tag":tag}, headers=HEADERS, timeout=12)
            for j in r.json().get("data",[]):
                jobs.append({
                    "title":       j.get("jobTitle",""),
                    "company":     j.get("companyName",""),
                    "location":    j.get("jobGeo","Remote"),
                    "url":         j.get("url",""),
                    "description": BeautifulSoup(j.get("jobDescription",""),"html.parser").get_text()[:2000],
                })
        except Exception as e:
            print(f"  Jobicy error ({tag}): {e}")
        time.sleep(1)
    print(f"  Jobicy: {len(jobs)} jobs")
    return jobs

def arbeitnow():
    jobs = []
    for tag in ["chief-of-staff","investment-associate","venture-capital",
                "operations-manager","growth-manager","coo","chief-strategy-officer"]:
        try:
            r = requests.get("https://www.arbeitnow.com/api/job-board-api",
                params={"page":1,"tags":tag}, headers=HEADERS, timeout=12)
            for j in r.json().get("data",[])[:10]:
                jobs.append({
                    "title":       j.get("title",""),
                    "company":     j.get("company_name",""),
                    "location":    j.get("location",""),
                    "url":         j.get("url",""),
                    "description": BeautifulSoup(j.get("description",""),"html.parser").get_text()[:2000],
                })
        except Exception as e:
            print(f"  Arbeitnow error ({tag}): {e}")
        time.sleep(1)
    print(f"  Arbeitnow: {len(jobs)} jobs")
    return jobs

def hn_hiring():
    jobs = []
    for kw in ["chief of staff","investment associate","chief strategy officer",
               "COO operations","growth marketing","venture capital hiring"]:
        try:
            r = requests.get("https://hn.algolia.com/api/v1/search_by_date",
                params={"query": kw+" hiring","tags":"comment","hitsPerPage":8},
                headers=HEADERS, timeout=10)
            for hit in r.json().get("hits",[]):
                text = hit.get("comment_text") or hit.get("story_text") or ""
                clean = BeautifulSoup(text,"html.parser").get_text()
                if len(clean) > 100 and any(w in clean.lower() for w in ["hiring","remote","salary","role","join"]):
                    jobs.append({
                        "title":       f"{kw.title()} — HN Hiring",
                        "company":     "",
                        "location":    "Remote / Global",
                        "url":         f"https://news.ycombinator.com/item?id={hit.get('objectID','')}",
                        "description": clean[:2000],
                    })
        except Exception as e:
            print(f"  HN error ({kw}): {e}")
        time.sleep(0.5)
    print(f"  HN Who's Hiring: {len(jobs)} leads")
    return jobs

def workable():
    jobs = []
    for q in ["chief of staff","investment associate","operations","growth","venture capital","COO","strategy"]:
        try:
            r = requests.get("https://jobs.workable.com/api/v1/jobs",
                params={"query":q,"details":"true"}, headers=HEADERS, timeout=12)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                data = r.json()
                for j in data.get("jobs", data.get("results",[]))[:8]:
                    url = j.get("url") or j.get("shortlink") or j.get("application_url","")
                    if not url: continue
                    jobs.append({
                        "title":    j.get("title",""),
                        "company":  j.get("company",{}).get("name","") if isinstance(j.get("company"),dict) else j.get("company",""),
                        "location": j.get("location",{}).get("city","") if isinstance(j.get("location"),dict) else j.get("location",""),
                        "url":      url,
                        "description": j.get("description","")[:2000],
                    })
        except Exception as e:
            print(f"  Workable error ({q}): {e}")
        time.sleep(1)
    print(f"  Workable: {len(jobs)} jobs")
    return jobs

def otta():
    jobs = []
    for q in ["chief-of-staff","investment-associate","operations","growth","venture-capital"]:
        try:
            r = requests.get("https://app.otta.com/api/jobs",
                params={"query":q,"page":1}, headers=HEADERS, timeout=12)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                data = r.json()
                for j in data.get("jobs", data.get("results", data.get("data",[])))[:8]:
                    url = j.get("url") or j.get("external_url","")
                    if not url: continue
                    desc = j.get("description") or j.get("job_description","")
                    if isinstance(desc,dict): desc = " ".join(str(v) for v in desc.values())
                    jobs.append({
                        "title":    j.get("title",""),
                        "company":  j.get("company",{}).get("name","") if isinstance(j.get("company"),dict) else j.get("company",""),
                        "location": j.get("location",""),
                        "url":      url,
                        "description": str(desc)[:2000],
                    })
        except Exception as e:
            print(f"  Otta error ({q}): {e}")
        time.sleep(1)
    print(f"  Otta: {len(jobs)} jobs")
    return jobs

def wttj():
    jobs = []
    for q in ["chief of staff","investment associate","chief strategy officer",
              "growth manager","COO","venture capital"]:
        try:
            r = requests.get("https://www.welcometothejungle.com/en/jobs",
                params={"query":q,"page":1}, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text,"html.parser")
            script = soup.find("script",id="__NEXT_DATA__")
            if script:
                try:
                    data = json.loads(script.string)
                    items = (data.get("props",{}).get("pageProps",{})
                                 .get("jobs", data.get("props",{}).get("pageProps",{}).get("results",[])))
                    for j in items[:8]:
                        jobs.append({
                            "title":       j.get("name","") or j.get("title",""),
                            "company":     j.get("organization",{}).get("name","") if isinstance(j.get("organization"),dict) else "",
                            "location":    j.get("location",""),
                            "url":         "https://www.welcometothejungle.com" + j.get("path",""),
                            "description": BeautifulSoup(j.get("description",""),"html.parser").get_text()[:2000],
                        })
                    continue
                except: pass
            for card in soup.select("li[data-testid], article, [class*=JobCard], [class*=job-card]")[:8]:
                title_el = card.select_one("h3, h2, [class*=title]")
                link_el  = card.select_one("a[href]")
                company_el = card.select_one("[class*=company],[class*=organization]")
                if title_el and link_el:
                    href = link_el["href"]
                    if not href.startswith("http"): href = "https://www.welcometothejungle.com" + href
                    jobs.append({
                        "title":    title_el.text.strip(),
                        "company":  company_el.text.strip() if company_el else "",
                        "location": "", "url": href, "description": "",
                    })
        except Exception as e:
            print(f"  WTTJ error ({q}): {e}")
        time.sleep(1.5)
    print(f"  Welcome to the Jungle: {len(jobs)} jobs")
    return jobs

def hellowork():
    jobs = []
    for q in ["chief of staff","directeur operations","investment associate",
              "growth manager","chief strategy officer"]:
        try:
            r = requests.get("https://www.hellowork.com/fr-fr/emploi/recherche.html",
                params={"k":q,"d":"all"}, headers=HEADERS, timeout=12)
            soup = BeautifulSoup(r.text,"html.parser")
            for script in soup.find_all("script",type="application/ld+json"):
                try:
                    data = json.loads(script.string)
                    items = [data] if isinstance(data,dict) else data
                    for item in items:
                        if item.get("@type") == "JobPosting":
                            jobs.append({
                                "title":    item.get("title",""),
                                "company":  item.get("hiringOrganization",{}).get("name",""),
                                "location": item.get("jobLocation",{}).get("address",{}).get("addressLocality",""),
                                "url":      item.get("url",""),
                                "description": BeautifulSoup(item.get("description",""),"html.parser").get_text()[:2000],
                            })
                except: pass
            for card in soup.select("li[class*=job], article[class*=job], [class*=JobCard]")[:8]:
                title_el   = card.select_one("h2, h3, [class*=title]")
                link_el    = card.select_one("a[href]")
                company_el = card.select_one("[class*=company],[class*=employer]")
                if title_el and link_el:
                    href = link_el["href"]
                    if not href.startswith("http"): href = "https://www.hellowork.com" + href
                    jobs.append({
                        "title":    title_el.text.strip(),
                        "company":  company_el.text.strip() if company_el else "",
                        "location": "France", "url": href, "description": "",
                    })
        except Exception as e:
            print(f"  HelloWork error ({q}): {e}")
        time.sleep(1.5)
    print(f"  HelloWork: {len(jobs)} jobs")
    return jobs

# ── SCORING ───────────────────────────────────────────────────────────────────

def score_job(client, job):
    prompt = f"""You are a job matching assistant.

CANDIDATE:
{PROFILE}

JOB:
Title: {job['title']}
Company: {job.get('company','')}
Location: {job.get('location','')}
Description: {job.get('description','')[:1500]}

Reply ONLY with valid JSON — no markdown:
{{
  "score": <0-100>,
  "score_reason": "<2 sentences>",
  "cv_version": "<LDAR_CoS_CV|LDAR_CoS_VC_CV|LDAR_Growth_UA|LDAR_VC_CV|SKIP>"
}}
SKIP if score < 35. 70+ = strong match."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(model="gemini-3.5-flash-lite", contents=prompt)
            text = resp.text.strip()
            if "```" in text:
                text = text.split("```")[1].lstrip("json").strip()
            return json.loads(text)
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 30 + (attempt * 15)
                print(f"    Rate limit hit — waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"    Gemini error: {e}")
                return {"score": 0, "score_reason": "Error", "cv_version": "SKIP"}
    return {"score": 0, "score_reason": "Rate limit", "cv_version": "SKIP"}

# ── DIGEST ────────────────────────────────────────────────────────────────────

def generate_digest(conn):
    rows = conn.execute("""SELECT * FROM jobs WHERE score>=50 AND applied=0
        ORDER BY score DESC, scraped_at DESC LIMIT 80""").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM jobs LIMIT 0").description]
    jobs = [dict(zip(cols,r)) for r in rows]
    strong = [j for j in jobs if j["score"] >= 70]
    review = [j for j in jobs if 50 <= j["score"] < 70]

    cv_colors = {
        "LDAR_CoS_CV":"#1C3A52","LDAR_CoS_VC_CV":"#2d4a7a",
        "LDAR_Growth_UA":"#1a6b4a","LDAR_VC_CV":"#6b1a4a",
    }

    def card(j):
        sc = j["score"]
        bg = cv_colors.get(j["cv_version"],"#888")
        sc_color = "#2a7a2a" if sc >= 70 else "#8a6a1a"
        return f"""
        <div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;
                    margin-bottom:12px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.04)">
          <div style="display:flex;justify-content:space-between;align-items:flex-start">
            <div style="flex:1">
              <div style="font-size:16px;font-weight:700;color:#1C3A52">{j['title']}</div>
              <div style="font-size:13px;color:#666;margin-top:3px">
                {j['company'] or '—'} · {j['location'] or '—'}</div>
            </div>
            <div style="text-align:right;flex-shrink:0;margin-left:16px">
              <div style="font-size:28px;font-weight:800;color:{sc_color}">{sc}</div>
              <div style="font-size:10px;color:#bbb">/100</div>
            </div>
          </div>
          <div style="margin-top:8px;font-size:13px;color:#555;line-height:1.5">
            {j['score_reason']}</div>
          <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <span style="background:{bg};color:#fff;padding:3px 10px;border-radius:4px;
                         font-size:11px;font-weight:600">{j['cv_version']}</span>
            <a href="{j['url']}" target="_blank"
               style="background:#1C3A52;color:#fff;padding:6px 14px;border-radius:4px;
                      text-decoration:none;font-size:13px;font-weight:600">View job →</a>
            <span style="font-size:11px;color:#ccc">{j['scraped_at'][:10]}</span>
          </div>
        </div>"""

    s_html = "".join(card(j) for j in strong) or "<p style='color:#aaa'>None today.</p>"
    r_html = "".join(card(j) for j in review) or "<p style='color:#aaa'>None today.</p>"
    now = datetime.now().strftime("%d %b %Y, %H:%M")

    DIGEST_PATH.write_text(f"""<!DOCTYPE html><html><head>
<meta charset="UTF-8"><title>Job Digest — {now}</title>
<style>body{{font-family:-apple-system,Arial,sans-serif;max-width:820px;margin:0 auto;
    padding:28px;background:#f4f5f7}}
h1{{color:#1C3A52;border-bottom:3px solid #1a6b8a;padding-bottom:10px;margin-bottom:6px}}
h2{{color:#1a6b8a;margin-top:32px;margin-bottom:12px}}</style></head><body>
<h1>🔍 Job Digest — Daniela</h1>
<p style="color:#888;font-size:13px;margin-bottom:28px">
  {now} · {len(strong)} strong · {len(review)} worth reviewing</p>
<h2>🟢 Strong Matches — score 70+</h2>{s_html}
<h2>🟡 Worth a Look — score 50–69</h2>{r_html}
<p style="font-size:11px;color:#ccc;text-align:center;margin-top:36px">
  Daniela Arias · Job Agent</p>
</body></html>""")

    print(f"\n✅ Digest ready — open index.html in your browser")
    print(f"   {len(strong)} strong · {len(review)} worth reviewing")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def run(digest_only=False):
    conn = init_db()
    if digest_only:
        generate_digest(conn); conn.close(); return

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("⚠️  Set GEMINI_API_KEY"); return

    from google import genai
    client = genai.Client(api_key=api_key)

    print("🔍 Collecting jobs from all sources...\n")
    raw = []
    for name, fn in [
        ("Remotive",              remotive),
        ("Jobicy",                jobicy),
        ("Arbeitnow",             arbeitnow),
        ("HN Who's Hiring",       hn_hiring),
        ("Workable",              workable),
        ("Otta",                  otta),
        ("Welcome to the Jungle", wttj),
        ("HelloWork",             hellowork),
    ]:
        print(f"[{name}]")
        raw += fn()

    print(f"\n📋 {len(raw)} total leads collected")

    # Deduplicate
    seen_ids, new = set(), []
    for j in raw:
        if not j.get("url"): continue
        i = jid(j["url"])
        if i not in seen_ids and not seen(conn, i):
            seen_ids.add(i); j["id"] = i; new.append(j)

    new = new[:MAX_JOBS]
    print(f"   {len(new)} new jobs to score\n")
    print(f"   ⏱  Estimated time: ~{round(len(new) * GEMINI_DELAY / 60)} minutes (free tier rate limit)\n")

    saved = 0
    for idx, j in enumerate(new, 1):
        print(f"  [{idx}/{len(new)}] {j['title'][:50]} @ {j.get('company','?')[:25]}")
        result = score_job(client, j)
        sc = result.get("score", 0)
        cv = result.get("cv_version", "SKIP")
        print(f"         → {sc}/100 · {cv}")
        if cv != "SKIP":
            save(conn, {**j, "score": sc, "cv_version": cv,
                        "score_reason": result.get("score_reason","")})
            saved += 1
        time.sleep(GEMINI_DELAY)  # respect free tier: 5 requests/min

    print(f"\n✅ {saved} new jobs saved")
    generate_digest(conn)
    conn.close()

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--digest", action="store_true")
    run(digest_only=p.parse_args().digest)
