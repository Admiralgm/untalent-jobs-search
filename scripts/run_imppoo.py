#!/usr/bin/env python3
"""
Impactpool.org scanner — adapted from untalent-jobs-search v3.1
Scrape + prefilter + save + PROBLEM REPORT.
Follows same ICT keyword pre-filtering and two-stage pipeline.

Usage: python3 run_scratch.py [/output/path]
"""
import asyncio, re, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from scrapling.fetchers import StealthyFetcher

BASE_DIR = Path("~/Downloads/TEST")
OUTPUT_DIR = BASE_DIR / "IMPTPOO"

# Impactpool search URL base (page appended as &page=N&per_page=40)
SEARCH_BASE = (
    "https://www.impactpool.org/search"
    "?q=&jf%5B%5D=77&jf%5B%5D=64&jf%5B%5D=104&jf%5B%5D=860"
    "&jf%5B%5D=135&jf%5B%5D=667&jf%5B%5D=105"
)
PER_PAGE = 40
MAX_PAGES = 50  # safety cap (~2000 jobs)
CONCURRENT = 4  # be gentle on impactpool

# ── PROBLEM TRACKER ─────────────────────────────────────────────────────
class ProblemTracker:
    def __init__(self): self.problems = []; self.stats = Counter()
    def log(self, cat, det, jid=None):
        self.problems.append({"category": cat, "detail": det, "jid": jid})
        self.stats[cat] += 1
    def report(self):
        if not self.problems:
            print("\n  ✅ No problems."); return
        print(f"\n  ⚠️  PROBLEMS ({len(self.problems)}):")
        for cat, count in self.stats.most_common():
            print(f"    {cat}: {count}")
        for p in self.problems:
            s = f" [{p['jid']}]" if p['jid'] else ""
            print(f"    [{p['category']}]{s} {p['detail']}")

tracker = ProblemTracker()

# ── ICT PRE-FILTER (same keywords as untalent-jobs-search) ──────────────
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
    "machine learning engineer", "deep learning", "natural language processing",
    "computer vision", "robotics engineer", "automation engineer",
    "blockchain", "distributed systems", "microservices",
    "api developer", "integration engineer", "middleware",
    "erp consultant", "crm consultant", "business analyst it",
    "it project manager", "it director", "head of it", "head of digital",
    "chief digital", "digital innovation", "emerging technology",
    "technology strategy", "it strategy", "it governance",
    "information systems", "management information",
    "gis specialist", "geospatial", "spatial data",
    "data warehouse", "data lake", "etl developer",
    "bi developer", "business intelligence developer",
    "report developer", "database developer", "sql developer",
    "python developer", "java developer", "javascript developer",
    "web application", "mobile developer", "app developer",
    "ui designer", "ux designer", "product designer digital",
    "technology for development", "digital development",
    "digital health", "e-health", "mhealth", "telemedicine",
    "fintech", "digital finance", "mobile money",
    "internet of things", "iot developer", "embedded systems",
    "firmware engineer", "hardware engineer it",
    "quantum computing", "high performance computing", "hpc",
    "data center", "data centre", "network operations", "noc engineer",
    "it support", "help desk", "technical support it",
    "it procurement", "it asset management",
    "digital platform", "platform developer", "developer platform",
    "open source developer", "freelance developer web",
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

# ── EXISTING FILE CHECK ─────────────────────────────────────────────────
def load_existing_ids():
    existing_jids = set()
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.glob("IMPTPOO_*.md"):
            parts = f.stem.split("_", 2)
            if len(parts) >= 2:
                existing_jids.add(parts[1])
    return existing_jids

