# Scrapling CSS Selector Gotchas

## `css('::attr(href)')` returns `Selectors`, NOT string

```python
# WRONG — returns Selectors object, .replace() will crash with AttributeError
href = a.css('::attr(href)')
path = href.replace('https://untalent.org', '')  # AttributeError: 'Selectors' object has no attribute 'replace'

# CORRECT — call .get() to extract the string value
href = a.css('::attr(href)').get() or ''
path = href.replace('https://untalent.org', '')
```

Same applies to `css('::text')` — always use `.get()` for single values, `.getall()` for lists.

## Pattern reference

| What you want | Wrong | Right |
|---|---|---|
| Single attribute as string | `a.css('::attr(href)')` | `a.css('::attr(href)').get()` |
| Single text node | `a.css('::text')` | `a.css('::text').get()` |
| All matching attributes | `a.css('a::attr(href)')` | `a.css('a::attr(href)').getall()` |
| All text nodes | `a.css('a::text')` | `a.css('a::text').getall()` |

## Discovered in
- Session: 2026-05-31, run_scan.py line 87 `extract_slugs()` function
- Crash: `AttributeError: 'Selectors' object has no attribute 'replace'`
