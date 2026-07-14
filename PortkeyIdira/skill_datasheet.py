"""Skill 1: Datasheet Download

从 PANW 官方网站搜索并下载产品 datasheet。
优先下载中文版，没有中文则下载英文版。
"""

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, quote_plus

import httpx
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data" / "datasheets"
MANIFEST_PATH = DATA_DIR / "manifest.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PANW_SEARCH_BASE = "https://www.paloaltonetworks.com"
PANW_SEARCH_CN = "https://www.paloaltonetworks.cn"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "search_datasheet",
        "description": (
            "Search and download PANW product datasheets from the official website. "
            "Prioritizes Chinese (zh-CN) version; falls back to English. "
            "Use this when a user asks for a product datasheet, spec sheet, or product overview PDF."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Product name or keyword to search for (e.g., 'PA-450', 'Cortex XDR', 'Prisma Access')",
                },
            },
            "required": ["query"],
        },
    },
}


def _load_manifest() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"datasheets": {}}


def _save_manifest(manifest: dict):
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def _search_google(query: str, client: httpx.Client) -> list[dict]:
    """Use Google search to find PANW datasheet PDFs."""
    results = []
    search_queries = [
        f"site:paloaltonetworks.com filetype:pdf {query} datasheet",
        f"site:paloaltonetworks.cn filetype:pdf {query}",
        f"site:paloaltonetworks.com filetype:pdf {query}",
    ]
    for sq in search_queries:
        try:
            url = f"https://www.google.com/search?q={quote_plus(sq)}&num=10"
            resp = client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/url?q=" in href:
                    real_url = href.split("/url?q=")[1].split("&")[0]
                    if "paloaltonetworks" in real_url and ".pdf" in real_url:
                        from urllib.parse import unquote
                        real_url = unquote(real_url)
                        title = a.get_text(strip=True) or Path(real_url).stem
                        if real_url not in [r["url"] for r in results]:
                            results.append({"title": title, "url": real_url})
        except Exception:
            continue
        if results:
            break
    return results


def _search_panw_direct(query: str, client: httpx.Client) -> list[dict]:
    """Try common PANW datasheet/content URL patterns."""
    slug = re.sub(r"[^\w-]", "-", query.lower()).strip("-")
    candidates = [
        f"{PANW_SEARCH_BASE}/content/dam/pan/en_US/assets/pdf/datasheets/{slug}.pdf",
        f"{PANW_SEARCH_BASE}/content/dam/pan/en_US/assets/pdf/datasheets/{slug}-datasheet.pdf",
        f"{PANW_SEARCH_CN}/content/dam/pan/zh_CN/assets/pdf/datasheets/{slug}.pdf",
        f"{PANW_SEARCH_BASE}/resources/datasheets/{slug}",
    ]
    results = []
    for url in candidates:
        try:
            resp = client.head(url, follow_redirects=True, timeout=10)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                if "pdf" in ct or url.endswith(".pdf"):
                    results.append({"title": query, "url": url})
        except Exception:
            continue
    return results


def _download_pdf(url: str, client: httpx.Client) -> tuple[bytes | None, str]:
    """Download PDF content. Returns (bytes, content_type)."""
    try:
        with client.stream("GET", url, follow_redirects=True) as r:
            if r.status_code != 200:
                return None, ""
            ct = r.headers.get("content-type", "")
            chunks = []
            for chunk in r.iter_bytes(8192):
                chunks.append(chunk)
            return b"".join(chunks), ct
    except Exception:
        return None, ""


async def handle(arguments: dict) -> str:
    """Execute the datasheet search skill."""
    query = arguments.get("query", "").strip()
    if not query:
        return "Please provide a product name or keyword to search for datasheets."

    manifest = _load_manifest()

    # Check if we already have it cached
    cache_key = query.lower()
    if cache_key in manifest["datasheets"]:
        entry = manifest["datasheets"][cache_key]
        return (
            f"Found cached datasheet:\n"
            f"- Title: {entry['title']}\n"
            f"- Language: {entry['language']}\n"
            f"- File: {entry['filename']}\n"
            f"- Download: /api/download/datasheet/{entry['filename']}\n"
            f"- Source: {entry['url']}"
        )

    with httpx.Client(headers=HEADERS, timeout=30) as client:
        # Priority 1: Direct URL patterns (fastest)
        results_direct = _search_panw_direct(query, client)

        # Priority 2: Google search for PANW PDFs
        results_google = _search_google(query, client)

        # Combine, deduplicate
        seen = set()
        all_results = []
        for r in results_direct + results_google:
            if r["url"] not in seen:
                seen.add(r["url"])
                all_results.append(r)

        # Try downloading each result
        downloaded = None
        lang = "en"
        for r in all_results:
            content, ct = _download_pdf(r["url"], client)
            if content and (b"%PDF" in content[:10] or "pdf" in ct):
                downloaded = (r, content)
                if "zh_CN" in r["url"] or ".cn" in r["url"]:
                    lang = "zh-CN"
                break

        if not downloaded:
            return (
                f"Could not find a downloadable datasheet for '{query}'. "
                f"Searched {len(all_results)} results from Google and direct URL patterns. "
                f"You can try a more specific product name (e.g., 'PA-5450' instead of 'PA')."
            )

        info, content = downloaded
        file_hash = hashlib.md5(content).hexdigest()[:8]
        safe_name = re.sub(r"[^\w-]", "-", query.lower())[:60]
        filename = f"{safe_name}-{lang}-{file_hash}.pdf"

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / filename).write_bytes(content)

        entry = {
            "title": info["title"],
            "url": info["url"],
            "filename": filename,
            "language": lang,
            "size_bytes": len(content),
            "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        manifest["datasheets"][cache_key] = entry
        _save_manifest(manifest)

        return (
            f"Datasheet downloaded successfully:\n"
            f"- Title: {info['title']}\n"
            f"- Language: {'中文' if lang == 'zh-CN' else 'English'}\n"
            f"- Size: {len(content) / 1024:.1f} KB\n"
            f"- Download: /api/download/datasheet/{filename}\n"
            f"- Source: {info['url']}"
        )
