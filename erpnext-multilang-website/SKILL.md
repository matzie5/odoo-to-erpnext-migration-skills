---
name: erpnext-multilang-website
description: Enable multi-language support on an ERPNext website (both for an existing ERPNext installation and during an Odoo-to-ERPNext migration) using URL-prefixed Page Builder pages (/en/<original-slug>), a top navbar language switcher (Multilingual Navbar Web Template), a bilingual footer (Headline Footer Web Template), Translation DocType records, and preferred_language cookie synchronization ready for multilingual E-Commerce stores.
---

# ERPNext Multi-Language Website & Store Readiness Skill

## Purpose

Enable seamless multi-language support (`PL | EN` or any primary/secondary language pair) on an ERPNext v15/v16 website while strictly using **ERPNext Page Builder building blocks (`Web Template`s)**, `Website Settings`, and `Translation` DocType records—without modifying core Frappe/ERPNext Python files or hardcoding monolithic HTML pages.

This skill supports **two operating modes**:
1. **Standalone Existing ERPNext Installation**: Clone existing `Page Builder` `Web Page`s into `/<lang>/<original-slug>` (and `/<lang>` for `home`), rewrite internal links (`/<slug>` → `/<lang>/<slug>`), translate block JSON values (`web_template_values`), and enable the `Multilingual Navbar` with a top language switcher.
2. **Odoo-to-ERPNext Multilingual Migration**: Extract translated strings from Odoo's `jsonb` columns (`ir_ui_view.arch_db->>'en_US'`, `website_menu.name->>'en_US'`, `blog_post.name/subtitle/content->>'en_US'`, `product_template.name->>'en_US'`) and populate the `/<lang>/<original-slug>` Page Builder pages, blogs, menus, and `Translation` records.

---

## Core Architecture (4-Layer Hybrid Design)

Why Frappe's built-in `show_language_picker` is not sufficient by itself:
- Built-in Page Builder `Web Template`s (`Section with Cards`, `Split Section with Image`, `Section with Testimonials`, etc.) output `{{ title }}` and `{{ content }}` without wrapping them in `_(...)`.
- Frappe's `website.js` `show_language_picker` is hidden for logged-in users (`frappe.session.user === "Guest"`), displays all 19+ enabled system languages instead of the site's active languages (`PL | EN`), omits `path=/` when writing the `preferred_language` cookie, and does not provide SEO-friendly `/en/<slug>` URLs.

To solve this cleanly using native ERPNext building blocks:

### Layer 1: URL-Prefixed Page Builder `Web Page`s (`/en` & `/en/<original-slug>`)
- **Primary Language (e.g. Polish `pl`)**:
  - Homepage: `route = "home"` (served at `/`)
  - Content pages: `route = "<original-slug>"` (e.g. `about-us`, `services`, `contactus`)
  - Blog posts: `route = "blog/<blog-slug>"`
- **Secondary Language (e.g. English `en`)**:
  - Homepage: `route = "en"` (served at `/en` — in Frappe v16 `PathResolver`, `en` is a valid non-reserved `Web Page` route)
  - Content pages: `route = "en/<original-slug>"` (e.g. `en/about-us`, `en/services`, `en/contactus`)
  - Blog posts: `route = "en/blog/<blog-slug>"` (preserving the original primary-language slug under `/en/...` for 1-to-1 counterpart switching and Odoo URL compatibility)
- All `/en/...` pages use `content_type = "Page Builder"` and reference the exact same reusable `Web Template` building blocks as the primary-language pages, with English `web_template_values` and `/en/...` internal CTA/card URLs.

