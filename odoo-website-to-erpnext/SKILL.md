---
name: odoo-website-to-erpnext
description: Migrate an Odoo website (theme, color palette, typography, navigation menus, footer, QWeb snippet pages, blog posts, web forms, and media assets) to ERPNext using ERPNext Page Builder building blocks (Web Templates), Website Theme, Website Settings, and Web Forms instead of hardcoded HTML blobs.
---

# Odoo Website to ERPNext Migration Skill

Use this skill when migrating a website from an Odoo instance (PostgreSQL + Odoo HTTP/filestore) to an ERPNext / Frappe instance (MariaDB + Frappe Bench).

## Core Principles

1. **Building-Block First (Avoid Raw HTML Blobs)**:
   - Decompose every Odoo QWeb page (`ir_ui_view.arch_db` `<section data-snippet="...">`) into structured ERPNext **Page Builder** blocks (`Web Page Block`) backed by standard ERPNext **`Web Template`** records (`Hero`, `Hero with Right Image`, `Split Section with Image`, `Section with Cards`, `Section with Features`, `Section with Collapsible Content`, `Section with CTA`, `Section with Small CTA`, `Section with Testimonials`, `Section with Image Grid`, `Section with Embed`, `Markdown`).
   - Only create custom **`Web Template`** records (`standard = 0`, `type = 'Section'` or `type = 'Footer'`) when a visual/functional pattern is not covered by built-in blocks (for example: Odoo's `template_footer_headline` footer, dynamic blog post grids, >9-item partner logo marquees, or multi-field interactive contact/inquiry forms with sidebars), and make those custom templates **parameterized via `Web Template Field`s** so they remain editable in the ERPNext UI.
   - Distinguish between Odoo's boxed CTA card (`s_cta_box` → `Section with CTA`, styled on `.section-cta` inside a neutral `o-cc1` section with `add_top_padding = 0`) and Odoo's full-width 2-column horizontal CTA banner (`s_call_to_action` → `Section with Small CTA` with `css_class = "o-cc5"`).
2. **Preserve Look & Feel via `Website Theme`**:
   - Extract the Odoo website's 5-color palette (`o-color-1`..`o-color-5`), color combinations (`o_cc1`..`o_cc5`), heading and body fonts, and button border-radius from `ir_attachment` (`_assets_primary_variables.scss`) and map them to ERPNext `Color` records and `Website Theme` (`primary_color`, `dark_color`, `light_color`, `text_color`, `background_color`, `google_font`, `custom_overrides`, `custom_scss`).
   - Provide CSS utility classes (`o-cc1`..`o-cc5`) in `Website Theme.custom_scss` and apply them via `Web Page Block.css_class` so section background/foreground combinations match Odoo's color presets.
   - Override Frappe's base `.navbar` (making it sticky via `position: sticky !important; top: 0 !important; z-index: 1030 !important; backdrop-filter: blur(8px)`), `.section-cta` (`background-color: #ededed; padding: 5rem 3rem`), `.web-footer` (`min-height: 140px` inside `body { height: 100%; display: flex; flex-direction: column }`), `.section-padding` (`8rem` desktop padding), `.section-with-features .section-features` (inline `style="margin-top: -1.5rem"` when `subtitle` is empty), and `.split-section-with-image` mobile column ordering in `Website Theme.custom_scss` so the sticky header, CTA cards, footers, feature grids, section spacing, and alternating split-section images behave cleanly across desktop and mobile.
3. **Complete Media & Shape Migration (CMS-Compatible Flat `/files/` Structure)**:
   - Download all referenced `/web/image/...` and `/web/content/...` attachments from Odoo.
   - For Odoo's dynamic SVG shapes (`/web_editor/shape/<theme>/<shape>.svg?c1=o-color-1...`), substitute `o-color-1`..`o-color-5` in the query string with URL-encoded hex colors (`%23...`) when fetching from Odoo's HTTP server so Odoo's `/web_editor/shape` controller bakes the exact website palette into the downloaded SVG.
   - **Never save extensionless files or nested subfolder paths in `file_url`**:
     - Odoo built-in attachments like `website.s_key_images_default_image_3` lack file extensions in `ir_attachment.name` and contain dots in the module prefix. Always normalize filenames by replacing dots in module prefixes with underscores and appending the proper extension from `mimetype` (e.g., `website_s_key_images_default_image_3.jpg`).
     - Frappe's `Section with Cards` (`templates/includes/image_with_blur.html` $\rightarrow$ `get_thumbnail_base64_for_image` $\rightarrow$ `get_local_image`) parses `file_url.rsplit(".", 1)` and passes `extn` directly to `PIL.Image.save(buffered, extn)`. An extensionless `file_url` or an `RGBA` PNG saved with a `.jpg` extension will crash page rendering. Always convert any `RGBA`/`P` mode image with a `.jpg`/`.jpeg` extension to `RGB` JPEG.
     - Save all public assets **flat** into `/home/frappe/frappe-bench/sites/<site>/public/files/<filename_with_ext>` (`file_url = "/files/<filename_with_ext>"`) and register each in `tabFile` under `folder = "Home"` (`is_private = 0`). Frappe's `File` DocType (`file.py`) and CMS File Picker (`Attach Image` $\rightarrow$ `Library`) expect public files to reside flat in `/files/<filename_with_ext>`.
4. **Navigation, Footer Template, Blogs, and Forms**:
   - Map `website_menu` hierarchy to `Website Settings.top_bar_items` (supporting parent/child dropdowns via `parent_label`).
   - Map the Odoo footer template (e.g. `website.template_footer_headline`) to a custom `Web Template` with `type = "Footer"` linked via `Website Settings.footer_template` and `Website Settings.footer_template_values`, keeping only the original footer links in `Website Settings.footer_items` and clearing static HTML from `Website Settings.address` so the footer and contact sidebars dynamically pull legal company details (`company_name`, `tax_id`, `custom_krs`, `custom_regon`, `phone_no`, `email`) and registered office `Address` (`Dynamic Link` to `Company`) from ERPNext settings.
     > **Important Jinja Sandbox Rule**: In Frappe `Web Template`s and `Print Format`s, `frappe.parse_json` is blocked by `render_safe_globals()`. Always use `json.loads(...)` when parsing JSON inside a `Web Template` or `Print Format`.
   - Migrate `blog_blog` and `blog_post` records to ERPNext (`Blog Category` + `Blog Post` when the `blog` app/DocTypes are installed, plus `Help Category` + `Help Article` and structured `Web Page` articles under `/<blog-slug>/<post-slug>` in Frappe v16+).
   - Migrate `s_website_form` sections to ERPNext `Contact Us Settings`, `Web Form` documents (`Lead` / `Communication`), and interactive form sections.
     - To deliver Contact Us form contents directly to an inbox with preserved multiline formatting, configure a default outgoing `Email Account` (`enable_outgoing = 1`, `default_outgoing = 1`, `always_use_account_email_id_as_sender = 1`), clear `Contact Us Settings.forward_to_email` (so `frappe.www.contact.send_message` does not send an unformatted duplicate), set `doc.recipients` on incoming website `Communication` records (`doc.sent_or_received == "Received" and not doc.reference_doctype`), and create native Frappe `Notification`s (`event = "New"`) on `Communication` and `Lead` wrapping `{{ doc.content }}` in `<div style="white-space: pre-wrap;">`.

---

## Step-by-Step Workflow

### Phase 1: Discovery & Extraction from Odoo
1. **Inspect Odoo Websites & Languages**:
   Query `website`, `res_lang`, `website_page`, `website_menu`, and `blog_post` in the Odoo PostgreSQL database:
   ```bash
   psql -U odoo -d <db_name> -t -A -c "SELECT id, name, domain, default_lang_id FROM website ORDER BY id;"
   ```
   > Always pass `-t -A` to `psql` when querying `ir_ui_view.arch_db` so PostgreSQL does not pad wide columns with megabytes of whitespace.
2. **Extract Website Bundle JSON**:
   Run [`scripts/extract_odoo_website.py`](scripts/extract_odoo_website.py) inside or against the Odoo PostgreSQL container to export:
   - Website metadata & theme SCSS attachments (`_assets_primary_variables.scss`)
   - Navigation menu tree (`website_menu`)
   - All `website_page` records and their resolved `ir_ui_view.arch_db` (with `jsonb` translation strings for the target locale, e.g. `pl_PL`)
   - Custom header/footer view templates (`ir_ui_view` inheriting `website.layout` / `website.footer_custom`)
   - All `blog_post` records for the website

### Phase 2: Asset & SVG Shape Migration
1. Scan all extracted HTML, blog `cover_properties`, and header/footer views for:
   - `/web/image/...`
   - `/web/content/...`
   - `/web_editor/shape/...`
2. Replace `o-color-1`..`o-color-5` in `/web_editor/shape/...` URLs with URL-encoded hex values from the extracted theme palette before downloading from `http://<odoo_host>:8069`.
3. Copy downloaded files flat into ERPNext `/home/frappe/frappe-bench/sites/<site>/public/files/<filename_with_ext>` (ensuring valid file extensions and converting any RGBA-in-JPEG files to RGB JPEG) and create `File` DocType records under `folder = "Home"` with `file_url = "/files/<filename_with_ext>"`.

### Phase 3: Theme & Branding Setup in ERPNext
1. Create `Color` records in ERPNext for each palette color (`o-color-1`..`o-color-5`).
2. Create or update a `Website Theme` document:
   - Set `google_font`, `primary_color`, `dark_color`, `light_color`, `text_color`, `background_color`.
   - Add Bootstrap/Frappe variable overrides in `custom_overrides` (e.g., `$font-family-sans-serif`, `$headings-font-family`, `$border-radius-pill`).
   - Add styling rules in `custom_scss` for `.o-cc1`..`.o-cc5` color combination sections, pill buttons, navbar CTA button, and card hover states.
   - Save the `Website Theme` document so Frappe compiles the SCSS into `/files/website_theme/<theme>_style.css`, and set `Website Settings.website_theme`.

### Phase 4: Snippet-to-Building-Block Mapping
Consult [`references/snippet-mapping.md`](references/snippet-mapping.md) for the complete mapping table from Odoo `data-snippet` types (`s_banner`, `s_cards_grid`, `s_showcase`, `s_key_benefits`, `s_accordion_image`, `s_faq_collapse`, `s_text_image`, `s_image_text`, `s_cta_box`, `s_call_to_action`, `s_quotes_carousel`, `s_company_team`, `s_references`, `s_embed_code`, `s_website_form`, `s_blog_posts`, `s_image_gallery`, `s_text_cover`, `s_text_block`) to ERPNext `Web Template`s and their exact JSON `web_template_values` schemas.

### Phase 5: Import Pages, Blogs, Web Forms & Settings into ERPNext
1. Execute [`scripts/migrate_to_erpnext.py`](scripts/migrate_to_erpnext.py) inside the ERPNext backend container (`erpnext-backend-1` with working directory `/home/frappe/frappe-bench/sites`).
2. Clear Frappe caches:
   ```bash
   bench --site <site> clear-cache
   bench --site <site> clear-website-cache
   ```

### Phase 6: Verification
1. Verify HTTP 200 status and rendered Page Builder blocks for all migrated routes (`/` and every `Web Page`, blog post, and `Web Form` route).
2. Verify all downloaded `/files/...` images and SVGs return HTTP 200.
3. Verify the compiled `Website Theme` stylesheet is linked in `<head>` and returns HTTP 200.