# ── PHASE 1 — Extract job IDs from listing pages ───────────────────────
async def extract_all_jobs():
    """Paginate through Impactpool search results, collect all job IDs + titles."""
    all_jobs = []  # [(jid, title), ...]
    seen = set()
    total_pages = 0

    print("=" * 70)
    print("PHASE 1 — Impactpool.org job listing extraction")
    print("=" * 70)

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
            tracker.log("LISTING_!200", f"P{ppn}: {page.status}")
            if pn == 1:
                break
            continue

        # Extract job links: <a href="/jobs/NUMBER ...">
        html = page.html_content or ""
        job_links = list(dict.fromkeys(
            re.findall(r'href="(/jobs/(\d{5,8}))"', html)
        ))

        if not job_links:
            print(f"  P{pn}: no job links found, stopping")
            break

        # Extract titles from anchor text
        titles = {}
        for a in page.css('a[href*="/jobs/"]'):
            href = (a.css('::attr(href)').get() or '').strip()
            m = re.match(r'/jobs/(\d{5,8})(?:\?|/|$)', href)
            if not m:
                continue
            jid = m.group(1)
            # Get text from the anchor or nearby heading
            text_parts = []
            for el in a.css('*'):
                t = (el.css('::text').get() or '').strip()
                if t and len(t) > 3:
                    text_parts.append(t)
            # Also try direct text
            direct = (a.css('::text').get() or '').strip()
            if direct and len(direct) > 3:
                text_parts.insert(0, direct)
            if text_parts:
                # Use longest text as title (most descriptive)
                titles[jid] = max(text_parts, key=len)

        new_count = 0
        for href, jid in job_links:
            if jid not in seen:
                seen.add(jid)
                title = titles.get(jid, f"Job {jid}")
                all_jobs.append((jid, title))
                new_count += 1

        total_pages += 1
        print(f"  P{pn}: {len(job_links)} found, {new_count} new, {len(seen)} total ({elapsed:.1f}s)")

        # If we got fewer than PER_PAGE results, it's the last page
        if len(job_links) < PER_PAGE:
            print(f"  Last page ({len(job_links)} < {PER_PAGE})")
            break

        await asyncio.sleep(0.5)  # polite delay

    print(f"  Total: {len(all_jobs)} jobs from {total_pages} pages")
    return all_jobs

# ── PHASE 2 — Pre-filter + fetch JDs ───────────────────────────────────
async def fetch_and_filter(all_jobs, existing_jids):
    """Apply ICT pre-filter, fetch matching JDs, save to disk."""
    print("\n" + "=" * 70)
    print("PHASE 2 — Pre-filter + fetch job descriptions")
    print("=" * 70)

    # Stage 1: Title pre-filter
    candidates = []
    hr = ir = 0
    for jid, title in all_jobs:
        if jid in existing_jids:
            continue
        passed, reason = is_ict_title(title)
        if passed:
            candidates.append((jid, title))
        elif "HARD" in reason:
            hr += 1
        else:
            ir += 1
            tracker.log("TITLE_FAIL", f"{jid}: {reason}")

    print(f"  Total new (not in existing): {len([j for j,t in all_jobs if j not in existing_jids])}")
    print(f"  Title pre-filter: {len(candidates)} pass, {hr} hard-reject, {ir} ICT-fail")
    print(f"  Existing (skipped): {sum(1 for j,t in all_jobs if j in existing_jids)}")

    if not candidates:
        tracker.log("NO_CANDIDATES", "all rejected at title stage")
        return 0, 0, 0

    # Stage 2: Fetch full JD + full-text pre-filter
    print(f"  Fetching {len(candidates)} JDs ({CONCURRENT} concurrent)...")
    sem = asyncio.Semaphore(CONCURRENT)
    fetch_times = []

    async def fetch_one(jid, title):
        t0 = time.time()
        async with sem:
            try:
                pg = await StealthyFetcher.async_fetch(
                    f"https://www.impactpool.org/jobs/{jid}",
                    headless=True, disable_resources=True, wait=2500)
                elapsed = time.time() - t0
                fetch_times.append(elapsed)
                text = pg.get_all_text() or ""
                h1_el = pg.css("h1::text")
                h1 = (h1_el.get() or "").strip() if h1_el else ""
                final_title = h1 if h1 and len(h1) > 3 else title

                if pg.status != 200:
                    tracker.log("JD_!200", f"{jid}: status={pg.status}", jid)
                elif elapsed > 20:
                    tracker.log("JD_SLOW", f"{jid}: {elapsed:.1f}s", jid)
                elif len(text) < 500:
                    tracker.log("JD_STUB", f"{jid}: {len(text)}B", jid)

                return jid, pg.status, len(text), text, final_title
            except Exception as e:
                elapsed = time.time() - t0
                tracker.log("JD_ERR", f"{jid}: {type(e).__name__}: {e}", jid)
                return jid, 0, 0, f"ERR:{e}", title

    fs = time.time()
    results = await asyncio.gather(*(fetch_one(j, t) for j, t in candidates))

    saved = skipped = failed = 0
    for jid, status, length, text, title in results:
        if status != 200 or length < 500:
            failed += 1
            continue
        if not is_ict_full(title, text):
            skipped += 1
            tracker.log("FULL_FAIL", f"{jid}: {title[:60]}", jid)
            print(f"  SKIP: {title[:60]}")
            continue
        fn = f"IMPTPOO_{jid}_{sanitize(title[:50])}.md"
        org = ""
        # Try to extract organization from text
        org_match = re.search(r'(?:Organization|Employer|Company)\s*[:\n]\s*(.+)', text[:500], re.I)
        if org_match:
            org = org_match.group(1).strip()[:100]
        (OUTPUT_DIR / fn).write_text(
            f"# {title}\n\n"
            f"Source: https://www.impactpool.org/jobs/{jid}\n"
            f"{'Organization: ' + org + chr(10) if org else ''}\n"
            f"{text}", "utf-8")
        if length < 1500:
            tracker.log("SMALL", f"{jid}: {length}B", jid)
        size_kb = length // 1024
        print(f"  SAVED ({size_kb}KB): {title[:60]}")
        saved += 1

    avg_f = sum(fetch_times) / len(fetch_times) if fetch_times else 0
    total_t = time.time() - fs
    print(f"  Impactpool: {saved}s/{skipped}k/{failed}f avg:{avg_f:.1f}s total:{total_t:.1f}s")
    return saved, skipped, failed

