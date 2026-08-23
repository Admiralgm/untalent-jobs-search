# Scrapling vs browser_navigate Benchmark (2026-05-31)

## Test setup
- 5 Impactpool job detail pages (IDs: 1216615, 1211567, 1213911, 1211939, 1215916)
- MacBook Air M4, 16GB RAM, macOS Sequoia
- All methods returned full JDs (22K-38K chars each)

## Results

| Method | Total time | Per job | Concurrent? | All JDs full? |
|--------|-----------|---------|-------------|----------------|
| browser_navigate (sequential) | ~60-100s | 3-5s | No | Yes |
| DynamicSession (sequential) | 13.6s | 2.7s | No | Yes |
| StealthyFetcher async_fetch (concurrent) | 7.2s | 1.4s | Yes (5 parallel) | Yes |

**Speedup: 10-14x vs browser_navigate**

## Key findings
- StealthyFetcher with asyncio.gather runs all fetches truly concurrently
- Content quality identical to browser_navigate -- full raw JDs, not stubs
- RAM: 5 concurrent instances ~1.5-2GB. 8 concurrent ~2.5-3.2GB. Safe on 16GB up to 8.
- UNTalent: StealthyFetcher required (Cloudflare blocks curl and DynamicFetcher)

## Scrapling API (v0.4.7 verified on macOS)
- Import: from scrapling.fetchers import StealthyFetcher
- Async: await StealthyFetcher.async_fetch(url, headless=True, disable_resources=True, wait=2000)
- Response: use .status, .get_all_text(), .html_content -- NOT .text (may be None)
- Title: page.css('h1::text').get()
- Playwright Chromium: config/home/Library/Caches/ms-playwright/chromium-1208/
- Install: python3 -m playwright install chromium
