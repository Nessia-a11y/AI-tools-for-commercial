"""Skill 5: TechDocs & Deployment Documentation

查询官方 TechDocs 和内部部署文档库。
用于 PANW 产品部署相关问题。
- 官方文档：从 docs.paloaltonetworks.com 搜索
- 内部文档：存放在 data/techdocs/ 目录中，管理员维护
"""

import json
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data" / "techdocs"
INTERNAL_DOCS_PATH = DATA_DIR / "internal_docs.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TECHDOCS_BASE = "https://docs.paloaltonetworks.com"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "query_techdocs",
        "description": (
            "Search PANW official TechDocs (docs.paloaltonetworks.com) and internal deployment documentation. "
            "Use this when a user asks about product deployment, configuration, troubleshooting, "
            "best practices, or any technical documentation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Deployment or technical question (e.g., 'PAN-OS 11.1 upgrade steps', 'Prisma Access GlobalProtect setup')",
                },
                "product": {
                    "type": "string",
                    "enum": ["panos", "panorama", "prisma-access", "prisma-cloud", "cortex-xdr", "cortex-xsiam", "cortex-xsoar", "cn-series", "vm-series", "all"],
                    "description": "Filter by product area",
                },
            },
            "required": ["query"],
        },
    },
}


def _load_internal_docs() -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if INTERNAL_DOCS_PATH.exists():
        return json.loads(INTERNAL_DOCS_PATH.read_text()).get("documents", [])
    return []


def _save_internal_docs(docs: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INTERNAL_DOCS_PATH.write_text(json.dumps({"documents": docs}, indent=2, ensure_ascii=False))


def add_internal_doc(title: str, content: str, product: str, tags: list[str] = None) -> dict:
    """Admin: add or update an internal deployment document. Same title will be replaced."""
    docs = _load_internal_docs()
    # Remove existing entry with same title (upsert)
    docs = [d for d in docs if d["title"] != title]
    entry = {
        "title": title,
        "content": content,
        "product": product,
        "tags": tags or [],
    }
    docs.append(entry)
    _save_internal_docs(docs)
    return entry


def remove_internal_doc(title: str) -> bool:
    """Admin: remove an internal doc by title."""
    docs = _load_internal_docs()
    new_docs = [d for d in docs if d["title"] != title]
    if len(new_docs) == len(docs):
        return False
    _save_internal_docs(new_docs)
    return True


def _search_official_techdocs(query: str, product: str, client: httpx.Client) -> list[dict]:
    """Search docs.paloaltonetworks.com."""
    results = []
    search_url = f"{TECHDOCS_BASE}/search#q={query}"
    if product and product != "all":
        search_url += f"&product={product}"

    try:
        resp = client.get(f"{TECHDOCS_BASE}/search", params={"q": query}, follow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.find_all("a", href=True)[:20]:
                href = item["href"]
                text = item.get_text(strip=True)
                if text and "/docs/" in href or "techdocs" in href:
                    full_url = href if href.startswith("http") else f"{TECHDOCS_BASE}{href}"
                    results.append({"title": text, "url": full_url})
    except Exception:
        pass

    return results[:10]


def _search_internal_docs(query: str, product: str) -> list[dict]:
    """Search internal documentation library."""
    docs = _load_internal_docs()
    query_lower = query.lower()
    keywords = query_lower.split()

    matches = []
    for doc in docs:
        if product and product != "all" and doc.get("product", "").lower() != product:
            continue
        searchable = f"{doc['title']} {doc.get('content', '')} {' '.join(doc.get('tags', []))}".lower()
        if query_lower in searchable or any(kw in searchable for kw in keywords):
            matches.append(doc)

    return matches


async def handle(arguments: dict) -> str:
    """Execute the techdocs search skill."""
    query = arguments.get("query", "").strip()
    product = arguments.get("product", "all")

    if not query:
        return "Please provide a deployment or technical question."

    # Search internal docs first (higher priority for deployment)
    internal_results = _search_internal_docs(query, product)

    # Search official TechDocs
    official_results = []
    with httpx.Client(headers=HEADERS, timeout=15) as client:
        official_results = _search_official_techdocs(query, product, client)

    lines = []

    if internal_results:
        lines.append("## Internal Deployment Docs\n")
        for doc in internal_results[:5]:
            lines.append(f"### {doc['title']}")
            lines.append(f"Product: {doc.get('product', 'N/A')} | Tags: {', '.join(doc.get('tags', []))}")
            content = doc.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"\n{content}\n")
            lines.append("---")

    if official_results:
        lines.append("\n## Official TechDocs\n")
        for r in official_results[:8]:
            lines.append(f"- [{r['title']}]({r['url']})")

    if not internal_results and not official_results:
        lines.append(
            f"No documentation found for '{query}'.\n\n"
            f"Suggestions:\n"
            f"- Check docs.paloaltonetworks.com directly\n"
            f"- Try broader keywords (e.g., 'GlobalProtect' instead of 'GP portal config')\n"
            f"- Ask admin to add relevant internal deployment docs"
        )

    return "\n".join(lines)
