#!/usr/bin/env python3
"""
Standalone ERPNext Multi-Language Page Cloner & Translator (Mode A).

Clones published Page Builder `Web Page` documents from primary routes (`/<slug>`)
into language-prefixed routes (`/<lang>/<slug>`, with `home` -> `<lang>`),
rewrites internal URLs inside `web_template_values` JSON, and applies a translation
dictionary (or Translation DocType records) to text fields while preserving
100% of the Page Builder (`Web Template`) structure.
"""
import argparse
import json
import re
import frappe


URL_KEYS = {
    "url",
    "cta_url",
    "primary_action",
    "secondary_action",
    "link_url",
    "feature_url",
    "post_route",
    "card_1_url",
    "card_2_url",
    "card_3_url",
    "card_4_url",
}


def prefix_internal_url(url_val: str, lang_prefix: str = "en") -> str:
    """Prefix internal site links with /<lang_prefix>, leaving external/file/anchor links untouched."""
    if not url_val or not isinstance(url_val, str):
        return url_val
    u = url_val.strip()
    if (
        u.startswith("http://")
        or u.startswith("https://")
        or u.startswith("mailto:")
        or u.startswith("tel:")
        or u.startswith("#")
        or u.startswith("/files/")
        or u.startswith("/assets/")
        or u == f"/{lang_prefix}"
        or u.startswith(f"/{lang_prefix}/")
    ):
        return u
    if u in ("/", "/home"):
        return f"/{lang_prefix}"
    if u.startswith("/"):
        return f"/{lang_prefix}{u}"
    return u


def rewrite_html_links(html: str, lang_prefix: str = "en") -> str:
    """Rewrite internal href='/...' links inside rich text / Markdown strings."""
    if not html or not isinstance(html, str):
        return html

    def _repl(match):
        quote = match.group(1)
        href = match.group(2)
        new_href = prefix_internal_url(href, lang_prefix=lang_prefix)
        return f"href={quote}{new_href}{quote}"

    return re.sub(r'href=(["\'])([^"\']+)\1', _repl, html)


def translate_value(val, translations: dict, lang_prefix: str = "en", key_name: str = ""):
    """Recursively translate strings and rewrite internal URLs in web_template_values."""
    if isinstance(val, dict):
        return {
            k: translate_value(v, translations, lang_prefix=lang_prefix, key_name=k)
            for k, v in val.items()
        }
    if isinstance(val, list):
        return [
            translate_value(item, translations, lang_prefix=lang_prefix, key_name=key_name)
            for item in val
        ]
    if isinstance(val, str):
        if key_name in URL_KEYS or key_name.endswith("_url") or key_name.endswith("_action"):
            return prefix_internal_url(val, lang_prefix=lang_prefix)
        translated = translations.get(val, val)
        translated = rewrite_html_links(translated, lang_prefix=lang_prefix)
        return translated
    return val


def clone_all_published_pages(
    site: str = "frontend",
    sites_path: str = "/home/frappe/frappe-bench/sites",
    lang_prefix: str = "en",
    dictionary_path: str = "",
):
    frappe.init(site=site, sites_path=sites_path)
    frappe.connect()
    frappe.set_user("Administrator")

    translations = {}
    if dictionary_path:
        with open(dictionary_path, "r", encoding="utf-8") as f:
            translations = json.load(f)

    # Also load any existing Translation DocType entries for lang_prefix
    db_translations = frappe.get_all(
        "Translation",
        filters={"language": lang_prefix},
        fields=["source_text", "translated_text"],
    )
    for row in db_translations:
        if row.source_text and row.translated_text and row.source_text not in translations:
            translations[row.source_text] = row.translated_text

    home_page = frappe.db.get_single_value("Website Settings", "home_page") or "home"
    pages = frappe.get_all(
        "Web Page",
        filters={"published": 1, "content_type": "Page Builder"},
        fields=["name", "title", "route"],
    )

    cloned_count = 0
    for p in pages:
        route = (p.route or "").strip("/")
        if not route or route == lang_prefix or route.startswith(f"{lang_prefix}/"):
            continue

        target_route = lang_prefix if route == home_page else f"{lang_prefix}/{route}"
        target_name = f"{lang_prefix}-{p.name}"[:140]

        src_doc = frappe.get_doc("Web Page", p.name)
        existing_name = frappe.db.get_value("Web Page", {"route": target_route}, "name") or (
            target_name if frappe.db.exists("Web Page", target_name) else None
        )

        if existing_name:
            dst_doc = frappe.get_doc("Web Page", existing_name)
        else:
            dst_doc = frappe.get_doc({"doctype": "Web Page", "__newname": target_name})

        dst_doc.title = translations.get(src_doc.title, src_doc.title)
        dst_doc.route = target_route
        dst_doc.published = 1
        dst_doc.content_type = "Page Builder"
        dst_doc.full_width = src_doc.full_width
        dst_doc.show_title = src_doc.show_title
        dst_doc.insert_style = src_doc.insert_style
        dst_doc.meta_title = translations.get(src_doc.meta_title or src_doc.title, src_doc.meta_title or src_doc.title)
        dst_doc.meta_description = translations.get(src_doc.meta_description or "", src_doc.meta_description or "")
        dst_doc.meta_image = src_doc.meta_image

        new_blocks = []
        for blk in src_doc.page_blocks:
            raw_vals = json.loads(blk.web_template_values or "{}")
            translated_vals = translate_value(raw_vals, translations, lang_prefix=lang_prefix)
            new_blocks.append(
                {
                    "web_template": blk.web_template,
                    "web_template_values": json.dumps(translated_vals, ensure_ascii=False),
                    "css_class": blk.css_class,
                    "add_shade": blk.add_shade,
                    "add_top_padding": blk.add_top_padding,
                    "add_bottom_padding": blk.add_bottom_padding,
                    "add_container": blk.add_container,
                    "hide_block": blk.hide_block,
                }
            )

        dst_doc.set("page_blocks", new_blocks)
        dst_doc.save(ignore_permissions=True)
        cloned_count += 1
        print(f"Cloned '{route}' -> '{target_route}' ({dst_doc.title})")

    frappe.db.commit()
    frappe.clear_cache()
    from frappe.website.utils import clear_cache

    clear_cache()
    print(f"Done. Cloned/updated {cloned_count} multilingual Web Pages under '/{lang_prefix}/...'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clone and translate ERPNext Page Builder pages.")
    parser.add_argument("--site", default="frontend", help="Frappe site name")
    parser.add_argument("--sites-path", default="/home/frappe/frappe-bench/sites", help="Frappe sites directory")
    parser.add_argument("--lang", default="en", help="Target language URL prefix and code (default: en)")
    parser.add_argument("--dictionary", default="", help="Optional JSON file mapping source strings to target strings")
    args = parser.parse_args()
    clone_all_published_pages(
        site=args.site,
        sites_path=args.sites_path,
        lang_prefix=args.lang,
        dictionary_path=args.dictionary,
    )
