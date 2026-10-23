#!/usr/bin/env python3
"""
Extract ONLY published store items (product_template.is_published = true)
and their main + gallery images from an Odoo PostgreSQL container and HTTP server.
"""
import argparse
import html
import json
import os
import re
import subprocess
import unicodedata
import urllib.request


def strip_tags(raw_html: str) -> str:
    if not raw_html:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(re.sub(r"\s+", " ", cleaned)).strip()


def slugify_odoo(text: str, prod_id: int) -> str:
    replacements = {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
        "ó": "o", "ś": "s", "ź": "z", "ż": "z",
        "Ą": "a", "Ć": "c", "Ę": "e", "Ł": "l", "Ń": "n",
        "Ó": "o", "Ś": "s", "Ź": "z", "Ż": "z",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return f"{text}-{prod_id}"


def run_psql_json(db_container: str, db_user: str, db_name: str, sql: str):
    wrapped = f"SELECT COALESCE(json_agg(t), '[]'::json) FROM ({sql}) t;"
    cmd = [
        "docker", "exec", db_container,
        "psql", "-U", db_user, "-d", db_name, "-t", "-A", "-c", wrapped,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return json.loads(out) if out else []


def main():
    parser = argparse.ArgumentParser(description="Extract published store items from Odoo.")
    parser.add_argument("--db-container", default="odoo-db", help="Odoo PostgreSQL container name")
    parser.add_argument("--db-user", default="odoo", help="PostgreSQL user")
    parser.add_argument("--db-name", default="odoo", help="PostgreSQL database name")
    parser.add_argument("--website-id", type=int, default=1, help="Odoo website.id")
    parser.add_argument("--odoo-url", default="http://localhost:8069", help="Odoo base HTTP URL")
    parser.add_argument("--files-prefix", default="/files/store", help="Target ERPNext public file prefix")
    parser.add_argument("--item-code-prefix", default="STORE-PROD-", help="ERPNext Item Code prefix")
    parser.add_argument("--currency", default="PLN", help="Store currency code")
    parser.add_argument("--output-dir", default="/tmp/odoo_store_extract", help="Output directory")
    args = parser.parse_args()

    img_dir = os.path.join(args.output_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    files_prefix = args.files_prefix.rstrip("/")

    products_sql = f"""
        SELECT
            pt.id,
            pt.website_id,
            pt.is_published,
            pt.website_sequence,
            pt.type,
            pt.list_price::float AS list_price,
            pt.default_code,
            pt.name,
            pt.description_sale,
            pt.description_ecommerce,
            pt.website_meta_title,
            pt.website_meta_description
        FROM product_template pt
        WHERE pt.is_published = true
          AND (pt.website_id = {args.website_id} OR pt.website_id IS NULL)
        ORDER BY pt.website_sequence, pt.id
    """
    products = run_psql_json(args.db_container, args.db_user, args.db_name, products_sql)

    gallery_sql = f"""
        SELECT
            pi.id,
            pi.name,
            pi.product_tmpl_id,
            pi.sequence
        FROM product_image pi
        JOIN product_template pt ON pt.id = pi.product_tmpl_id
        WHERE pt.is_published = true
          AND (pt.website_id = {args.website_id} OR pt.website_id IS NULL)
        ORDER BY pi.product_tmpl_id, pi.sequence, pi.id
    """
    gallery_rows = run_psql_json(args.db_container, args.db_user, args.db_name, gallery_sql)
    gallery_by_tmpl = {}
    for g in gallery_rows:
        gallery_by_tmpl.setdefault(g["product_tmpl_id"], []).append(g)

    extracted = []
    for p in products:
        pid = p["id"]
        name_map = p.get("name") or {}
        name_pl = (name_map.get("pl_PL") or name_map.get("en_US") or f"Product {pid}").strip()
        name_en = (name_map.get("en_US") or name_pl).strip()

        slug_pl = slugify_odoo(name_pl, pid)
        slug_en_odoo = slugify_odoo(name_en, pid)

        main_fname = f"product_{pid}_main.webp"
        main_url = f"{args.odoo_url}/web/image/product.template/{pid}/image_1024"
        try:
            data = urllib.request.urlopen(main_url).read()
            with open(os.path.join(img_dir, main_fname), "wb") as f:
                f.write(data)
        except Exception as exc:
            print(f"Warning: could not download main image for product {pid}: {exc}")

        gallery_files = [f"{files_prefix}/{main_fname}"]
        for idx, g in enumerate(gallery_by_tmpl.get(pid, []), start=1):
            g_fname = f"product_{pid}_gallery_{idx}.webp"
            g_url = f"{args.odoo_url}/web/image/product.image/{g['id']}/image_1024"
            try:
                g_data = urllib.request.urlopen(g_url).read()
                with open(os.path.join(img_dir, g_fname), "wb") as f:
                    f.write(g_data)
                gallery_files.append(f"{files_prefix}/{g_fname}")
            except Exception as exc:
                print(f"Warning: could not download gallery image {g['id']}: {exc}")

        desc_map = p.get("description_ecommerce") or {}
        sale_map = p.get("description_sale") or {}
        desc_pl = desc_map.get("pl_PL") or "" if isinstance(desc_map, dict) else str(desc_map or "")
        desc_en = desc_map.get("en_US") or desc_pl if isinstance(desc_map, dict) else str(desc_map or "")
        short_pl = (sale_map.get("pl_PL") if isinstance(sale_map, dict) else "") or strip_tags(desc_pl)[:220]
        short_en = (sale_map.get("en_US") if isinstance(sale_map, dict) else "") or strip_tags(desc_en)[:220]

        price = float(p.get("list_price") or 0.0)
        is_service = p.get("type") == "service"

        extracted.append({
            "odoo_id": pid,
            "item_code": f"{args.item_code_prefix}{pid}",
            "item_group": "Services" if is_service else "Products",
            "is_stock_item": 0 if is_service else 1,
            "type": p["type"],
            "price": price,
            "list_price": price,
            "price_fmt_pl": f"{price:,.2f} zł".replace(",", " ").replace(".", ","),
            "price_fmt_en": f"{price:.2f} {args.currency}",
            "currency": args.currency,
            "name_pl": name_pl,
            "name_en": name_en,
            "category_pl": "Usługi" if is_service else "Produkty",
            "category_en": "Services" if is_service else "Products",
            "short_desc_pl": short_pl,
            "short_desc_en": short_en,
            "slug_pl": slug_pl,
            "slug_en_odoo": slug_en_odoo,
            "route_pl": f"shop/{slug_pl}",
            "route_en": f"en/shop/{slug_pl}",
            "description_pl": desc_pl,
            "description_en": desc_en,
            "main_image": f"{files_prefix}/{main_fname}",
            "gallery_images": gallery_files,
        })

    out_json = os.path.join(args.output_dir, "published_store_items.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(extracted, f, ensure_ascii=False, indent=2)

    print(f"Extracted {len(extracted)} published store items to {out_json}")


if __name__ == "__main__":
    main()
