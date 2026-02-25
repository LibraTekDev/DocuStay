"""
One-off test: call SerpApi for "BURKWOOD TREATMENT CENTER" contact email and print
raw response (snippets) and extracted emails. Requires SERPAPI_KEY in .env.
"""
import json
import os
from pathlib import Path

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

def main():
    api_key = (os.environ.get("SERPAPI_KEY") or "").strip()
    if not api_key:
        print("SERPAPI_KEY not set in .env. Add your key and run again.")
        return
    query = '"BURKWOOD TREATMENT CENTER" contact email'
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "api_key": api_key, "num": 10}
    print(f"Calling SerpApi: GET {url}")
    print(f"Query: {query!r}\n")
    import httpx
    r = httpx.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    # Summary from response
    meta = data.get("search_metadata") or {}
    print("--- search_metadata ---")
    print(f"  status: {meta.get('status')}")
    print(f"  total_time_taken: {meta.get('total_time_taken')}")
    print(f"  google_url: {meta.get('google_url', '')[:80]}...")
    # Related questions (snippets)
    rq = data.get("related_questions") or []
    print(f"\n--- related_questions ({len(rq)} items) ---")
    for i, item in enumerate(rq[:5]):
        sn = (item.get("snippet") or "")[:200]
        print(f"  [{i}] snippet: {sn!r}...")
    # Organic results (snippets)
    org = data.get("organic_results") or []
    print(f"\n--- organic_results ({len(org)} items) ---")
    for i, item in enumerate(org[:8]):
        link = item.get("link", "")
        sn = (item.get("snippet") or "")[:200]
        print(f"  [{i}] {link[:60]}...")
        print(f"      snippet: {sn!r}")
    # Extracted emails via app module
    print("\n--- Extracted emails (app extract_emails_from_serpapi_response) ---")
    from app.services.provider_contact_search import extract_emails_from_serpapi_response
    emails = extract_emails_from_serpapi_response(data)
    print(f"  Count: {len(emails)}")
    for e in emails:
        print(f"  - {e}")
    if not emails:
        print("  (none)")

if __name__ == "__main__":
    main()
