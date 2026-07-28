#!/usr/bin/env python3
"""
================================================================================
UNIFIED SCANNER v4.0 — UNTalent.org + UNJobNet.org + Impactpool.org
================================================================================
Scrapes ICT/AI/digital/telecom/innovation vacancies from all 3 aggregator
sites using Scrapling StealthyFetcher. Two-stage pre-filtering. Skips existing
files. Removes expired JDs before scanning.

PIPELINE:
  Phase 0 : Load existing files, remove expired JDs (deadline passed)
  Phase A1: UNTalent.org  — paginate /jobs?page=N, CF challenge
  Phase A2: UNJobNet.org  — paginate by occupation IDs, no CF
  Phase A3: Impactpool.org — paginate search URL, no CF

Usage: python3 run_scan.py [/output/path]

Pre-written for DeepSeek V4 Flash. DS4: do NOT modify. Just run and report.
================================================================================
"""
import asyncio, re, sys, time
from collections import Counter
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from scrapling.fetchers import StealthyFetcher

# ── CONFIG ──────────────────────────────────────────────────────────────────
BASE_DIR = Path("~/Downloads/DATA_REPOSITORY/JOBS-RAW-EXTRACT")
UNTALENT_DIR = BASE_DIR / "UNTALENT"
UNJN_DIR      = BASE_DIR / "UNjobsnet"
IMPTPOO_DIR   = BASE_DIR / "impactpool"
CONCURRENT    = 4
MAX_UNTALENT_PAGES = 8
IMPPT_PER_PAGE = 40
IMPPT_MAX_PAGES = 50

# Impactpool pre-filter job-function IDs
IMPPT_JF_PARAMS = (
    "q=&jf%5B%5D=77&jf%5B%5D=64&jf%5B%5D=104&jf%5B%5D=860"
    "&jf%5B%5D=135&jf%5B%5D=667&jf%5B%5D=105"
)
IMPPT_SEARCH_BASE = f"https://www.impactpool.org/search?{IMPPT_JF_PARAMS}"

# UNJobNet occupation IDs
UNJN_OCCUPATIONS = {6: "ICT", 70: "Innovation", 16: "Research",
                    28: "Engineering", 71: "FinTech", 25: "DocInfo"}

# ── PROBLEM TRACKER ─────────────────────────────────────────────────────────
class ProblemTracker:
    def __init__(self):
        self.problems = []
        self.stats = Counter()
    def log(self, cat, det, key=None):
        self.problems.append({"category": cat, "detail": det, "key": key})
        self.stats[cat] += 1
    def report(self):
        if not self.problems:
            print("\n  ✅ No problems.")
            return
        print(f"\n  ⚠️  PROBLEMS ({len(self.problems)}):")
        for cat, count in self.stats.most_common():
            print(f"    {cat}: {count}")

tracker = ProblemTracker()

# ── KEYWORDS (FULL list) ──────────────────────────────────────────────────
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

# ── PHASE 0 — CLEAN EXPIRED JDs ─────────────────────────────────────────────
DEADLINE_PATTERN = re.compile(
    r'(?:closing|deadline|application\s+deadline|closing\s+on)\s*[:\s]\s*'
    r'(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4})', re.I)

MONTHS = {
    'jan': 1,'january': 1,'feb': 2,'february': 2,'mar': 3,'march': 3,
    'apr': 4,'april': 4,'may': 5,'jun': 6,'june': 6,
    'jul': 7,'july': 7,'aug': 8,'august': 8,'sep': 9,'sept': 9,'september': 9,
    'oct': 10,'october': 10,'nov': 11,'november': 11,'dec': 12,'december': 12,
}

def parse_deadline(text):
    m = DEADLINE_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1)
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        pass
    parts = raw.split()
    if len(parts) == 3:
        try:
            day = int(parts[0])
            month = MONTHS.get(parts[1].lower(), 0)
            year = int(parts[2])
            if month:
                return date(year, month, day)
        except (ValueError, IndexError):
            pass
    return None

