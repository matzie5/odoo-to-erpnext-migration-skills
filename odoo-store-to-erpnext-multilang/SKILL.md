---
name: odoo-store-to-erpnext-multilang
description: Migrate published e-commerce store items (website_sale product.template with is_published=true) from Odoo to ERPNext using the official frappe/webshop and frappe/payments apps with full multi-language (PL | EN) support, including Website Item, Website Slideshow, Webshop Settings, Payment Gateway Account, ERPNext Item and Item Price records, Translation records, and bilingual Store Catalog (/shop, /en/shop, /all-products), Product Detail (/shop/<slug>, /en/shop/<slug>), and Checkout (/cart) integration.
---

# Odoo Store to ERPNext Multi-Language Migration Skill (`frappe/webshop` + `frappe/payments`)

## Purpose

Migrate an Odoo e-commerce store (`website_sale`) into ERPNext v15/v16 using the official **`frappe/webshop`** and **`frappe/payments`** apps with full multi-language (`PL | EN` or any primary/secondary language pair) support, **strictly filtering to published store items (`product_template.is_published = true`)**.

This skill bridges:
1. **`frappe/payments` & `frappe/webshop` Installation and Checkout Configuration**:
   - Installs `payments` (`version-16`) and `webshop` (`version-16`) on the ERPNext site and syncs built assets across backend/frontend/worker containers.
   - Configures active **`Fiscal Year`**, **`Payment Gateway`**, **`Payment Gateway Account`**, and **`Webshop Settings`** (`enabled = 1`, `enable_checkout = 1`, `price_list = "Standard Selling"`, `quotation_series = "SAL-QTN-.YYYY.-"`, `allow_items_not_in_stock = 1`, `enable_recommendations = 1`, `enable_wishlist = 1`).
   - Enables the complete native `frappe/webshop` checkout pipeline:
     - `webshop.webshop.shopping_cart.update_cart` -> server-side Shopping Cart **`Quotation`**
     - `/cart` (`place_order`) -> **`Sales Order`**
     - `/orders/<SO-name>` (`make_payment_request`) -> **`Payment Request`** via **`Payment Gateway Account`** (`payments` app).
2. **ERPNext Inventory, Pricing, `Website Item` & `Website Slideshow` (Published Items Only)**:
   - Migrates only published `product_template` rows (`WHERE is_published = true AND (website_id = <target_website_id> OR website_id IS NULL)`) into ERPNext **`Item`**, **`Item Price`**, **`Website Slideshow`** (for multi-image product galleries), and **`Website Item`** DocTypes (plus opening **`Bin`** stock in `Finished Goods` for physical stock items).
   - Serves BOTH Polish (`/shop/<slug>`) AND English (`/en/shop/<slug>`) product detail pages natively via `frappe/webshop`'s **`Website Item`** (`templates/generators/item/item.html`) using a `website_path_resolver` hook (`resolve_multilang_webshop_path` in `webshop/shopping_cart/utils.py`), as well as `/all-products` / `/en/all-products` and `/cart` / `/en/cart`.
   - Eliminates the empty white `.product-container.col-9` box below `Website Item` pages in `templates/generators/item/item.html` when specifications, tabs, `website_content`, and reviews are empty/disabled (`has_additional_info = False`), and expands `.recommended-item-section` to full width (`col-12 px-0`).
   - Seeds **`Translation`** DocType records (`language = "en"` for product titles, short descriptions, and full HTML descriptions; `language = "pl"` for native `frappe/webshop` UI strings).
3. **Multi-Language Storefront (`/shop`, `/en/shop`, `/shop/<slug>`, `/en/shop/<slug>`, `/cart`, `/en/cart`)**:
   - Provides **`Store Product Catalog`** (`/shop` and `/en/shop`) Page Builder `Web Template` wired directly to `webshop.webshop.shopping_cart.update_cart` (`window.siteAddToWebshopCart`) and `/cart` (`/en/cart`), while keeping `Multilingual Navbar`'s `#cart-count` badge synchronized with `frappe/webshop`'s `cart_count` cookie.

---

## Core Rules

1. **Only Migrate Published Store Items (`is_published = true`)**:
   - Always filter `product_template` with `WHERE pt.is_published = true AND (pt.website_id = :website_id OR pt.website_id = NULL)`.
   - Never migrate internal/unpublished products (`is_published = false` or `is_published IS NULL`, such as internal event registrations, delivery methods, or draft workshops) into `Item` or `Website Item`.