### Layer 2: `Multilingual Navbar` (`Web Template`, `type = "Navbar"`)
- Assigned via `Website Settings.navbar_template = "Multilingual Navbar"` and configured via `Website Settings.navbar_template_values`.
- **Sandboxed Jinja Compatibility (`render_safe_globals`)**:
  - Uses `json.loads()` (never `frappe.parse_json()`, which is blocked for `Guest` users in Frappe v16's `render_safe_globals()`).
  - Detects current language directly from `frappe.request.path` / `path`:
    ```jinja
    {%- set req_path = (frappe.request.path if frappe.request and frappe.request.path else ("/" + (path or ""))) -%}
    {%- set clean_path = req_path.rstrip("/") or "/" -%}
    {%- set is_en = (clean_path == "/en" or clean_path.startswith("/en/")) or (path == "en" or (path or "").startswith("en/")) -%}
    ```
  - Computes exact counterpart URLs (`pl_url` and `en_url`) for the **top language switcher (`PL | EN`)**:
    - `/` or `/home` ↔ `/en`
    - `/<slug>` ↔ `/en/<slug>`
    - `/blog/<blog-slug>` ↔ `/en/blog/<blog-slug>`
    - `/shop` ↔ `/en/shop`
  - Renders as a sticky top header (`<nav class="navbar navbar-light navbar-expand-lg sticky-top">` paired with `position: sticky !important; top: 0 !important; z-index: 1030 !important;` in `Website Theme.custom_scss`) so navigation and the `PL | EN` language switcher remain accessible at all scroll positions.
  - Dynamically translates `top_bar_items` labels (including nested dropdown `child_items`), rewrites internal links to `/en/...`, updates the brand logo `href` (`/` vs `/en`), and localizes the navbar CTA button (`Skontaktuj się z nami` → `Contact Us`).
  - Synchronizes Frappe's `preferred_language` cookie (`document.cookie = "preferred_language=en; path=/; max-age=31536000; SameSite=Lax"`) both when clicking `PL | EN` and automatically on page load based on the URL prefix.

### Layer 3: Bilingual `Headline Footer` & Section `Web Template`s
- **`Headline Footer` (`type = "Footer"`)**:
  - Reads `headline_title_en` and `headline_lead_en` from `Website Settings.footer_template_values` when `is_en` is True.
  - Translates `footer_items` (`Home` → `/en`, `Contact us` → `/en/contactus`, `Privacy Policy` → `/en/cookie-policy`).
  - Renders a secondary `Polski | English` language switcher in the bottom copyright bar.
- **`Contact and Inquiry Form` & `Dynamic Blog Posts Grid` (`type = "Section"`)**:
  - Automatically detect `is_en` from `frappe.request.path` (or explicit `lang` field) to render English form field labels, sidebar labels, `/en/contactus-thank-you` redirect, and `Read more →` blog links.

### Layer 4: `Translation` DocType & Multilingual Store Readiness
- Seeds `Translation` DocType records (`language = "en"` and `language = "pl"`) for navigation labels, system strings (`Learn more`, `Login`, `My Account`, `Log out`), and E-Commerce / Store vocabulary (`Add to Cart`, `View in Cart`, `Go to Quote`, `Out of Stock`, `Price`, `Categories`, `All Products`, plus product/item names and descriptions).
- Enables `translated_doctype = 1` (via `Property Setter`) on `Item` and `Item Group` so Frappe's ORM automatically translates item titles and group names whenever `frappe.local.lang == "en"`.
- Configures `Website Settings.route_redirects` for English aliases (`en/privacy` → `en/cookie-policy`, `en/shop` → `/en/shop`).

---

## Workflow

### Step 1: Install / Update Multilingual `Web Template`s & `Website Settings`
Run [`enable_erpnext_multilang.py`](scripts/enable_erpnext_multilang.py) (for Odoo-to-ERPNext migrations) or [`clone_and_translate_erpnext_pages.py`](scripts/clone_and_translate_erpnext_pages.py) (for any standalone ERPNext site) inside the ERPNext backend container:

```bash
docker cp scripts/enable_erpnext_multilang.py erpnext-backend-1:/tmp/enable_erpnext_multilang.py
docker exec -w /home/frappe/frappe-bench/sites erpnext-backend-1 /home/frappe/frappe-bench/env/bin/python /tmp/enable_erpnext_multilang.py --data-json /tmp/odoo_website_data.json
```

> [!IMPORTANT]
> Always execute Frappe scripts with `-w /home/frappe/frappe-bench/sites` so Frappe's relative logger path (`../logs/database.log`) resolves to `/home/frappe/frappe-bench/logs/database.log`.

### Step 2: Clear Frappe Website & Translation Caches
After creating/updating `Web Page`s, `Web Template`s, `Website Settings`, or `Translation` records, always clear both Redis cache and website page cache:
```python
frappe.clear_cache()
from frappe.website.utils import clear_cache
clear_cache()
```

### Step 3: Verify Counterpart Routes & Language Switcher
Verify that:
1. Every primary-language route (`/`, `/about-us`, `/services`, `/blog`, `/blog/<slug>`, `/contactus`, etc.) returns HTTP `200` and renders the top language switcher with `PL` active and `EN` linking to `/en` or `/en/<slug>`.
2. Every English route (`/en`, `/en/about-us`, `/en/services`, `/en/blog`, `/en/blog/<slug>`, `/en/contactus`, etc.) returns HTTP `200`, renders English navbar/footer/page blocks, and renders the top language switcher with `EN` active and `PL` linking back to `/` or `/<slug>`.

---

## References & Scripts
- Architecture & Store Readiness Reference: [`references/multilang-architecture.md`](references/multilang-architecture.md)
- Full Bilingual Migration & Setup Script: [`scripts/enable_erpnext_multilang.py`](scripts/enable_erpnext_multilang.py)
- Generic Standalone ERPNext Page Cloner & Translator: [`scripts/clone_and_translate_erpnext_pages.py`](scripts/clone_and_translate_erpnext_pages.py)
