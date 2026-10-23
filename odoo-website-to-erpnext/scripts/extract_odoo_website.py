#!/usr/bin/env python3
"""
Extract an Odoo website (pages, menus, blog posts, theme SCSS, and media/shape assets)
from an Odoo PostgreSQL container and HTTP server into a portable bundle directory.
"""
import argparse
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request


def run_psql(container: str, db_user: str, db_name: str, sql: str) -> str:
    for prefix in (["sudo", "-n"], []):
        cmd = prefix + [
            "docker", "exec", container,
            "psql", "-U", db_user, "-d", db_name, "-t", "-A", "-c", sql,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return res.stdout.strip()
    raise RuntimeError(f"psql query failed against container {container}")


def extract_website_data(pg_container: str, db_user: str, db_name: str, website_id: int, lang: str) -> dict:
    pages_sql = f"""
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (
      SELECT wp.id, wp.url, wp.is_published, wp.website_id, wp.view_id,
             v.name as view_name, v.key as view_key,
             v.arch_db->>'{lang}' as arch_lang,
             v.arch_db->>'en_US' as arch_en,
             v.arch_db::text as arch_raw
      FROM website_page wp
      JOIN ir_ui_view v ON wp.view_id = v.id
      WHERE wp.website_id = {website_id} OR wp.website_id IS NULL
      ORDER BY wp.id
    ) t;
    """
    blogs_sql = f"""
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (
      SELECT bp.id, bp.blog_id, bp.is_published, bp.website_id,
             bp.name->>'{lang}' as title_lang,
             bp.name->>'en_US' as title_en,
             bp.subtitle->>'{lang}' as subtitle_lang,
             bp.subtitle->>'en_US' as subtitle_en,
             bp.content->>'{lang}' as content_lang,
             bp.content->>'en_US' as content_en,
             bp.cover_properties,
             bp.published_date, bp.create_date, bp.author_id
      FROM blog_post bp
      WHERE bp.website_id = {website_id} OR bp.website_id IS NULL
      ORDER BY bp.id
    ) t;
    """
    menus_sql = f"""
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (
      SELECT id, name->>'{lang}' as name_lang, name->>'en_US' as name_en,
             url, parent_id, sequence, page_id
      FROM website_menu
      WHERE website_id = {website_id}
      ORDER BY parent_id NULLS FIRST, sequence, id
    ) t;
    """
    attachments_sql = """
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (
      SELECT id, name, mimetype, url
      FROM ir_attachment
      WHERE public = true OR res_model IN ('ir.ui.view', 'website', 'blog.post')
      ORDER BY id
    ) t;
    """
    pages = json.loads(run_psql(pg_container, db_user, db_name, pages_sql) or "[]")
    blogs = json.loads(run_psql(pg_container, db_user, db_name, blogs_sql) or "[]")
    menus = json.loads(run_psql(pg_container, db_user, db_name, menus_sql) or "[]")
    attachments = json.loads(run_psql(pg_container, db_user, db_name, attachments_sql) or "[]")
    return {
        "website_id": website_id,
        "lang": lang,
        "pages": pages,
        "blogs": blogs,
        "menus": menus,
        "attachments": attachments,
    }


def slugify_filename(url: str, attachment_names: dict = None) -> str:
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(urllib.parse.unquote(parsed.path))
    parts = [p for p in path.split("/") if p]
    if path.startswith("/web_editor/shape/"):
        shape_name = "_".join(parts[2:])
        if not shape_name.endswith(".svg"):
            shape_name += ".svg"
        q = parsed.query.replace("&", "_").replace("=", "-")
        if q:
            base, ext = os.path.splitext(shape_name)
            shape_name = f"{base}_{q}{ext}"
        return re.sub(r"[^a-zA-Z0-9._-]", "_", shape_name)
    elif path.startswith("/web/content/"):
        att_id = parts[2].split("-")[0]
        if attachment_names and att_id.isdigit() and int(att_id) in attachment_names:
            return re.sub(r"[^a-zA-Z0-9._-]", "_", f"{att_id}_{attachment_names[int(att_id)]}")
        return f"attachment_{att_id}.bin"
    elif path.startswith("/web/image/"):
        if len(parts) >= 4:
            att_prefix = parts[2].split("-")[0]
            fname = parts[3]
            clean = re.sub(r"[^a-zA-Z0-9._-]", "_", fname)
            return f"{att_prefix}_{clean}"
        else:
            ref = parts[2].replace(".", "_")
            clean = re.sub(r"[^a-zA-Z0-9._-]", "_", ref)
            return clean + ".jpg"
    return re.sub(r"[^a-zA-Z0-9._-]", "_", path)


def download_assets(data: dict, odoo_url: str, palette: dict, assets_dir: str, assets_prefix: str = "/files/website") -> dict:
    os.makedirs(assets_dir, exist_ok=True)
    attachment_names = {
        int(a["id"]): a["name"]
        for a in data.get("attachments", [])
        if a.get("id") and a.get("name")
    }
    texts = []
    for p in data.get("pages", []):
        texts.append(p.get("arch_lang") or p.get("arch_en") or p.get("arch_raw") or "")
    for b in data.get("blogs", []):
        texts.append(b.get("content_lang") or b.get("content_en") or "")
        texts.append(b.get("cover_properties") or "")

    raw = html.unescape("\n".join(texts))
    urls = set(re.findall(r"/(?:web/image|web/content|web_editor/shape)/[^\"\x27\s\)\<\>]+", raw))

    asset_map = {}
    for orig_url in sorted(urls):
        fetch_url = orig_url
        if fetch_url.startswith("/web_editor/shape/"):
            for k, hex_val in palette.items():
                fetch_url = fetch_url.replace(k, urllib.parse.quote(hex_val))
        full_url = odoo_url.rstrip("/") + fetch_url
        fname = slugify_filename(orig_url, attachment_names)
        dest_path = os.path.join(assets_dir, fname)
        req = urllib.request.Request(full_url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                content = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                if fname.startswith("website_s_"):
                    base = os.path.splitext(fname)[0]
                    if "png" in ctype:
                        fname = base + ".png"
                    elif "svg" in ctype:
                        fname = base + ".svg"
                    elif "webp" in ctype:
                        fname = base + ".webp"
                    else:
                        fname = base + ".jpg"
                    dest_path = os.path.join(assets_dir, fname)
                with open(dest_path, "wb") as f:
                    f.write(content)
            asset_map[orig_url] = f"{assets_prefix.rstrip('/')}/{fname}"
        except Exception as exc:
            print(f"Warning: could not fetch {full_url}: {exc}")
    return asset_map


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Odoo Website Data & Assets")
    parser.add_argument("--db-container", default="odoo-db-1", help="Odoo PostgreSQL Docker container")
    parser.add_argument("--db-user", default="odoo", help="PostgreSQL user")
    parser.add_argument("--db-name", default="odoo", help="PostgreSQL database name")
    parser.add_argument("--website-id", type=int, default=1, help="Odoo website.id to extract")
    parser.add_argument("--lang", default="pl_PL", help="Primary Odoo language code (e.g. pl_PL)")
    parser.add_argument("--odoo-url", default="http://localhost:8069", help="Base URL of running Odoo instance")
    parser.add_argument("--output-dir", default="/tmp/odoo_website_extract", help="Output bundle directory")
    parser.add_argument("--assets-prefix", default="/files/website", help="Target ERPNext public file URL prefix")
    parser.add_argument("--palette-json", default="", help="Optional JSON string or file overriding o-color-1..o-color-5")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    data_json_path = os.path.join(args.output_dir, "website_data.json")
    assets_dir = os.path.join(args.output_dir, "assets")
    asset_map_path = os.path.join(args.output_dir, "asset_map.json")

    data = extract_website_data(args.db_container, args.db_user, args.db_name, args.website_id, args.lang)
    with open(data_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    palette = {
        "o-color-1": "#3B82F6",
        "o-color-2": "#F59E0B",
        "o-color-3": "#F8FAFC",
        "o-color-4": "#FFFFFF",
        "o-color-5": "#0F172A",
    }
    if args.palette_json:
        if os.path.isfile(args.palette_json):
            with open(args.palette_json, "r", encoding="utf-8") as pf:
                palette.update(json.load(pf))
        else:
            palette.update(json.loads(args.palette_json))

    asset_map = download_assets(data, args.odoo_url, palette, assets_dir, args.assets_prefix)
    with open(asset_map_path, "w", encoding="utf-8") as f:
        json.dump(asset_map, f, indent=2, ensure_ascii=False)
    print(f"Extracted website {args.website_id} ({len(data['pages'])} pages, {len(data['blogs'])} blogs) and {len(asset_map)} assets to {args.output_dir}")
