# Impactpool.org Scraping Patterns (v3.2)

## Site Characteristics
- **No Cloudflare** — clean 200 responses, no solve_cloudflare needed
- **Standard HTML pagination** — `&page=N&per_page=40` query params
- **Job URLs** — `/jobs/NUMBER` (5-8 digit numeric IDs)
- **Server can be slow** — 60-100s response times observed; this is server-side
- **Domain** — `www.impactpool.org` (keep www)

## URL Structure
```
https://www.impactpool.org/search?q=&jf[]=77&jf[]=64&jf[]=104&jf[]=860&jf[]=135&jf[]=667&jf[]=105&page={N}&per_page=40
```
The `jf[]` params are pre-filter job function IDs set by the user. Pass them through from the input URL.

## Extraction Pattern
```python
# From listing page HTML
job_links = list(dict.fromkeys(
    re.findall(r'href="(/jobs/(\d{5,8}))"', page.html_content or "")
))
# Stop when fewer than 40 results returned
if len(job_links) < 40:
    break  # last page
```

## Title Extraction
```python
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
        titles[jid] = max(text_parts, key=len)  # longest = most descriptive
```

## File Naming
```
IMPTPOO_{jid}_{sanitized_title[:50]}.md
```

## JD Fetch Settings
- `headless=True, disable_resources=True, wait=2500`
- `solve_cloudflare=False` (wastes time, no CF on impactpool)
- 4 concurrent max
- Expected avg fetch: ~50s (server-side slowness)

## Problem Categories (Impactpool-specific prefix: `IMP_`)
- `IMP_TITLE_FAIL` — title didn't match ICT keywords
- `IMP_FULL_FAIL` — passed title, failed full-text filter
- `IMP_JD_SLOW` — fetch >20s (common on impactpool, server-side)
- `IMP_JD_STUB` — file <500 bytes
- `IMP_JD_ERR` — exception during fetch

## Session Result (2026-05-31)
- 1694 jobs found across 43 pages
- 88 passed title pre-filter, 87 saved (1 full-text reject)
- 0 fetch failures
- Total scan time: 304s
- Output: 87 files, 2024KB in ~/Downloads/TEST/IMPTPOO/