2. **Do Not Shadow `Website Item` (`/shop/<slug>`, `/en/shop/<slug>`) or `/cart` Routes with `Web Page` Records**:
   - In Frappe's router, `Web Page` takes precedence over `WebsiteGenerator` (`Website Item`). Ensure no `Web Page` exists at `shop/<polish-slug>`, `en/shop/<polish-slug>`, or `cart` so `Website Item` renders both `/shop/<polish-slug>` and `/en/shop/<polish-slug>` natively (via `resolve_multilang_webshop_path`) and `webshop` renders `/cart` and `/en/cart` natively.
   - Note that in Frappe's `PathResolver.resolve()`, registering `website_path_resolver` in `hooks.py` runs *instead* of the default `resolve_path(self.path)`, so `resolve_multilang_webshop_path(path)` must delegate to `from frappe.website.path_resolver import resolve_path` for all non-webshop paths.
3. **Avoid Empty `.product-container.col-9` Below `Website Item`**:
   - By default, `webshop/templates/generators/item/item.html` renders `<div class="product-container mt-4 {{ padding_top }} {{ info_col }}">` inside `<div class="d-flex">` alongside `.recommended-item-section` even when specifications, tabs, `website_content`, and reviews are all empty/disabled, creating a large blank white box. Guard that block with `{% if has_additional_info %}` and expand `.recommended-item-section` to `col-12 px-0` when `not has_additional_info`.
4. **Ensure an Active `Fiscal Year` Exists**:
   - `webshop.webshop.shopping_cart.cart.update_cart` creates a `Quotation`, which validates `transaction_date` against `Fiscal Year`. Always ensure an active `Fiscal Year` exists for the current calendar year.

---

## Step-by-Step Workflow

### Step 1: Ensure `frappe/payments` and `frappe/webshop` Are Installed
Inside `erpnext-backend-1` (from `/home/frappe/frappe-bench`):
```bash
bench get-app --branch version-16 https://github.com/frappe/payments.git
bench get-app --branch version-16 https://github.com/frappe/webshop.git
bench --site frontend install-app payments
bench --site frontend install-app webshop
```
*(Sync `apps/payments`, `apps/webshop`, and `sites/assets` to `erpnext-frontend-1`, `erpnext-scheduler-1`, and `erpnext-websocket-1` if running multi-container Docker).*

### Step 2: Extract Published Store Products & Images from Odoo
Run [`scripts/extract_odoo_store.py`](scripts/extract_odoo_store.py) to query `product_template`, `product_product`, and `product.image` for published items (`is_published = true`) and download all main and gallery images from Odoo (`http://localhost:8069`):

```bash
python3 scripts/extract_odoo_store.py \
  --db-container odoo-db \
  --db-name odoo \
  --website-id 1 \
  --odoo-url http://localhost:8069 \
  --output-dir /tmp/odoo_store_extract
```

### Step 3: Copy Product Images into ERPNext & Run `frappe/webshop` Store Migration
Copy the downloaded images into the ERPNext site's public files directory and execute [`scripts/migrate_store_to_erpnext.py`](scripts/migrate_store_to_erpnext.py) inside `erpnext-backend-1` (with `-w /home/frappe/frappe-bench/sites`):

```bash
docker exec erpnext-backend-1 mkdir -p /home/frappe/frappe-bench/sites/frontend/public/files/store
docker cp /tmp/odoo_store_extract/images/. erpnext-backend-1:/home/frappe/frappe-bench/sites/frontend/public/files/store/
docker cp /tmp/odoo_store_extract/published_store_items.json erpnext-backend-1:/tmp/published_store_items.json
docker cp scripts/migrate_store_to_erpnext.py erpnext-backend-1:/tmp/migrate_store_to_erpnext.py
docker exec -w /home/frappe/frappe-bench/sites erpnext-backend-1 /home/frappe/frappe-bench/env/bin/python /tmp/migrate_store_to_erpnext.py --input-json /tmp/published_store_items.json
```

### Step 4: Verify `frappe/webshop` Records, Checkout & Bilingual Routes
1. Confirm `Item`, `Item Price`, and `Website Item` records in ERPNext contain only the published store products (`STORE-PROD-<id>`).
2. Verify HTTP `200` across all `frappe/webshop` and bilingual store routes:
   - `/all-products` (native `frappe/webshop` filterable catalog)
   - `/cart` (native `frappe/webshop` shopping cart & checkout)
   - `/shop` ↔ `/en/shop`
   - `/shop/<product-slug>` (native `Website Item`) ↔ `/en/shop/<product-slug>`

---

## References & Scripts
- Field & Schema Mapping Reference: [`references/store-mapping.md`](references/store-mapping.md)
- Odoo Published Store Extractor: [`scripts/extract_odoo_store.py`](scripts/extract_odoo_store.py)
- ERPNext Multilingual `frappe/webshop` Migrator: [`scripts/migrate_store_to_erpnext.py`](scripts/migrate_store_to_erpnext.py)
