"""Skill 4: SKU Calculator (PA Internal Only)

查询 PANW 产品 SKU 计算方式。
数据由管理员维护在 data/sku/sku_rules.json 中。
仅对 PA 内部人员开放。
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "sku"
DB_PATH = DATA_DIR / "sku_rules.json"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "query_sku",
        "description": (
            "Look up SKU calculation rules for PANW products. For internal staff only. "
            "Helps with pricing, licensing tiers, and SKU selection based on requirements. "
            "Use this when an INTERNAL user asks about SKU numbers, licensing, pricing tiers, "
            "or how to calculate the right SKU for a customer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Product or SKU question (e.g., 'PA-450 licensing', 'Prisma Access tier calculation', 'XSIAM pricing model')",
                },
                "customer_size": {
                    "type": "string",
                    "description": "Optional: customer size info (e.g., '5000 users', '3 sites')",
                },
            },
            "required": ["query"],
        },
    },
}


def _load_db() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text())
    return {"products": [], "rules": [], "notes": ""}


def _save_db(data: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def add_product_sku(product: str, skus: list[dict], calculation_notes: str = "") -> dict:
    """Admin: add/update SKU info for a product."""
    db = _load_db()
    existing = next((p for p in db["products"] if p["product"].lower() == product.lower()), None)
    if existing:
        existing["skus"] = skus
        existing["calculation_notes"] = calculation_notes
    else:
        db["products"].append({
            "product": product,
            "skus": skus,
            "calculation_notes": calculation_notes,
        })
    _save_db(db)
    return {"product": product, "sku_count": len(skus)}


def add_rule(rule: str, applies_to: str = "all"):
    """Admin: add a general SKU calculation rule."""
    db = _load_db()
    db["rules"].append({"rule": rule, "applies_to": applies_to})
    _save_db(db)


def list_products() -> list[str]:
    """List all products with SKU data."""
    db = _load_db()
    return [p["product"] for p in db["products"]]


async def handle(arguments: dict) -> str:
    """Execute the SKU query skill."""
    query = arguments.get("query", "").strip().lower()
    customer_size = arguments.get("customer_size", "")

    if not query:
        return "Please provide a product name or SKU-related question."

    db = _load_db()

    if not db["products"] and not db["rules"]:
        return (
            "SKU database is empty. Admin needs to populate SKU rules.\n"
            "Use the admin API to add product SKU information."
        )

    # Search products
    matches = []
    for prod in db["products"]:
        searchable = f"{prod['product']} {prod.get('calculation_notes', '')}".lower()
        sku_text = " ".join(s.get("sku", "") + " " + s.get("description", "") for s in prod.get("skus", []))
        searchable += " " + sku_text.lower()
        if query in searchable or any(kw in searchable for kw in query.split()):
            matches.append(prod)

    # General rules
    applicable_rules = []
    for rule in db.get("rules", []):
        if rule["applies_to"] == "all" or query in rule["applies_to"].lower():
            applicable_rules.append(rule["rule"])

    if not matches and not applicable_rules:
        available = [p["product"] for p in db["products"]]
        return (
            f"No SKU information found for '{query}'.\n"
            f"Available products: {', '.join(available) if available else 'none'}\n"
            f"Try a product name like 'Prisma Access', 'PA-450', 'Cortex XDR'."
        )

    lines = []
    for prod in matches[:5]:
        lines.append(f"## {prod['product']}\n")
        if prod.get("calculation_notes"):
            lines.append(f"{prod['calculation_notes']}\n")
        if prod.get("skus"):
            lines.append("| SKU | Description | Notes |")
            lines.append("|-----|-------------|-------|")
            for sku in prod["skus"]:
                lines.append(f"| {sku.get('sku', '')} | {sku.get('description', '')} | {sku.get('notes', '')} |")
            lines.append("")

    if customer_size:
        lines.append(f"\n*Customer context: {customer_size}*")
        lines.append("Please confirm the exact requirements with your SE team for accurate sizing.")

    if applicable_rules:
        lines.append("\n**General Rules:**")
        for rule in applicable_rules:
            lines.append(f"- {rule}")

    return "\n".join(lines)