def clean_expired_dirs():
    print("=" * 70)
    print("PHASE 0 — Clean expired JDs")
    print("=" * 70)
    today = date.today()
    total_removed = 0
    for dirlabel, dirpath in [("UNTALENT", UNTALENT_DIR),
                                ("UNJN", UNJN_DIR),
                                ("IMPTPOO", IMPTPOO_DIR)]:
        if not dirpath.exists():
            print(f"  {dirlabel}: dir does not exist, skip")
            continue
        removed = 0
        kept_no_date = 0
        for f in dirpath.glob("*.md"):
            try:
                content = f.read_text("utf-8", errors="ignore")
            except Exception:
                continue
            dl = parse_deadline(content)
            if dl is None:
                kept_no_date += 1
            elif dl < today:
                f.unlink()
                removed += 1
        total_removed += removed
        remaining = len(list(dirpath.glob("*.md")))
        print(f"  {dirlabel}: removed {removed} expired, {remaining} remaining ({kept_no_date} no-deadline)")
    print(f"  Total expired removed: {total_removed}")
    return total_removed

# ── EXISTING FILE CHECK ─────────────────────────────────────────────────────
def load_existing_ids():
    existing_slugs = set()
    existing_jids  = set()
    existing_imp_ids = set()
    for f in UNTALENT_DIR.glob("UNTALENT_*.md"):
        slug = f.stem[len("UNTALENT_"):]
        if slug:
            existing_slugs.add(slug)
    for f in UNJN_DIR.glob("UNJN_*.md"):
        parts = f.stem.split("_", 2)
        if len(parts) >= 2:
            existing_jids.add(parts[1])
    for f in IMPTPOO_DIR.glob("IP_*.md"):
        parts = f.stem.split("_", 2)
        if len(parts) >= 2:
            existing_imp_ids.add(parts[1])
    return existing_slugs, existing_jids, existing_imp_ids

# ── UNTALENT.ORG ─────────────────────────────────────────────────────────────
def extract_slugs(page):
    slugs = set()
    for h in page.css('a::attr(href)').getall():
        if not h:
            continue
        path = h.replace('https://untalent.org', '').replace('http://untalent.org', '')
        if not path.startswith('/jobs/'):
            continue
        parts = [p for p in path.split('/') if p]
        if len(parts) != 2 or parts[1] in ('search', 'start'):
            continue
        slugs.add(parts[1])
    titles = {}
    for a in page.css('a'):
        href = a.css('::attr(href)').get() or ''
        path = href.replace('https://untalent.org', '')
        parts = [p for p in path.split('/') if p]
        if len(parts) != 2 or parts[1] in ('search', 'start') or parts[1] not in slugs:
            continue
        text = (a.css('::text').get() or '').strip()
        if text and len(text) > 3 and parts[1] not in titles:
            titles[parts[1]] = text
    return slugs, titles

