# Odoo CE to ERPNext v16 Migration Skills

A collection of reusable AI agent skills, architecture references, and idempotent Python migration scripts for migrating from **Odoo Community Edition (CE)** to **ERPNext v16** (with **Frappe Webshop** and **Frappe CRM**).

---

## Motivation

Migrating away from **Odoo Community Edition (CE)** to a 100% open-source ERP stack like **ERPNext** often looks daunting because data and presentation logic span PostgreSQL tables, QWeb XML views, JSONB translation fields, filestore attachments, e-commerce catalogs, and CRM pipelines.

The motivation behind this repository is to provide an **easy, repeatable, agent-assisted way to migrate from Odoo CE to ERPNext v16**—preserving native editability (ERPNext Page Builder blocks, Frappe Webshop items, and Frappe CRM deals/organizations) without modifying Frappe or ERPNext core code. Using these skills, the end-to-end migration of website pages, bilingual content, published store products, and CRM opportunities/contacts was completed in **a couple of hours**.

---

## Scope & Restrictions (Proof of Concept)

> [!IMPORTANT]
> **Proof of Concept (PoC) Notice**
>
> Please keep the following scope restrictions in mind when using or adapting these skills:
> 1. **Source Language Focus (`pl_PL` / `en_US`)**: These skills and normalization rules were built around a **Polish (`pl_PL`) source system** with secondary **English (`en_US`)** multi-language support (including Polish phone extension formats, `PLN` currency defaults, and `PL | EN` language switchers).
> 2. **Module Scope (Webpage & Opportunity Tracking)**: The source Odoo CE instance was primarily used for **website content, a small published product catalog, and CRM opportunity/contact tracking**.
> 3. **Need for Stronger Guardrails on Larger Datasets**: When more data or higher-complexity modules are migrated (such as full general ledger accounting, multi-warehouse inventory, manufacturing/BOMs, complex tax rules, or large transaction histories), **stronger guardrails, schema/constraint checks, and automated evaluations of value correctness** (e.g., row-level reconciliation, financial balance assertions, and post-migration data quality audits) are required.

---

## Included Skills

| Skill | Description | Key Scripts |
| :--- | :--- | :--- |
| **[`odoo-website-to-erpnext`](./odoo-website-to-erpnext/SKILL.md)** | Migrates an Odoo website (theme, color palette, typography, navigation menus, footer, QWeb snippet pages, blog posts, web forms, and media assets) into native **ERPNext Page Builder** building blocks (`Web Template`), `Website Theme`, `Website Settings`, and `Web Form` records rather than raw HTML blobs. | [`extract_odoo_website.py`](./odoo-website-to-erpnext/scripts/extract_odoo_website.py)<br>[`migrate_to_erpnext.py`](./odoo-website-to-erpnext/scripts/migrate_to_erpnext.py) |
| **[`erpnext-multilang-website`](./erpnext-multilang-website/SKILL.md)** | Enables multi-language ($N$-language, e.g. `PL \| EN \| DE`) support on an ERPNext website using URL-prefixed Page Builder pages (`/<lang>/<slug>`), a custom `Multilingual Navbar` Web Template with a language dropdown switcher (`🌐 PL ▾`), a multilingual `Headline Footer` dropdown, `Translation` DocType entries, and `preferred_language` cookie synchronization. | [`enable_erpnext_multilang.py`](./erpnext-multilang-website/scripts/enable_erpnext_multilang.py)<br>[`clone_and_translate_erpnext_pages.py`](./erpnext-multilang-website/scripts/clone_and_translate_erpnext_pages.py) |
| **[`odoo-store-to-erpnext-multilang`](./odoo-store-to-erpnext-multilang/SKILL.md)** | Migrates published Odoo `website_sale` products (`product.template` with `is_published = true`) and gallery images (`product.image`) into the official **`frappe/webshop`** and **`frappe/payments`** apps (`Item`, `Website Item`, `Item Price`, `Website Slideshow`, `Webshop Settings`, and bilingual `/shop` + `/en/shop` catalogs). | [`extract_odoo_store.py`](./odoo-store-to-erpnext-multilang/scripts/extract_odoo_store.py)<br>[`migrate_store_to_erpnext.py`](./odoo-store-to-erpnext-multilang/scripts/migrate_store_to_erpnext.py) |
| **[`odoo-surveys-to-erpnext-multilang`](./odoo-surveys-to-erpnext-multilang/SKILL.md)** | Migrates active non-draft Odoo surveys (`survey.survey`) and their non-draft responses (`> 2` answered questions) into ERPNext using native Custom DocTypes (`Survey`, `Survey Response`), bilingual `Web Form`s (`/surveys/<slug>` and `/en/surveys/<slug>`), client/server scoring & grading, and bilingual `/surveys` + `/en/surveys` catalog pages. | [`extract_odoo_surveys.py`](./odoo-surveys-to-erpnext-multilang/scripts/extract_odoo_surveys.py)<br>[`migrate_surveys_to_erpnext.py`](./odoo-surveys-to-erpnext-multilang/scripts/migrate_surveys_to_erpnext.py) |
| **[`odoo-crm-to-erpnext`](./odoo-crm-to-erpnext/SKILL.md)** | Migrates CRM data (`res.partner`, `crm.lead`, `crm.stage`, `crm.lost.reason`, `crm.tag`, `mail.message`, `mail.activity`, `ir.attachment`) into both **ERPNext CRM** (`Customer`, `Contact`, `Address`, `Opportunity`, `ToDo`, `Kanban Board`) and the standalone **Frappe CRM (`frappe/crm`)** app (`CRM Organization`, `CRM Deal`, `FCRM Note`, `CRM Task`). | [`extract_odoo_crm.py`](./odoo-crm-to-erpnext/scripts/extract_odoo_crm.py)<br>[`migrate_crm_to_erpnext.py`](./odoo-crm-to-erpnext/scripts/migrate_crm_to_erpnext.py) |

