# ERPNext Multi-Language Website Architecture Reference

## 1. Frappe v16 Website Rendering & Jinja Sandbox Internals

When Frappe renders a website page (`frappe/templates/base.html`), it loads the header and footer using `Website Settings.navbar_template` and `Website Settings.footer_template`:

- **Default Navbar (`Standard Navbar`)**: Renders `{% include "templates/includes/navbar/navbar.html" %}`.
- **Custom Navbar (`Web Template`, `type='Navbar'`, `standard=0`)**: Rendered via `frappe.website.doctype.web_template.web_template.render_web_template`, which uses `frappe.utils.jinja.render_template(..., safe_render=True)`.
- **Safe Render Globals (`frappe/utils/safe_exec.py:render_safe_globals`)**:
  - `json.loads`, `json.dumps` (use instead of `frappe.parse_json` which is blocked for Guest users).
  - `frappe.request.path` (exact HTTP request path, e.g., `"/en/about-us"`, `"/en"`, `"/about-us"`, `"/"`).
  - `path` (normalized Frappe route in `_context_dict`, e.g., `"en"`, `"en/about-us"`, `"home"`, `"about-us"`).
  - `_(text, lang)` (`frappe._` translation function).
  - `frappe.db.get_single_value`, `frappe.db.get_value`, `frappe.get_list`, `frappe.get_all`.
  - Avoid `frappe.utils.generate_hash` inside custom `Web Template`s; use `id="nav-dropdown-{{ loop.index }}"` instead.

---

## 2. Bidirectional Route Mapping (`/<slug>` ↔ `/en/<slug>`)

| Language | Homepage Route (`Web Page.route`) | Public Homepage URL | Content Page Route (`Web Page.route`) | Blog Post Route (`Web Page.route`) |
| --- | --- | --- | --- | --- |
| Primary (`pl`) | `home` (`Website Settings.home_page`) | `/` | `<primary-slug>` (e.g. `services`) | `blog/<primary-slug>` |
| Secondary (`en`) | `en` | `/en` | `en/<primary-slug>` (e.g. `en/services`) | `en/blog/<primary-slug>` |

### Jinja Path Computation Snippet
```jinja2
{%- set req_path = (frappe.request.path if frappe.request else ('/' ~ (path or ''))) -%}
{%- set is_en = (req_path == '/en' or req_path.startswith('/en/') or path == 'en' or (path and path.startswith('en/'))) -%}
{%- if is_en -%}
    {%- set stripped = req_path[3:] if req_path.startswith('/en') else '/' -%}
    {%- set pl_url = stripped if (stripped and stripped.startswith('/')) else '/' -%}
    {%- set en_url = req_path if req_path.startswith('/en') else '/en' -%}
{%- else -%}
    {%- set pl_url = '/' if (req_path in ['', '/', '/home']) else req_path -%}
    {%- set en_url = '/en' if pl_url == '/' else ('/en' ~ pl_url) -%}
{%- endif -%}
```

---

## 3. Translation DocType & Multilingual E-Commerce Store Readiness

Frappe's `_(text, lang)` checks the `Translation` DocType (`tabTranslation`) after `.mo`/`.po` catalogs and merges any user-defined database translations on top.

For a multilingual E-Commerce store (`webshop` / `erpnext` E-Commerce):
1. **Language Cookie Sync**:
   - Frappe's `resolve_language()` checks `request.cookies.get("preferred_language")`.
   - Clicking `PL` or `EN` in the navbar switcher sets `document.cookie = "preferred_language=" + lang + "; path=/; max-age=31536000; SameSite=Lax"`.
   - In addition, if a visitor lands directly on `/en/...` via an external link without a cookie set yet, an inline script sets `preferred_language=en` immediately so subsequent AJAX/storefront calls use English.
2. **Translatable Store DocTypes**:
   - Enable `translated_doctype = 1` on `Item` and `Item Group` (or insert `Translation` records for item names, descriptions, and group names).
   - Add `Website Settings.route_redirects` from `en/shop` → `/shop` (or the target shop route) so `/en/shop` resolves cleanly and the language switcher works on store routes.