async def run_untalent(existing_slugs=None):
    if existing_slugs is None:
        existing_slugs = set()
    print("\n" + "=" * 70 + "\nPHASE A1 — UNTalent.org\n" + "=" * 70)
    ts = time.time()
    lt = []
    all_slugs = []
    st = {}
    seen = set(existing_slugs)
    skipped_existing = 0
    for pn in range(1, MAX_UNTALENT_PAGES + 1):
        t0 = time.time()
        try:
            page = await StealthyFetcher.async_fetch(
                f"https://untalent.org/jobs?page={pn}",
                headless=True, disable_resources=True, wait=2000, solve_cloudflare=True)
        except Exception as e:
            tracker.log("LISTING_ERROR", f"P{pn}:{e}")
            break
        el = time.time() - t0
        lt.append(el)
        if page.status != 200:
            tracker.log("LISTING_!200", f"P{pn}:{page.status}")
            if pn == 1:
                break
            continue
        if el > 10:
            tracker.log("CF_SLOW", f"P{pn}:{el:.1f}s")
        slugs, titles = extract_slugs(page)
        st.update(titles)
        new = []
        already_have = 0
        for s in slugs:
            if s in seen:
                already_have += 1
            else:
                seen.add(s)
                new.append(s)
        all_slugs.extend(new)
        skipped_existing += already_have
        miss = len(new) - sum(1 for s in new if s in titles)
        if miss > 0:
            tracker.log("NO_TITLE", f"P{pn}:{miss}/{len(new)} titles missing")
        print(f"  P{pn}: {len(slugs)} total, {len(new)} new, {already_have} already fetched ({el:.1f}s)")
        if len(slugs) < 20:
            break
    avg = sum(lt) / len(lt) if lt else 0
    print(f"  Pages:{len(lt)} NewSlugs:{len(all_slugs)} SkippedExisting:{skipped_existing} Avg:{avg:.1f}s")
    pre = []
    hr = ir = 0
    for slug in all_slugs:
        p, r = is_ict_title(st.get(slug, slug))
        if p:
            pre.append(slug)
        elif "HARD" in r:
            hr += 1
        else:
            ir += 1
            tracker.log("TITLE_FAIL", r, slug)
    print(f"  Pre-filter: {len(pre)}p {hr}h {ir}i")
    if not pre:
        tracker.log("NO_CANDIDATES", "all rejected")
        return
    print(f"  Fetching {len(pre)} JDs ({CONCURRENT} concurrent)...")
    sem = asyncio.Semaphore(CONCURRENT)
    ft = []
    async def fetch(slug):
        t0 = time.time()
        async with sem:
            try:
                pg = await StealthyFetcher.async_fetch(
                    f"https://untalent.org/jobs/{slug}",
                    headless=True, disable_resources=True, wait=2000, solve_cloudflare=True)
                el = time.time() - t0
                ft.append(el)
                txt = pg.get_all_text() or ""
                title = (pg.css("h1::text").get() or "").strip() or slug
                if pg.status != 200:
                    tracker.log("JD_!200", f"{pg.status} {el:.1f}s", slug)
                elif el > 20:
                    tracker.log("JD_SLOW", f"{el:.1f}s", slug)
                elif len(txt) < 500:
                    tracker.log("JD_STUB", f"{len(txt)}B", slug)
                return slug, pg.status, len(txt), txt, title
            except Exception as e:
                tracker.log("JD_ERR", f"{type(e).__name__}:{e}", slug)
                return slug, 0, 0, f"ERR:{e}", slug
    fs = time.time()
    results = await asyncio.gather(*(fetch(s) for s in pre))
    saved = skipped = failed = 0
    for slug, status, length, text, title in results:
        if status != 200 or length < 500:
            failed += 1
            continue
        if not is_ict_full(title, text):
            skipped += 1
            tracker.log("FULL_FAIL", title[:60], slug)
            continue
        fn = f"UNTALENT_{sanitize(title)}.md"
        (UNTALENT_DIR / fn).write_text(
            f"# {title}\n\nSource: https://untalent.org/jobs/{slug}\n\n{text}", "utf-8")
        if length < 1500:
            tracker.log("SMALL", f"{length}B", slug)
        print(f"  SAVED ({length // 1024}KB): {title[:60]}")
        saved += 1
    a_f = sum(ft) / len(ft) if ft else 0
    print(f"  UNTalent: {saved}s/{skipped}k/{failed}f avg:{a_f:.1f}s total:{time.time() - ts:.1f}s")