---

## Architecture Highlights

- **100% Configuration & Database Driven**: Zero edits to Frappe, ERPNext, Webshop, or Frappe CRM Python/JS core files. Everything is stored in the MariaDB site database (`tabWeb Template`, `tabWeb Page`, `tabWebsite Item`, `tabOpportunity`, `tabCRM Deal`, `tabCustom Field`, `tabTranslation`, etc.) and the `sites/frontend/public/files/` directory—making the target state trivial to snapshot, containerize, and replicate.
- **Two-Stage Extract & Load Pipeline**:
  1. **Extract**: Query Odoo PostgreSQL + filestore (or live HTTP endpoints) into clean, portable JSON bundles and downloaded media directories.
  2. **Load**: Run idempotent Frappe ORM scripts inside the `erpnext-backend` container to upsert master data, translations, pages, products, customers, contacts, and deals.

---

## Repository Structure

```text
.
├── README.md
├── odoo-website-to-erpnext/
│   ├── SKILL.md
│   ├── references/
│   │   └── snippet-mapping.md
│   └── scripts/
│       ├── extract_odoo_website.py
│       └── migrate_to_erpnext.py
├── erpnext-multilang-website/
│   ├── SKILL.md
│   ├── references/
│   │   └── multilang-architecture.md
│   └── scripts/
│       ├── clone_and_translate_erpnext_pages.py
│       └── enable_erpnext_multilang.py
├── odoo-store-to-erpnext-multilang/
│   ├── SKILL.md
│   ├── references/
│   │   └── store-mapping.md
│   └── scripts/
│       ├── extract_odoo_store.py
│       └── migrate_store_to_erpnext.py
├── odoo-surveys-to-erpnext-multilang/
│   ├── SKILL.md
│   ├── references/
│   │   └── survey-mapping.md
│   └── scripts/
│       ├── extract_odoo_surveys.py
│       └── migrate_surveys_to_erpnext.py
└── odoo-crm-to-erpnext/
    ├── SKILL.md
    ├── references/
    │   └── crm-mapping.md
    └── scripts/
        ├── extract_odoo_crm.py
        └── migrate_crm_to_erpnext.py
```

