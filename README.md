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
| **[`erpnext-multilang-website`](./erpnext-multilang-website/SKILL.md)** | Enables multi-language (`PL \| EN`) support on an ERPNext website using URL-prefixed Page Builder pages (`/en/<slug>`), a custom `Multilingual Navbar` Web Template with language toggle, a bilingual `Headline Footer`, `Translation` DocType entries, and `preferred_language` cookie synchronization. | [`enable_erpnext_multilang.py`](./erpnext-multilang-website/scripts/enable_erpnext_multilang.py)<br>[`clone_and_translate_erpnext_pages.py`](./erpnext-multilang-website/scripts/clone_and_translate_erpnext_pages.py) |
| **[`odoo-store-to-erpnext-multilang`](./odoo-store-to-erpnext-multilang/SKILL.md)** | Migrates published Odoo `website_sale` products (`product.template` with `is_published = true`) and gallery images (`product.image`) into the official **`frappe/webshop`** and **`frappe/payments`** apps (`Item`, `Website Item`, `Item Price`, `Website Slideshow`, `Webshop Settings`, and bilingual `/shop` + `/en/shop` catalogs). | [`extract_odoo_store.py`](./odoo-store-to-erpnext-multilang/scripts/extract_odoo_store.py)<br>[`migrate_store_to_erpnext.py`](./odoo-store-to-erpnext-multilang/scripts/migrate_store_to_erpnext.py) |
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
└── odoo-crm-to-erpnext/
    ├── SKILL.md
    ├── references/
    │   └── crm-mapping.md
    └── scripts/
        ├── extract_odoo_crm.py
        └── migrate_crm_to_erpnext.py
```

---

## Author

Created by **[@matzie5](https://github.com/matzie5)**.
