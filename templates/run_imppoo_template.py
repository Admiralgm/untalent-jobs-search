#!/usr/bin/env python3
"""
Impactpool.org scanner — adapted from untalent-jobs-search v3.2
Scrape + prefilter + save + PROBLEM REPORT.
Usage: python3 run_imppoo.py [/output/path]
"""
import asyncio, re, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from scrapling.fetchers import StealthyFetcher

BASE_DIR = Path("~/Downloads/TEST")
OUTPUT_DIR = BASE_DIR / "IMPTPOO"

SEARCH_BASE = (
    "https://www.impactpool.org/search"
    "?q=&jf%5B%5D=77&jf%5B%5D=64&jf%5B%5D=104&jf%5B%5D=860"
    "&jf%5B%5D=135&jf%5B%5D=667&jf%5B%5D=105"
)
PER_PAGE = 40
MAX_PAGES = 50
CONCURRENT = 4

class ProblemTracker:
    def __init__(self): self.problems = []; self.stats = Counter()
    def log(self, cat, det, jid=None):
        self.problems.append({"category": cat, "detail": det, "jid": jid})
        self.stats[cat] += 1
    def report(self):
        if not self.problems:
            print("\n  No problems."); return
        print(f"\n  PROBLEMS ({len(self.problems)}):")
        for cat, count in self.stats.most_common():
            print(f"    {cat}: {count}")

tracker = ProblemTracker()

HARD_REJECT = re.compile(
    r"(intern|stagiaire|volunteer|unpaid|nutrition|agricultur|wash specialist|"
    r"sanitation engineer|civil engineer|shelter|procurement|human rights|medical|"
    r"doctor|nurse|midwife|teacher|pedagog|child protection|gender|accountant|"
    r"finance officer|budget officer|audit|hr officer|human resources|admin officer|"
    r"logistics|supply chain|warehouse|fleet|security officer|driver|interpreter|"
    r"translator|cook|cleaner|maintenance|electrician|plumber)", re.I)

ICT_KW = [
    " it ", " ict ", " isp ", " ai ", " artificial ", " telecom ", " connectivity ",
    " innovation ", "information technology", "chief technology", " cto ",
    " chief information ", " cio ", " digital transformation ", " digital officer ",
    " systems administrator ", " network engineer ", " network administrator ",
    " software engineer ", " software developer ", " data engineer ", " data scientist ",
    " cybersecurity ", " information security ", " devops ", " cloud engineer ",
    " cloud architect ", " database administrator ", " web developer ",
    " full stack ", " machine learning ", " deep learning ",
    " solutions architect ", " enterprise architect ", " technical lead ",
    "it officer", "it specialist", "it manager",
    "ict officer", "ict specialist", "ict coordinator",
    "ai engineer", "ai research", "telecommunications", "innovation officer",
    "digital specialist", "digital officer", "digital advisor",
    "tech lead", "technology officer", "technology specialist",
    "system administrator", "systems engineer", "platform engineer",
    "fullstack", "front-end developer", "backend developer",
    "cloud computing", "data analyst", "data analytics",
    "business intelligence", "information management", "knowledge management",
    "infrastructure engineer", "site reliability", "devsecops",
    "machine learning engineer", "natural language processing",
    "computer vision", "robotics engineer", "automation engineer",
    "blockchain", "distributed systems", "microservices",
    "api developer", "integration engineer",
    "it project manager", "it director", "head of it", "head of digital",
    "chief digital", "digital innovation",
    "information systems",
    "gis specialist", "geospatial",
    "data warehouse", "data lake",
    "python developer", "java developer",
    "technology for development", "digital development",
    "digital health", "fintech", "digital finance",
    "internet of things", "iot developer", "embedded systems",
    "data center", "data centre", "network operations",
]

def is_ict_title(title):
    t = " " + title.lower() + " "
    if HARD_REJECT.search(title):
        return False, f"HARD-REJECT: '{title[:50]}'"
    for kw in ICT_KW:
        if kw in t:
            return True, f"ICT-PASS: '{kw.strip()}'"
    return False, f"ICT-FAIL: '{title[:50]}'"

def is_ict_full(title, body):
    return any(kw in (title + " " + body[:1000]).lower() for kw in ICT_KW)

def sanitize(name):
    return re.sub(r'\s+', '_', re.sub(r'[^a-zA-Z0-9\-_\s]', '', name).strip())[:60]

def load_existing_ids():
    existing_jids = set()
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.glob("IMPTPOO_*.md"):
            parts = f.stem.split("_", 2)
            if len(parts) >= 2:
                existing_jids.add(parts[1])
    return existing_jids