---

## How You Port the Config Change (Dev $\rightarrow$ Staging $\rightarrow$ Prod)

There is an important distinction between **Pre-Launch** (initial migration/setup) and **Post-Launch** (once Production has live CRM deals, contacts, or shop orders):

| Stage | How to Port Config Changes | Why |
| :--- | :--- | :--- |
| **A. Pre-Launch (Initial Setup)** | **Full Backup & Restore** (`import-from-dev.sh`) | Dev is the single source of truth for everything. Restoring the full DB + files snapshot moves 100% of pages, items, CRM data, and settings at once. |
| **B. Post-Launch: Small Content Fix** *(e.g. typo, wrong link, swapped image)* | **Edit directly in Production CMS** *(optionally test in Dev/Staging first)* | In ERPNext, `Web Page`, `Blog Post`, and `Website Item` are content documents (like WordPress pages). You cannot overwrite the Prod DB with a Dev DB dump after launch because Prod has new live CRM leads and shop orders. For a quick content fix, edit it in the Prod CMS UI—your next `pull-from-prod.sh` brings it back to Dev automatically. |
| **C. Post-Launch: Larger Config / Redesign in Dev** *(e.g. new Web Page, new Web Template, Website Theme SCSS changes, Custom Fields)* | **Selective Document Sync (`bench export-json` / `bench import-doc`)** | Exports **only** the specific configuration documents (`Web Page`, `Web Template`, `Website Theme`, `Website Settings`, `Translation`, `Custom Field`) + `/files/` from Dev as JSON and imports them into Staging/Prod, leaving live CRM Deals, Contacts, Customers, and Orders untouched. |

### Instructions for Approach C: Selective Config Sync (`export-json` / `import-doc`)

Frappe includes first-class CLI commands (`bench --site frontend export-json` and `bench --site frontend import-doc`) backed by `frappe.core.doctype.data_import.data_import`. They serialize any document **including all of its child table rows** (such as `Web Page Block` rows inside a `Web Page`, or `top_bar_items` inside `Website Settings`) and upsert them on the target environment with `force=True` without touching any other database tables.

#### 1. Export Specific Configuration Documents from Dev (`erpnext-backend-1`)

```bash
# 1. Create export folder inside Dev container
sudo docker exec erpnext-backend-1 mkdir -p /tmp/cms_export

# 2. Export specific Web Pages (includes all child Web Page Blocks)
sudo docker exec erpnext-backend-1 bash -c \
  "cd /home/frappe/frappe-bench && \
   bench --site frontend export-json 'Web Page' /tmp/cms_export/web_page_home_pl.json --name instytut-higieny-cyfrowej && \
   bench --site frontend export-json 'Web Page' /tmp/cms_export/web_page_home_en.json --name digital-hygiene-institute"

# (Optional) Or export ALL Web Pages, custom Web Templates, Translations, and Website Themes at once:
sudo docker exec erpnext-backend-1 bash -c \
  "cd /home/frappe/frappe-bench && \
   bench --site frontend export-json 'Web Page' /tmp/cms_export/all_web_pages.json && \
   bench --site frontend export-json 'Web Template' /tmp/cms_export/all_web_templates.json && \
   bench --site frontend export-json 'Website Theme' /tmp/cms_export/website_themes.json && \
   bench --site frontend export-json 'Translation' /tmp/cms_export/translations.json && \
   /home/frappe/frappe-bench/env/bin/python -c '
import json
p = \"/tmp/cms_export/all_web_templates.json\"
data = [d for d in json.load(open(p)) if not d.get(\"standard\")]
json.dump(data, open(p, \"w\"), indent=2)
'"

# (Optional) Export a Single DocType such as Website Settings (pass '--name -'):
sudo docker exec erpnext-backend-1 bash -c \
  "cd /home/frappe/frappe-bench && \
   bench --site frontend export-json 'Website Settings' /tmp/cms_export/website_settings.json --name -"

# 3. Copy the exported JSON bundle to the host
mkdir -p ~/erpnext-staging/cms_export
sudo docker cp erpnext-backend-1:/tmp/cms_export/. ~/erpnext-staging/cms_export/
```

