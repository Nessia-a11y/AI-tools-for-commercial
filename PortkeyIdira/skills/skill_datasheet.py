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


def _search_panw_page(query: str, base_url: str, client: httpx.Client) -> list[dict]:
    """Search a PANW site for PDF links matching query."""
    search_url = f"{base_url}/resources/datasheets"
    results = []
    try:
        resp = client.get(search_url, follow_redirects=True)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        query_lower = query.lower()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True).lower()
            if query_lower in text or query_lower in href.lower():
                if href.endswith(".pdf") or "/datasheets/" in href:
                    full_url = urljoin(base_url, href)
                    title = a.get_text(strip=True) or Path(href).stem
                    results.append({"title": title, "url": full_url})
    except Exception:
        pass
    return results


def _search_direct_datasheet_url(query: str, client: httpx.Client) -> list[dict]:
    """Try common PANW datasheet URL patterns."""
    slug = re.sub(r"[^\w-]", "-", query.lower()).strip("-")
    candidates = [
        f"{PANW_SEARCH_CN}/resources/datasheets/{slug}",
        f"{PANW_SEARCH_BASE}/resources/datasheets/{slug}",
        f"{PANW_SEARCH_BASE}/resources/datasheets/{slug}.pdf",
    ]
    results = []
    for url in candidates:
        try:
            resp = client.head(url, follow_redirects=True)
            if resp.status_code == 200:
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

    results_cn = []
    results_en = []

    with httpx.Client(headers=HEADERS, timeout=30) as client:
        # Priority 1: Chinese site
        results_cn = _search_panw_page(query, PANW_SEARCH_CN, client)
        results_cn += _search_direct_datasheet_url(query, client)

        # Priority 2: English site
        results_en = _search_panw_page(query, PANW_SEARCH_BASE, client)
        results_en += _search_direct_datasheet_url(query, client)

        # Try Chinese first
        downloaded = None
        lang = "zh-CN"
        for r in results_cn:
            content, ct = _download_pdf(r["url"], client)
            if content and (b"%PDF" in content[:10] or "pdf" in ct):
                downloaded = (r, content)
                break

        # Fallback to English
        if not downloaded:
            lang = "en"
            for r in results_en:
                content, ct = _download_pdf(r["url"], client)
                if content and (b"%PDF" in content[:10] or "pdf" in ct):
                    downloaded = (r, content)
                    break

        if not downloaded:
            return (
                f"Could not find a downloadable datasheet for '{query}'. "
                f"Searched {len(results_cn)} Chinese and {len(results_en)} English results. "
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
