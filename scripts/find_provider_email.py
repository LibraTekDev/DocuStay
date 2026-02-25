"""
Find contact email for a utility provider by searching the web and extracting emails from result pages.

Works for any provider type: electric, gas, water, internet. Only needs provider name and optional state.

Flow:
  1. Search for "[provider name] [state] contact email" via Brave Search API.
  2. Fetch up to N result URLs (HTML).
  3. Extract strings that look like email addresses (regex).
  4. Filter out junk (noreply@, example.com, etc.) and return the best candidate(s).

Usage:
  Set one of these in .env:
    BRAVE_SEARCH_API_KEY  – get key at https://api.search.brave.com/ (dashboard may be at api-dashboard.search.brave.com; if that domain doesn't load (DNS_PROBE_FINISHED_NXDOMAIN), try another network or use SERPAPI_KEY instead).
    SERPAPI_KEY           – alternative: get key at https://serpapi.com/ (Google search results).
  Then:
    python scripts/find_provider_email.py "Pacific Gas and Electric" CA
    python scripts/find_provider_email.py "City of Austin Utilities" TX
    python scripts/find_provider_email.py "Comcast" ""
    echo "Duke Energy,NC" | python scripts/find_provider_email.py --csv   # read from stdin "name,state"

Output: one or more candidate emails (best first), or "No email found".

Rate limits: Brave gives ~1,000 free web searches/month ($5 monthly credits). Each provider = 1 search + a few HTTP fetches (no API cost for fetches).

Note: Bing Web Search API was retired Aug 2025; Brave Search API is the replacement used here.
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Optional: load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

# Email regex (simple, good enough for contact pages)
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

# Domains/localparts we treat as non-contact (exclude)
SKIP_EMAIL_PATTERNS = re.compile(
    r"noreply|no-reply|donotreply|do-not-reply|"
    r"example\.com|@.*\.(png|jpg|jpeg|gif|svg|woff2?)(\s|$)|"
    r"@2x\.|wixpress|schema\.org|sentry\.io|"
    r"gravatar|facebook\.com|twitter\.com|linkedin\.com|youtube\.com|"
    r"w3\.org|googleapis|gstatic|google\.com|microsoft\.com|"
    r"placeholder|test@|user@|admin@(?!.*\.(gov|org))",
    re.I
)

# Prefer these local-parts as likely contact addresses (score higher)
PREFER_LOCAL = re.compile(
    r"^(contact|info|customerservice|customercare|support|"
    r"customer\.service|utility|authority|consumer)",
    re.I
)


def search_brave(query: str, api_key: str, count: int = 5) -> list[str]:
    """Return list of URLs from Brave Web Search (up to count)."""
    import httpx
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"X-Subscription-Token": api_key}
    params = {"q": query, "count": min(count, 20)}
    try:
        r = httpx.get(url, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        urls = []
        for item in data.get("web", {}).get("results", []):
            u = item.get("url")
            if u and u.startswith("http"):
                urls.append(u)
        return urls[:count]
    except Exception as e:
        print(f"Brave search error: {e}", file=sys.stderr)
        return []


def search_serpapi(query: str, api_key: str, count: int = 5) -> list[str]:
    """Return list of URLs from SerpApi (Google search). Use if Brave dashboard is unreachable."""
    import httpx
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "api_key": api_key, "num": min(count, 10)}
    try:
        r = httpx.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        urls = []
        for item in data.get("organic_results", []):
            u = item.get("link")
            if u and u.startswith("http"):
                urls.append(u)
        return urls[:count]
    except Exception as e:
        print(f"SerpApi search error: {e}", file=sys.stderr)
        return []


def fetch_page_text(url: str, max_chars: int = 200_000) -> str:
    """Fetch URL and return body as plain text (strip tags roughly)."""
    import httpx
    try:
        r = httpx.get(
            url,
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "DocuStay-ContactLookup/1.0"}
        )
        r.raise_for_status()
        html = r.text
        if len(html) > max_chars:
            html = html[:max_chars]
        # Remove script/style to reduce noise
        html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
        html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text
    except Exception as e:
        print(f"Fetch error {url}: {e}", file=sys.stderr)
        return ""


def extract_emails_from_text(text: str) -> list[str]:
    """Return list of candidate emails found in text, deduped, filtered."""
    found = set()
    for m in EMAIL_RE.finditer(text):
        email = m.group(0).strip().lower()
        if len(email) > 254:
            continue
        if SKIP_EMAIL_PATTERNS.search(email):
            continue
        # Skip if it looks like an image path or query param
        if "/" in email or "?" in email or "=" in email:
            continue
        found.add(email)
    return list(found)


def score_email(email: str) -> int:
    """Higher = better candidate for contact."""
    local = email.split("@")[0] if "@" in email else ""
    score = 0
    if PREFER_LOCAL.match(local):
        score += 10
    # Prefer .gov / .org for utilities
    if email.endswith(".gov") or email.endswith(".org"):
        score += 5
    return score


def find_emails_for_provider(
    provider_name: str,
    state: str | None,
    search_fn: callable,
    search_key: str,
    serpapi_key: str | None = None,
) -> list[str]:
    """Search web for provider contact, fetch result pages, extract and rank emails."""
    state = (state or "").strip().upper()
    name = (provider_name or "").strip()
    if not name:
        return []
    # When using SerpApi, try app module (snippet extraction) first; no page fetches
    if serpapi_key:
        try:
            from app.services.provider_contact_search import find_provider_emails_serpapi
            emails = find_provider_emails_serpapi(name, state or None, serpapi_key)
            if emails:
                return emails
        except ImportError:
            pass
    query = f'"{name}"'
    if state:
        query += f" {state}"
    query += " contact email"
    urls = search_fn(query, search_key, count=4)
    if not urls:
        return []
    all_emails: list[tuple[str, int]] = []  # (email, score)
    seen = set()
    for u in urls:
        text = fetch_page_text(u)
        for e in extract_emails_from_text(text):
            if e not in seen:
                seen.add(e)
                all_emails.append((e, score_email(e)))
    all_emails.sort(key=lambda x: -x[1])
    return [e for e, _ in all_emails]


def main() -> None:
    ap = argparse.ArgumentParser(description="Find provider contact email via web search + page scrape.")
    ap.add_argument("provider_name", nargs="?", help="Provider name (e.g. 'Pacific Gas and Electric')")
    ap.add_argument("state", nargs="?", help="State code (e.g. CA)")
    ap.add_argument("--csv", action="store_true", help="Read stdin as CSV lines: provider_name,state")
    args = ap.parse_args()
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    serp_key = os.environ.get("SERPAPI_KEY", "").strip()
    if brave_key:
        search_fn, search_key = search_brave, brave_key
    elif serp_key:
        search_fn, search_key = search_serpapi, serp_key
    else:
        print(
            "Set one of these in .env:\n"
            "  BRAVE_SEARCH_API_KEY - https://api.search.brave.com/ (if dashboard doesn't load, try SERPAPI_KEY)\n"
            "  SERPAPI_KEY          - https://serpapi.com/ (Google search, works when Brave is unreachable)",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.csv:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip().strip('"') for p in line.split(",", 1)]
            name = parts[0] if parts else ""
            state = parts[1] if len(parts) > 1 else ""
            emails = find_emails_for_provider(
                name, state or None, search_fn, search_key,
                serpapi_key=serp_key if serp_key else None,
            )
            out = emails[0] if emails else "No email found"
            print(f"{name},{state},{out}")
        return
    if not args.provider_name:
        ap.print_help()
        sys.exit(0)
    emails = find_emails_for_provider(
        args.provider_name, args.state, search_fn, search_key,
        serpapi_key=serp_key if serp_key else None,
    )
    if not emails:
        print("No email found")
        return
    for e in emails:
        print(e)


if __name__ == "__main__":
    main()