#### 2. Sync Public Media Files (`/files/`) and `File` Records (If New Images Were Added)

```bash
# Export File DocType records from Dev
sudo docker exec erpnext-backend-1 bash -c \
  "cd /home/frappe/frappe-bench && \
   bench --site frontend export-json 'File' /tmp/cms_export/files_meta.json"
sudo docker cp erpnext-backend-1:/tmp/cms_export/files_meta.json ~/erpnext-staging/cms_export/

# Copy the physical public/files directory from Dev to host
mkdir -p ~/erpnext-staging/cms_export/public_files
sudo docker cp erpnext-backend-1:/home/frappe/frappe-bench/sites/frontend/public/files/. \
  ~/erpnext-staging/cms_export/public_files/
```

#### 3. Import into Staging (`erpnext-staging-backend-1`) or Production

```bash
# 1. Copy JSON files (and optional public_files) into the target backend container
sudo docker cp ~/erpnext-staging/cms_export \
  erpnext-staging-backend-1:/tmp/cms_export

# (If syncing physical media files) Copy public files into sites/frontend/public/files/
sudo docker exec -u root erpnext-staging-backend-1 bash -c \
  "if [ -d /tmp/cms_export/public_files ]; then \
     cp -rn /tmp/cms_export/public_files/* /home/frappe/frappe-bench/sites/frontend/public/files/ 2>/dev/null || true; \
     chown -R frappe:frappe /home/frappe/frappe-bench/sites/frontend/public/files; \
   fi"

# 2. Import all JSON files in /tmp/cms_export and clear caches
sudo docker exec erpnext-staging-backend-1 bash -c \
  "cd /home/frappe/frappe-bench && \
   bench --site frontend import-doc /tmp/cms_export && \
   bench --site frontend clear-cache && \
   bench --site frontend clear-website-cache && \
   rm -rf /tmp/cms_export"
```

---

## How to Add Additional Languages to the Public Website (e.g. German `de`)

All custom `Web Template`s (`Multilingual Navbar`, `Headline Footer`, `Contact and Inquiry Form`, `Dynamic Blog Posts Grid`, `Store Product Catalog`, `Store Product Detail`, and `Store Shopping Cart and Checkout`) are generalized for $N$ languages and render a **dropdown language switcher** (`🌐 PL ▾` in the top navbar and `🌐 Polski (PL)` in the footer). No template code changes are required to add a 3rd or 4th language:

1. **Add the Language in `Website Settings`**:
   - Open `/app/website-settings` → **Header / Navbar** → under `Navbar Template` (`Multilingual Navbar`), click **Edit Values**.
   - Append `,de:Deutsch` to **Supported Languages (code:Label)** (`pl:Polski,en:English,de:Deutsch`) and save.
2. **Add `Translation` Records (`/app/translation`)**:
   - Create `Translation` entries with `Language = de` for navbar/footer labels, shared UI strings (use existing `Language = en` entries as your checklist), and store product titles/descriptions.
3. **Clone & Translate `Web Page`s under `/de/...`**:
   - Create Page Builder pages with `route = de` (homepage), `route = de/<original-slug>` (content & store pages), and `route = de/blog/<blog-slug>`, or run:
     ```bash
     sudo docker cp ~/.agents/skills/erpnext-multilang-website/scripts/clone_and_translate_erpnext_pages.py \
       erpnext-backend-1:/tmp/clone_and_translate_erpnext_pages.py
     sudo docker exec -w /home/frappe/frappe-bench/sites erpnext-backend-1 \
       /home/frappe/frappe-bench/env/bin/python /tmp/clone_and_translate_erpnext_pages.py --target-lang de
     ```
4. **(Optional) Add Route Redirects**:
   - Add convenience aliases in `Website Settings` → **Redirects** (e.g. `de/sklep` $\rightarrow$ `/de/shop`).

---

## Author

Created by **[@matzie5](https://github.com/matzie5)**.