# ── MAIN ────────────────────────────────────────────────────────────────
async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.time()

    existing_jids = load_existing_ids()
    print(f"Impactpool Scanner — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Existing (skip): {len(existing_jids)}")

    # Phase 1: Extract all job IDs from listing pages
    all_jobs = await extract_all_jobs()

    # Phase 2: Pre-filter + fetch + save
    saved, skipped, failed = await fetch_and_filter(all_jobs, existing_jids)

    # Summary
    te = time.time() - ts
    all_files = list(OUTPUT_DIR.glob("IMPTPOO_*.md"))
    total_size = sum(f.stat().st_size for f in all_files)
    new_count = len(all_files) - len(existing_jids)

    print("\n" + "=" * 70)
    print(f"SCAN COMPLETE — {te:.1f}s")
    print("=" * 70)
    print(f"Total files: {len(all_files)} ({total_size // 1024}KB)")
    print(f"New this run: {new_count}")
    print(f"Skipped (already existed): {len(existing_jids)}")
    print(f"Fetch results: {saved} saved, {skipped} full-text rejected, {failed} fetch failed")
    tracker.report()

    # Write problem report
    rp = BASE_DIR / "IMPTPOO_PROBLEMS_REPORT.txt"
    lines = [
        f"Impactpool Problem Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Time: {te:.1f}s | Total files: {len(all_files)} | New: {new_count} | "
        f"Skipped: {len(existing_jids)} | Size: {total_size // 1024}KB",
        f"Jobs found in listings: {len(all_jobs)}",
        f"Fetch: {saved}s/{skipped}k/{failed}f",
        f"Problems: {len(tracker.problems)}",
        f"Categories: {dict(tracker.stats)}",
        "", "Issues:"
    ]
    for p in tracker.problems:
        s = f" [{p['jid']}]" if p['jid'] else ""
        lines.append(f"  [{p['category']}]{s} {p['detail']}")
    rp.write_text("\n".join(lines), "utf-8")
    print(f"\nReport: {rp}")

if __name__ == "__main__":
    asyncio.run(main())