# ── UNJOBNET.ORG ─────────────────────────────────────────────────────────────
async def run_unjn(existing_jids=None):
    if existing_jids is None:
        existing_jids = set()
    print("\n" + "=" * 70 + "\nPHASE A2 — UNJobNet.org\n" + "=" * 70)
    ts = time.time()
    lt = []
    all_jobs = []
    seen = set(existing_jids)
    skipped_existing = 0
    for oid, name in UNJN_OCCUPATIONS.items():
        pn = 1
        ct = 0
        while True:
            url = f"https://www.unjobnet.org/jobs?occupations[]={oid}&page={pn}"
            t0 = time.time()
            try:
                pg = await StealthyFetcher.async_fetch(
                    url, headless=True, disable_resources=True, wait=3000)
                lt.append(time.time() - t0)
            except Exception as e:
                tracker.log("UJN_LIST_ERR", f"{name}p{pn}:{e}")
                break
            if pg.status != 200:
                tracker.log("UJN_LIST_!200", f"{name}p{pn}:{pg.status}")
                break
            jids = list(dict.fromkeys(
                re.findall(r"/jobs/detail/(\d{7,8})", pg.html_content or "")))
            if not jids:
                break
            ct += len(jids)
            titles = {}
            for a in pg.css('a[href*="/jobs/detail/"]'):
                h = a.css('::attr(href)').get() or ''
                tx = (a.css('::text').get() or '').strip()
                m = re.search(r"/jobs/detail/(\d{7,8})", h)
                if m and tx and len(tx) > 3:
                    titles[m.group(1)] = tx
            new = []
            already = 0
            if jids:
                for j in jids:
                if j in seen:
                    already += 1
                else:
                    seen.add(j)
                    new.append((j, titles.get(j, str(j))))
                all_jobs.extend(new)
                skipped_existing += already
            if len(jids) < 20:
                break
            pn += 1
            await asyncio.sleep(0.3)
        print(f"  {name}: {ct} total, {len(new)} new, {already} already fetched")
    avg_l = sum(lt) / len(lt) if lt else 0
    print(f"  Unique:{len(all_jobs)} SkippedExisting:{skipped_existing} Avg-list:{avg_l:.1f}s")
    pre = []
    hr = ir = 0
    for jid, title in all_jobs:
        p, r = is_ict_title(title)
        if p:
            pre.append((jid, title))
        elif "HARD" in r:
            hr += 1
        else:
            ir += 1
            tracker.log("UJN_TITLE_FAIL", r, jid)
    print(f"  Pre-filter: {len(pre)}p {hr}h {ir}i")
    if not pre:
        tracker.log("UJN_NO_CANDIDATES", "all rejected")
        return
    print(f"  Fetching {len(pre)} JDs ({CONCURRENT} concurrent)...")
    sem = asyncio.Semaphore(CONCURRENT)
    ft = []
    async def fetch(jid, th):
        t0 = time.time()
        async with sem:
            try:
                pg = await StealthyFetcher.async_fetch(
                    f"https://www.unjobnet.org/jobs/detail/{jid}",
                    headless=True, disable_resources=True, wait=2000)
                el = time.time() - t0
                ft.append(el)
                txt = pg.get_all_text() or ""
                h1 = (pg.css("h1::text").get() or "").strip()
                title = h1 if h1 and len(h1) > 3 else th
                if pg.status != 200:
                    tracker.log("UJN_JD_!200", f"{pg.status}", jid)
                elif len(txt) < 500:
                    tracker.log("UJN_JD_STUB", f"{len(txt)}B", jid)
                return jid, pg.status, len(txt), txt, title
            except Exception as e:
                tracker.log("UJN_JD_ERR", f"{type(e).__name__}:{e}", jid)
                return jid, 0, 0, f"ERR:{e}", th
    results = await asyncio.gather(*(fetch(j, t) for j, t in pre))
    saved = skipped = failed = 0
    for jid, status, length, text, title in results:
        if status != 200 or length < 500:
            failed += 1
            continue
        if not is_ict_full(title, text):
            skipped += 1
            tracker.log("UJN_FULL_FAIL", title[:60], jid)
            continue
        fn = f"UNJN_{jid}_{sanitize(title[:50])}.md"
        (UNJN_DIR / fn).write_text(
            f"# {title}\n\nSource: https://www.unjobnet.org/jobs/detail/{jid}\n\n{text}", "utf-8")
        if length < 1500:
            tracker.log("UJN_SMALL", f"{length}B", jid)
        print(f"  SAVED ({length // 1024}KB): {title[:60]}")
        saved += 1
    a_f = sum(ft) / len(ft) if ft else 0
    print(f"  UNJobNet: {saved}s/{skipped}k/{failed}f avg:{a_f:.1f}s total:{time.time() - ts:.1f}s")