async def extract_all_jobs():
    all_jobs = []
    seen = set()
    for pn in range(1, MAX_PAGES + 1):
        url = f"{SEARCH_BASE}&page={pn}&per_page={PER_PAGE}"
        t0 = time.time()
        try:
            page = await StealthyFetcher.async_fetch(
                url, headless=True, disable_resources=True, wait=3000)
        except Exception as e:
            tracker.log("LISTING_ERROR", f"P{pn}: {e}")
            break
        elapsed = time.time() - t0
        if page.status != 200:
            tracker.log("LISTING_!200", f"P{pn}: {page.status}")
            break
        html = page.html_content or ""
        job_links = list(dict.fromkeys(
            re.findall(r'href="(/jobs/(\d{5,8}))"', html)
        ))
        if not job_links:
            break
        titles = {}
        for a in page.css('a[href*="/jobs/"]'):
            href = (a.css('::attr(href)').get() or '').strip()
            m = re.match(r'/jobs/(\d{5,8})(?:\?|/|$)', href)
            if not m:
                continue
            jid = m.group(1)
            text_parts = []
            for el in a.css('*'):
                t = (el.css('::text').get() or '').strip()
                if t and len(t) > 3:
                    text_parts.append(t)
            direct = (a.css('::text').get() or '').strip()
            if direct and len(direct) > 3:
                text_parts.insert(0, direct)
            if text_parts:
                titles[jid] = max(text_parts, key=len)
        new_count = 0
        for href, jid in job_links:
            if jid not in seen:
                seen.add(jid)
                all_jobs.append((jid, titles.get(jid, f"Job {jid}")))
                new_count += 1
        print(f"  P{pn}: {len(job_links)} found, {new_count} new, {len(seen)} total ({elapsed:.1f}s)")
        if len(job_links) < PER_PAGE:
            break
        await asyncio.sleep(0.5)
    return all_jobs

async def fetch_and_filter(all_jobs, existing_jids):
    candidates = []
    for jid, title in all_jobs:
        if jid in existing_jids:
            continue
        passed, reason = is_ict_title(title)
        if passed:
            candidates.append((jid, title))
        elif "HARD" in reason:
            pass
        else:
            tracker.log("TITLE_FAIL", f"{jid}: {reason}")
    print(f"  Candidates: {len(candidates)} (skipped {sum(1 for j,t in all_jobs if j in existing_jids)} existing)")
    if not candidates:
        return 0, 0, 0
    sem = asyncio.Semaphore(CONCURRENT)
    async def fetch_one(jid, title):
        t0 = time.time()
        async with sem:
            try:
                pg = await StealthyFetcher.async_fetch(
                    f"https://www.impactpool.org/jobs/{jid}",
                    headless=True, disable_resources=True, wait=2500)
                elapsed = time.time() - t0
                text = pg.get_all_text() or ""
                h1_el = pg.css("h1::text")
                h1 = (h1_el.get() or "").strip() if h1_el else ""
                final_title = h1 if h1 and len(h1) > 3 else title
                return jid, pg.status, len(text), text, final_title, elapsed
            except Exception as e:
                tracker.log("JD_ERR", f"{jid}: {e}", jid)
                return jid, 0, 0, f"ERR:{e}", title, time.time() - t0
    results = await asyncio.gather(*(fetch_one(j, t) for j, t in candidates))
    saved = skipped = failed = 0
    for jid, status, length, text, title, elapsed in results:
        if status != 200 or length < 500:
            failed += 1; continue
        if not is_ict_full(title, text):
            skipped += 1; continue
        fn = f"IMPTPOO_{jid}_{sanitize(title[:50])}.md"
        (OUTPUT_DIR / fn).write_text(
            f"# {title}\n\nSource: https://www.impactpool.org/jobs/{jid}\n\n{text}", "utf-8")
        print(f"  SAVED ({length//1024}KB): {title[:60]}")
        saved += 1
    return saved, skipped, failed

async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.time()
    existing_jids = load_existing_ids()
    print(f"Impactpool Scanner v3.2 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    existing_jids = load_existing_ids()
    print(f"Existing (skip): {len(existing_jids)}")
    all_jobs = await extract_all_jobs()
    saved, skipped, failed = await fetch_and_filter(all_jobs, existing_jids)
    te = time.time() - ts
    all_files = list(OUTPUT_DIR.glob("IMPTPOO_*.md"))
    total_size = sum(f.stat().st_size for f in all_files)
    new_count = len(all_files) - len(existing_jids)
    print(f"\nSCAN COMPLETE — {te:.1f}s")
    print(f"Total files: {len(all_files)} ({total_size // 1024}KB)")
    print(f"New this run: {new_count}")
    print(f"Fetch: {saved}s/{skipped}k/{failed}f")
    tracker.report()
    rp = BASE_DIR / "IMPTPOO_PROBLEMS_REPORT.txt"
    lines = [
        f"Impactpool Problem Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Time: {te:.1f}s | Total: {len(all_files)} | New: {new_count} | Existing: {len(existing_jids)} | Size: {total_size // 1024}KB",
        f"Jobs in listings: {len(all_jobs)} | Fetch: {saved}s/{skipped}k/{failed}f",
        f"Problems: {len(tracker.problems)} | Categories: {dict(tracker.stats)}", "", "Issues:"
    ]
    for p in tracker.problems:
        s = f" [{p['jid']}]" if p['jid'] else ""
        lines.append(f"  [{p['category']}]{s} {p['detail']}")
    rp.write_text("\n".join(lines), "utf-8")
    print(f"Report: {rp}")

if __name__ == "__main__":
    asyncio.run(main())