# ── IMPACTPOOL.ORG ───────────────────────────────────────────────────────────
async def run_impactpool(existing_imp_ids=None):
    if existing_imp_ids is None:
        existing_imp_ids = set()
    print("\n" + "=" * 70 + "\nPHASE A3 — Impactpool.org\n" + "=" * 70)
    ts = time.time()
    lt = []
    all_jobs = []
    seen = set(existing_imp_ids)
    skipped_existing = 0
    for pn in range(1, IMPPT_MAX_PAGES + 1):
        url = f"{IMPPT_SEARCH_BASE}&page={pn}&per_page={IMPPT_PER_PAGE}"
        t0 = time.time()
        try:
            page = await StealthyFetcher.async_fetch(
                url, headless=True, disable_resources=True, wait=3000)
        except Exception as e:
            tracker.log("IMPPT_LIST_ERR", f"P{pn}:{e}")
            break
        elapsed = time.time() - t0
        lt.append(elapsed)
        if page.status != 200:
            tracker.log("IMPPT_LIST_!200", f"P{pn}:{page.status}")
            break
        html = page.html_content or ""
        job_links = list(dict.fromkeys(
            re.findall(r'href="(/jobs/(\d{5,8}))"', html)))
        if not job_links:
            print(f"  P{pn}: no job links, stopping")
            break
        titles = {}
        for a in page.css('a[href*="/jobs/"]'):
            href = (a.css('::attr(href)').get() or '').strip()
            m = re.match(r'/jobs/(\d{5,8})(?:\?|/|$)', href)
            if not m:
                continue
            jid = m.group(1)
            texts = []
            for el in a.css('*'):
                t = (el.css('::text').get() or '').strip()
                if t and len(t) > 3:
                    texts.append(t)
            direct = (a.css('::text').get() or '').strip()
            if direct and len(direct) > 3:
                texts.insert(0, direct)
            if texts:
                titles[jid] = max(texts, key=len)
        new_count = 0
        already_count = 0
        for href, jid in job_links:
            if jid in seen:
                already_count += 1
            else:
                seen.add(jid)
                all_jobs.append((jid, titles.get(jid, f"Job {jid}")))
                new_count += 1
        skipped_existing += already_count
        print(f"  P{pn}: {len(job_links)} found, {new_count} new, {len(seen)} total ({elapsed:.1f}s)")
        if len(job_links) < IMPPT_PER_PAGE:
            print(f"  Last page ({len(job_links)} < {IMPPT_PER_PAGE})")
            break
        await asyncio.sleep(0.5)
    avg_l = sum(lt) / len(lt) if lt else 0
    print(f"  Total jobs: {len(all_jobs)} new, {skipped_existing} already existed, avg-list:{avg_l:.1f}s")
    pre = []
    hr = ir = 0
    for jid, title in all_jobs:
        if jid in existing_imp_ids:
            continue
        p, r = is_ict_title(title)
        if p:
            pre.append((jid, title))
        elif "HARD" in r:
            hr += 1
        else:
            ir += 1
            tracker.log("IMPPT_TITLE_FAIL", r, jid)
    print(f"  Pre-filter: {len(pre)}p {hr}h {ir}i")
    if not pre:
        tracker.log("IMPPT_NO_CANDIDATES", "all rejected")
        return
    print(f"  Fetching {len(pre)} JDs ({CONCURRENT} concurrent)...")
    sem = asyncio.Semaphore(CONCURRENT)
    ft = []
    async def fetch(jid, th):
        t0 = time.time()
        async with sem:
            try:
                pg = await StealthyFetcher.async_fetch(
                    f"https://www.impactpool.org/jobs/{jid}",
                    headless=True, disable_resources=True, wait=2500)
                el = time.time() - t0
                ft.append(el)
                txt = pg.get_all_text() or ""
                h1 = (pg.css("h1::text").get() or "").strip()
                title = h1 if h1 and len(h1) > 3 else th
                if pg.status != 200:
                    tracker.log("IMPPT_JD_!200", f"{pg.status}", jid)
                elif el > 20:
                    tracker.log("IMPPT_JD_SLOW", f"{el:.1f}s", jid)
                elif len(txt) < 500:
                    tracker.log("IMPPT_JD_STUB", f"{len(txt)}B", jid)
                return jid, pg.status, len(txt), txt, title
            except Exception as e:
                tracker.log("IMPPT_JD_ERR", f"{type(e).__name__}:{e}", jid)
                return jid, 0, 0, f"ERR:{e}", th
    results = await asyncio.gather(*(fetch(j, t) for j, t in pre))
    saved = skipped = failed = 0
    for jid, status, length, text, title in results:
        if status != 200 or length < 500:
            failed += 1
            continue
        if not is_ict_full(title, text):
            skipped += 1
            tracker.log("IMPPT_FULL_FAIL", title[:60], jid)
            continue
        fn = f"IP_{jid}_{sanitize(title[:50])}.md"
        (IMPTPOO_DIR / fn).write_text(
            f"# {title}\n\nSource: https://www.impactpool.org/jobs/{jid}\n\n{text}", "utf-8")
        if length < 1500:
            tracker.log("IMPPT_SMALL", f"{length}B", jid)
        print(f"  SAVED ({length // 1024}KB): {title[:60]}")
        saved += 1
    a_f = sum(ft) / len(ft) if ft else 0
    print(f"  Impactpool: {saved}s/{skipped}k/{failed}f avg:{a_f:.1f}s total:{time.time() - ts:.1f}s")

# ── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    UNTALENT_DIR.mkdir(parents=True, exist_ok=True)
    UNJN_DIR.mkdir(parents=True, exist_ok=True)
    IMPTPOO_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.time()

    print(f"Unified Scanner v4.0 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Output base: {BASE_DIR}")

    # Phase 0: Clean expired
    expired_removed = clean_expired_dirs()

    # Load existing IDs
    existing_slugs, existing_jids, existing_imp_ids = load_existing_ids()
    print(f"\nExisting (skip): {len(existing_slugs)} UNTalent, {len(existing_jids)} UNJobNet, {len(existing_imp_ids)} Impactpool")

    # Phase A: Scrape all 3 sites
    await run_untalent(existing_slugs)
    await run_unjn(existing_jids)
    await run_impactpool(existing_imp_ids)

    # Summary
    te = time.time() - ts
    uf = list(UNTALENT_DIR.glob("UNTALENT_*.md"))
    jf = list(UNJN_DIR.glob("UNJN_*.md"))
    pf = list(IMPTPOO_DIR.glob("IP_*.md"))
    sz = sum(f.stat().st_size for f in uf + jf + pf)
    new_u = len(uf) - len(existing_slugs)
    new_j = len(jf) - len(existing_jids)
    new_p = len(pf) - len(existing_imp_ids)

    print("\n" + "=" * 70)
    print(f"SCAN COMPLETE — {te:.1f}s")
    print("=" * 70)
    print(f"Total files: {len(uf)}U + {len(jf)}J + {len(pf)}P = {len(uf)+len(jf)+len(pf)} ({sz//1024}KB)")
    print(f"New this run: {new_u}U + {new_j}J + {new_p}P = {new_u+new_j+new_p}")
    print(f"Expired removed: {expired_removed}")
    print(f"Skipped (already existed): {len(existing_slugs)}U + {len(existing_jids)}J + {len(existing_imp_ids)}P")
    tracker.report()

    # Write problem report
    rp = BASE_DIR / "SCAN_PROBLEMS_REPORT.txt"
    lines = [
        f"Unified Scanner v4.0 Problem Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Time: {te:.1f}s | Total: {len(uf)+len(jf)+len(pf)} | New: {new_u+new_j+new_p} | "
        f"Expired removed: {expired_removed} | Skipped: {len(existing_slugs)+len(existing_jids)+len(existing_imp_ids)} | "
        f"Size: {sz//1024}KB",
        f"Files: {len(uf)} UNTalent, {len(jf)} UNJobNet, {len(pf)} Impactpool",
        f"Problems: {len(tracker.problems)}",
        f"Categories: {dict(tracker.stats)}",
        "", "Issues:"
    ]
    for p in tracker.problems:
        s = f" [{p['key']}]" if p['key'] else ""
        lines.append(f"  [{p['category']}]{s} {p['detail']}")
    rp.write_text("\n".join(lines), "utf-8")
    print(f"\nReport: {rp}")

if __name__ == "__main__":
    asyncio.run(main())
