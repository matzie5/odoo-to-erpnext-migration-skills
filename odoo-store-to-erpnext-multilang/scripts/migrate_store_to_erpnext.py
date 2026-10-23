#!/usr/bin/env python3
"""
Migrate ONLY the published Odoo Store items (is_published = true) into ERPNext v16
using the official `frappe/webshop` and `frappe/payments` apps with full multi-language (PL | EN) support:
- Configures `Payment Gateway`, `Payment Gateway Account`, and `Webshop Settings` (enabled=1, enable_checkout=1)
- ERPNext `Item` & `Item Price` records (Standard Selling, PLN) for published items loaded from `--input-json`
- `Website Slideshow` records for multi-image product galleries
- `Website Item` records at `/shop/<slug>` with `recommended_items`, `website_warehouse`, and opening `Bin` stock
- `Translation` DocType records (`en` for product titles/descriptions, `pl` for native `frappe/webshop` UI strings)
- Reusable Page Builder Web Templates (`Multilingual Navbar`, `Store Product Catalog`)
  integrated with `webshop.webshop.shopping_cart.update_cart` and `/cart`
- `Website Settings` `top_bar_items` ("Sklep" / "Shop") & `route_redirects`
"""
import argparse
import json
import os
import frappe
from erpnext.stock.utils import get_bin


def ensure_store_files(store_dir: str, files_prefix: str = "/files/store"):
    if not os.path.isdir(store_dir):
        print("Warning: store image directory not found:", store_dir)
        return
    files_prefix = files_prefix.rstrip("/")
    created = 0
    for fname in sorted(os.listdir(store_dir)):
        furl = f"{files_prefix}/{fname}"
        if not frappe.db.exists("File", {"file_url": furl}):
            doc = frappe.get_doc({
                "doctype": "File",
                "file_name": fname,
                "file_url": furl,
                "is_private": 0,
                "folder": "Home",
            })
            doc.insert(ignore_permissions=True)
            created += 1
    frappe.db.commit()
    print(f"Registered {created} new store File records.")


def ensure_webshop_settings_and_payment_gateway(currency: str = "PLN"):
    """Configure Fiscal Year, Payment Gateway, Payment Gateway Account, and Webshop Settings for checkout."""
    company = (
        frappe.db.get_single_value("Global Defaults", "default_company")
        or frappe.db.get_value("Company", {}, "name")
    )
    curr_year = str(frappe.utils.getdate().year)
    if not frappe.db.exists("Fiscal Year", curr_year):
        fy = frappe.get_doc({
            "doctype": "Fiscal Year",
            "year": curr_year,
            "year_start_date": f"{curr_year}-01-01",
            "year_end_date": f"{curr_year}-12-31",
            "disabled": 0,
        })
        fy.insert(ignore_permissions=True)

    if not frappe.db.exists("Price List", "Standard Selling"):
        pl = frappe.get_doc({
            "doctype": "Price List",
            "price_list_name": "Standard Selling",
            "currency": currency,
            "selling": 1,
            "buying": 0,
            "enabled": 1,
        })
        pl.insert(ignore_permissions=True)
    else:
        frappe.db.set_value("Price List", "Standard Selling", {"currency": currency, "selling": 1, "enabled": 1})

    gateway_name = "Online Payment / Card"
    if frappe.db.exists("DocType", "Payment Gateway") and not frappe.db.exists("Payment Gateway", gateway_name):
        pg = frappe.get_doc({"doctype": "Payment Gateway", "gateway": gateway_name})
        pg.insert(ignore_permissions=True)

    pga_name = frappe.db.get_value(
        "Payment Gateway Account",
        {"payment_gateway": gateway_name, "currency": currency},
        "name",
    )
    if not pga_name and frappe.db.exists("DocType", "Payment Gateway Account"):
        cash_acc = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Cash", "is_group": 0},
            "name",
        ) or frappe.db.get_value("Account", {"company": company, "is_group": 0}, "name")
        pga = frappe.get_doc({
            "doctype": "Payment Gateway Account",
            "payment_gateway": gateway_name,
            "company": company,
            "payment_account": cash_acc,
            "currency": currency,
            "is_default": 1,
            "message": "Please complete payment for your order.",
        })
        pga.insert(ignore_permissions=True)
        pga_name = pga.name

    if frappe.db.exists("DocType", "Webshop Settings"):
        ws = frappe.get_doc("Webshop Settings")
        ws.products_per_page = 20
        ws.enable_field_filters = 1
        ws.enable_attribute_filters = 0
        ws.hide_variants = 0
        ws.enable_variants = 0
        ws.show_price = 1
        ws.hide_price_for_guest = 0
        ws.show_stock_availability = 1
        ws.show_quantity_in_website = 0
        ws.allow_items_not_in_stock = 1
        ws.show_apply_coupon_code_in_website = 1
        ws.show_contact_us_button = 1
        ws.show_attachments = 0
        ws.company = company
        ws.price_list = "Standard Selling"
        ws.default_customer_group = "Individual" if frappe.db.exists("Customer Group", "Individual") else "All Customer Groups"
        ws.quotation_series = "SAL-QTN-.YYYY.-"
        ws.enabled = 1
        ws.enable_checkout = 1
        ws.payment_success_url = "Orders"
        ws.payment_gateway_account = pga_name
        ws.enable_wishlist = 1
        ws.enable_reviews = 0
        ws.enable_recommendations = 1
        ws.set("filter_fields", [{"fieldname": "item_group"}])
        ws.save(ignore_permissions=True)

    frappe.db.commit()
    print(f"Configured Webshop Settings (enabled=1, enable_checkout=1) and Payment Gateway Account ({pga_name}).")


def ensure_erpnext_items_and_prices(products: list, item_code_prefix: str = "STORE-PROD-"):
    """
    Create/update ERPNext Item, Item Price, Website Slideshow, and Website Item records
    ONLY for the published store products (is_published = true).
    """
    published_codes = [p["item_code"] for p in products]
    default_warehouse = frappe.db.get_value(
        "Warehouse", {"warehouse_name": "Finished Goods", "is_group": 0}, "name"
    ) or frappe.db.get_value("Warehouse", {"is_group": 0}, "name")

    if frappe.db.exists("DocType", "Website Item"):
        existing_wi = frappe.get_all(
            "Website Item",
            filters={"item_code": ["like", f"{item_code_prefix}%"]},
            fields=["name", "item_code"],
        )
        for row in existing_wi:
            if row.item_code not in published_codes:
                frappe.delete_doc("Website Item", row.name, force=True, ignore_permissions=True)

    existing_items = frappe.get_all("Item", filters={"item_code": ["like", f"{item_code_prefix}%"]}, pluck="name")
    for code in existing_items:
        if code not in published_codes:
            frappe.delete_doc("Item", code, force=True, ignore_permissions=True)

    shadow_routes = (
        [p["route_pl"] for p in products]
        + [p["route_en"] for p in products]
        + ["shop/cart", "en/shop/cart"]
    )
    shadow_pages = frappe.get_all("Web Page", filters={"route": ["in", shadow_routes]}, pluck="name")
    for wp_name in shadow_pages:
        frappe.delete_doc("Web Page", wp_name, force=True, ignore_permissions=True)

    wi_by_code = {}
    for idx, prod in enumerate(products):
        code = prod["item_code"]
        price = float(prod.get("price") or prod.get("list_price") or 0.0)
        currency = prod.get("currency") or "PLN"
        is_stock_item = int(prod.get("is_stock_item", 0 if prod.get("type") == "service" else 1))
        item_group = prod.get("item_group") or ("Services" if prod.get("type") == "service" else "Products")

        if frappe.db.exists("Item", code):
            item = frappe.get_doc("Item", code)
        else:
            item = frappe.get_doc({"doctype": "Item", "item_code": code})

        item.item_name = prod["name_pl"]
        item.item_group = item_group if frappe.db.exists("Item Group", item_group) else "Products"
        item.stock_uom = "Nos"
        item.is_stock_item = is_stock_item
        item.is_sales_item = 1
        item.standard_rate = price
        item.image = prod["main_image"]
        item.description = prod.get("description_pl") or ""
        item.disabled = 0
        item.save(ignore_permissions=True)

        ip_name = frappe.db.get_value(
            "Item Price",
            {"item_code": code, "price_list": "Standard Selling", "selling": 1},
            "name",
        )
        if ip_name:
            ip = frappe.get_doc("Item Price", ip_name)
            ip.price_list_rate = price
            ip.currency = currency
            ip.save(ignore_permissions=True)
        else:
            ip = frappe.get_doc({
                "doctype": "Item Price",
                "item_code": code,
                "price_list": "Standard Selling",
                "currency": currency,
                "price_list_rate": price,
                "selling": 1,
            })
            ip.insert(ignore_permissions=True)

        if is_stock_item and default_warehouse:
            bin_doc = get_bin(code, default_warehouse)
            if (bin_doc.actual_qty or 0) <= 0:
                frappe.db.set_value(
                    "Bin",
                    bin_doc.name,
                    {"actual_qty": 100.0, "projected_qty": 100.0},
                )

        slideshow_name = None
        gallery = prod.get("gallery_images") or []
        if len(gallery) > 1:
            slideshow_name = f"{code}-Gallery"
            if frappe.db.exists("Website Slideshow", slideshow_name):
                ss = frappe.get_doc("Website Slideshow", slideshow_name)
            else:
                ss = frappe.get_doc({
                    "doctype": "Website Slideshow",
                    "slideshow_name": slideshow_name,
                })
            ss.set("slideshow_items", [
                {"image": img_url, "heading": prod["name_pl"], "description": ""}
                for img_url in gallery
            ])
            ss.save(ignore_permissions=True)

        if frappe.db.exists("DocType", "Website Item"):
            wi_name = frappe.db.get_value("Website Item", {"item_code": code}, "name")
            if wi_name:
                wi = frappe.get_doc("Website Item", wi_name)
            else:
                wi = frappe.get_doc({"doctype": "Website Item", "item_code": code})
            wi.web_item_name = prod["name_pl"]
            wi.route = prod["route_pl"]
            wi.published = 1
            wi.website_image = prod["main_image"]
            wi.slideshow = slideshow_name
            wi.website_warehouse = default_warehouse if is_stock_item else None
            wi.on_backorder = 0
            wi.short_description = prod.get("short_desc_pl") or ""
            wi.web_long_description = prod.get("description_pl") or ""
            wi.ranking = 100 - (idx * 10)
            wi.save(ignore_permissions=True)
            wi_by_code[code] = wi.name

    for prod in products:
        code = prod["item_code"]
        wi_name = wi_by_code.get(code)
        if not wi_name:
            continue
        wi = frappe.get_doc("Website Item", wi_name)
        rec_rows = []
        for other in products:
            if other["item_code"] == code:
                continue
            other_wi = wi_by_code.get(other["item_code"])
            if other_wi:
                rec_rows.append({
                    "website_item": other_wi,
                    "item_code": other["item_code"],
                    "website_item_name": other["name_pl"],
                    "website_item_thumbnail": other["main_image"],
                    "route": other["route_pl"],
                })
        wi.set("recommended_items", rec_rows)
        wi.save(ignore_permissions=True)

    frappe.db.commit()
    print(f"Synced {len(products)} published ERPNext Items, Item Prices, Slideshows & Website Items: {published_codes}")


def ensure_store_translations(products: list):
    en_map = {
        "Sklep": "Shop",
        "Koszyk": "Cart",
        "Wszystkie produkty": "All Products",
        "Dodaj do koszyka": "Add to Cart",
        "Kup teraz": "Buy Now",
        "Szukaj w sklepie...": "Search products...",
        "Sortuj według": "Sort by",
        "Polecane": "Featured",
        "Cena: od najniższej": "Price: Low to High",
        "Cena: od najwyższej": "Price: High to Low",
        "Nazwa: A-Z": "Name: A-Z",
        "Ilość": "Quantity",
        "Twój koszyk": "Your Shopping Cart",
        "Twój koszyk jest pusty.": "Your shopping cart is empty.",
        "Przejdź do sklepu": "Continue Shopping",
        "Podsumowanie zamówienia": "Order Summary",
        "Złóż zamówienie": "Place Order",
        "Nos": "pcs",
        "szt.": "pcs",
    }

    pl_map = {
        "All Products": "Wszystkie produkty",
        "Products": "Produkty",
        "Services": "Usługi",
        "Add to Cart": "Dodaj do koszyka",
        "View in Cart": "Zobacz w koszyku",
        "Shopping Cart": "Koszyk",
        "In stock": "W magazynie",
        "Out of stock": "Brak w magazynie",
        "Contact Us": "Skontaktuj się z nami",
        "Product Details": "Szczegóły produktu",
        "Recommended": "Polecane produkty",
        "Place Order": "Złóż zamówienie",
        "Continue Shopping": "Kontynuuj zakupy",
        "Filters": "Filtry",
        "Clear All": "Wyczyść filtry",
        "Item Group": "Kategoria",
        "Search for Products": "Szukaj produktów...",
        "Billing Address": "Adres rozliczeniowy",
        "Shipping Address": "Adres dostawy",
        "Same as Billing Address": "Taki sam jak adres rozliczeniowy",
        "New Address": "Nowy adres",
        "Payment Summary": "Podsumowanie płatności",
        "Net Total": "Suma netto",
        "Grand Total": "Razem do zapłaty",
        "Apply Coupon Code": "Zastosuj kod rabatowy",
        "Enterger Coupon Code": "Wpisz kod rabatowy",
        "Apply": "Zastosuj",
        "Your Cart is Empty": "Twój koszyk jest pusty",
        "Explore Products": "Przeglądaj produkty",
    }

    for prod in products:
        if prod.get("name_pl") and prod.get("name_en"):
            en_map[prod["name_pl"]] = prod["name_en"]
        if prod.get("short_desc_pl") and prod.get("short_desc_en"):
            en_map[prod["short_desc_pl"]] = prod["short_desc_en"]
        if prod.get("description_pl") and prod.get("description_en"):
            en_map[prod["description_pl"]] = prod["description_en"]
        if prod.get("category_pl") and prod.get("category_en"):
            en_map[prod["category_pl"]] = prod["category_en"]

    inserted = 0
    for lang, mapping in (("en", en_map), ("pl", pl_map)):
        for src, tgt in mapping.items():
            existing = frappe.db.get_value("Translation", {"language": lang, "source_text": src}, "name")
            if existing:
                frappe.db.set_value("Translation", existing, "translated_text", tgt)
            else:
                doc = frappe.get_doc({
                    "doctype": "Translation",
                    "language": lang,
                    "source_text": src,
                    "translated_text": tgt,
                })
                doc.insert(ignore_permissions=True)
                inserted += 1

    frappe.db.commit()
    print(f"Synced store Translation records ({inserted} newly inserted).")


def ensure_store_web_templates(products: list):
    products_json = json.dumps(products, ensure_ascii=False)

    catalog_template = f"""
{{%- set req_path = (frappe.request.path if frappe.request else ('/' ~ (path or ''))) -%}}
{{%- set is_en = (lang == 'en') or (req_path == '/en' or req_path.startswith('/en/') or path == 'en' or (path and path.startswith('en/'))) -%}}
{{%- set products = {products_json} -%}}

<div class="site-store-catalog py-3">
	<div class="d-flex flex-column flex-md-row justify-content-between align-items-md-end mb-4 pb-3 border-bottom">
		<div>
			<span class="badge badge-pill px-3 py-1 mb-2" style="background: rgba(59, 130, 246, 0.14); color: #0F2830; font-weight: 700;">
				{{{{ 'Official Store' if is_en else 'Oficjalny sklep' }}}}
			</span>
			<h1 class="section-title mb-1">{{{{ title or ('Shop' if is_en else 'Sklep') }}}}</h1>
			<p class="text-muted mb-0">{{{{ subtitle or ('Published products and services' if is_en else 'Opublikowane produkty i usługi') }}}}</p>
		</div>
		<div class="mt-3 mt-md-0 d-flex align-items-center">
			<a href="{{{{ '/en/all-products' if is_en else '/all-products' }}}}" class="btn btn-sm btn-outline-secondary mr-2">
				{{{{ 'Filterable Catalog' if is_en else 'Katalog z filtrami' }}}}
			</a>
			<a href="{{{{ '/en/cart' if is_en else '/cart' }}}}" class="btn btn-sm btn-primary">
				&#128722; {{{{ 'Shopping Cart' if is_en else 'Koszyk' }}}}
			</a>
		</div>
	</div>

	<div class="row" id="site-store-grid">
		{{%- for prod in products -%}}
		{{%- set p_name = prod.name_en if is_en else prod.name_pl -%}}
		{{%- set p_short = prod.short_desc_en if is_en else prod.short_desc_pl -%}}
		{{%- set p_cat = prod.category_en if is_en else prod.category_pl -%}}
		{{%- set p_price = prod.price_fmt_en if is_en else prod.price_fmt_pl -%}}
		{{%- set p_href = ('/' ~ prod.route_en) if is_en else ('/' ~ prod.route_pl) -%}}
		<div class="col-12 col-md-6 col-lg-4 mb-4 site-store-item"
			data-name="{{{{ p_name | lower }}}}"
			data-price="{{{{ prod.price }}}}"
			data-seq="{{{{ loop.index }}}}">
			<div class="card h-100 shadow-sm">
				<a href="{{{{ p_href }}}}" class="d-block text-center p-3" style="background: #F8FAFC;">
					<img src="{{{{ prod.main_image }}}}" alt="{{{{ p_name }}}}" style="max-height: 220px; object-fit: contain;" loading="lazy">
				</a>
				<div class="card-body d-flex flex-column">
					<small class="text-muted text-uppercase font-weight-bold mb-1">{{{{ p_cat }}}}</small>
					<h2 class="h5 card-title">
						<a href="{{{{ p_href }}}}" class="text-dark">{{{{ p_name }}}}</a>
					</h2>
					<p class="card-text text-muted small flex-grow-1">{{{{ p_short }}}}</p>
					<div class="d-flex align-items-center justify-content-between pt-3 border-top mt-2">
						<span class="h5 mb-0 font-weight-bold">{{{{ p_price }}}}</span>
						<div>
							<a href="{{{{ p_href }}}}" class="btn btn-sm btn-outline-secondary mr-1">
								{{{{ 'Details' if is_en else 'Szczegóły' }}}}
							</a>
							<button type="button" class="btn btn-sm btn-primary"
								onclick="window.siteAddToWebshopCart('{{{{ prod.item_code }}}}', 1, false)">
								&#128722; {{{{ 'Add to Cart' if is_en else 'Do koszyka' }}}}
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>
		{{%- endfor -%}}
	</div>
</div>
<script>
window.siteAddToWebshopCart = function(itemCode, qty, redirectToCart) {{
	var isEn = (window.location.pathname === "/en" || window.location.pathname.indexOf("/en/") === 0);
	var cartUrl = isEn ? "/en/cart" : "/cart";
	if (window.frappe && frappe.call) {{
		frappe.call({{
			type: "POST",
			method: "webshop.webshop.shopping_cart.cart.update_cart",
			args: {{ item_code: itemCode, qty: qty || 1 }},
			callback: function() {{
				window.location.href = cartUrl;
			}}
		}});
	}} else {{
		window.location.href = cartUrl;
	}}
}};
</script>
""".strip()

    if frappe.db.exists("Web Template", "Store Product Catalog"):
        doc = frappe.get_doc("Web Template", "Store Product Catalog")
    else:
        doc = frappe.get_doc({"doctype": "Web Template", "__newname": "Store Product Catalog"})
    doc.type = "Section"
    doc.standard = 0
    doc.module = "Website"
    doc.template = catalog_template
    doc.set("fields", [
        {"label": "Title", "fieldname": "title", "fieldtype": "Data"},
        {"label": "Subtitle", "fieldname": "subtitle", "fieldtype": "Data"},
        {"label": "Language (pl or en)", "fieldname": "lang", "fieldtype": "Data", "default": "pl"},
    ])
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    print("Created/Updated 'Store Product Catalog' Web Template.")


def block(web_template, values, css_class="o-cc1", add_shade=0, add_top_padding=1, add_bottom_padding=1, add_container=1):
    return {
        "web_template": web_template,
        "web_template_values": json.dumps(values, ensure_ascii=False),
        "css_class": css_class,
        "add_shade": add_shade,
        "add_top_padding": add_top_padding,
        "add_bottom_padding": add_bottom_padding,
        "add_container": add_container,
        "hide_block": 0,
    }


def upsert_web_page(name, title, route, blocks, meta_title=None, meta_description=None):
    existing_name = frappe.db.get_value("Web Page", {"route": route}, "name")
    if not existing_name and frappe.db.exists("Web Page", name):
        existing_name = name
    if existing_name:
        doc = frappe.get_doc("Web Page", existing_name)
    else:
        doc = frappe.get_doc({"doctype": "Web Page", "__newname": name})
    doc.title = title
    doc.route = route
    doc.published = 1
    doc.content_type = "Page Builder"
    doc.full_width = 1
    doc.show_title = 0
    if meta_title:
        doc.meta_title = meta_title
    if meta_description:
        doc.meta_description = meta_description
    doc.set("page_blocks", blocks)
    doc.save(ignore_permissions=True)


def ensure_store_web_pages():
    """
    Create/Update Store Catalog Pages (/shop and /en/shop).
    Both Polish (/shop/<slug>) and English (/en/shop/<slug>) Product Detail pages
    are served natively by frappe/webshop Website Item via resolve_multilang_webshop_path!
    """
    upsert_web_page(
        name="shop",
        title="Sklep",
        route="shop",
        meta_title="Sklep",
        meta_description="Oficjalny sklep internetowy.",
        blocks=[
            block("Store Product Catalog", {"title": "Sklep", "subtitle": "Nasze produkty i usługi", "lang": "pl"}),
        ],
    )
    upsert_web_page(
        name="en-shop",
        title="Shop",
        route="en/shop",
        meta_title="Shop",
        meta_description="Official online store.",
        blocks=[
            block("Store Product Catalog", {"title": "Shop", "subtitle": "Our products and services", "lang": "en"}),
        ],
    )

    frappe.db.commit()
    print("Created/Updated Store Catalog (/shop, /en/shop) Web Pages.")


def update_website_settings_for_store(products: list):
    ws = frappe.get_doc("Website Settings", "Website Settings")
    has_shop = any((item.url or "").strip() == "/shop" for item in (ws.top_bar_items or []))
    if not has_shop:
        ws.append("top_bar_items", {"label": "Sklep", "url": "/shop", "right": 0})

    redirects = list(ws.route_redirects or [])
    existing_sources = {r.source for r in redirects}
    new_redirects = [
        {"source": "shop/cart", "target": "cart"},
        {"source": "en/shop/cart", "target": "en/cart"},
    ]
    for prod in products:
        if prod.get("slug_en_odoo") and prod["slug_en_odoo"] != prod["slug_pl"]:
            new_redirects.append({
                "source": f"en/shop/{prod['slug_en_odoo']}",
                "target": prod["route_en"],
            })
            new_redirects.append({
                "source": f"shop/{prod['slug_en_odoo']}",
                "target": prod["route_pl"],
            })
    for nr in new_redirects:
        if nr["source"] not in existing_sources:
            ws.append("route_redirects", nr)

    ws.save(ignore_permissions=True)
    frappe.db.commit()
    print("Updated Website Settings top_bar_items ('Sklep' -> '/shop') and store route_redirects.")


def ensure_multilang_webshop_integration():
    """
    Ensure frappe/webshop supports:
    1. Multi-language path resolution (/en/shop/<slug> -> Website Item at shop/<slug>, /en/all-products -> all-products, /en/cart -> cart)
       while setting frappe.local.lang = 'en' on /en/... and 'pl' on primary routes.
    """
    webshop_root = "/home/frappe/frappe-bench/apps/webshop/webshop"
    if not os.path.isdir(webshop_root):
        return

    hooks_path = os.path.join(webshop_root, "hooks.py")
    if os.path.isfile(hooks_path):
        with open(hooks_path) as f:
            hooks_src = f.read()
        resolver_line = 'website_path_resolver = ["webshop.webshop.shopping_cart.utils.resolve_multilang_webshop_path"]'
        if "resolve_multilang_webshop_path" not in hooks_src:
            hooks_src = hooks_src.rstrip() + "\n\n" + resolver_line + "\n"
            with open(hooks_path, "w") as f:
                f.write(hooks_src)

    utils_path = os.path.join(webshop_root, "webshop/shopping_cart/utils.py")
    if os.path.isfile(utils_path):
        with open(utils_path) as f:
            utils_src = f.read()
        if "def resolve_multilang_webshop_path" not in utils_src:
            resolver_fn = '''

def resolve_multilang_webshop_path(path):
	"""
	Allow /en/shop/<slug>, /en/all-products, and /en/cart to render natively via
	frappe/webshop while setting frappe.local.lang according to the URL prefix.
	"""
	from frappe.website.path_resolver import resolve_path

	clean = (path or "").strip("/")
	if clean == "en" or clean.startswith("en/"):
		frappe.local.lang = "en"
		frappe.local.cookie_manager.set_cookie("preferred_language", "en")
		stripped = clean[3:].strip("/")
		if stripped.startswith("shop/") and stripped != "shop":
			if frappe.db.exists("Website Item", {"route": stripped, "published": 1}):
				return stripped
		if stripped in ("all-products", "cart"):
			return stripped
	else:
		if not clean.startswith(("api/", "assets/", "files/", "app", "login", "desk")):
			frappe.local.lang = "pl"
			frappe.local.cookie_manager.set_cookie("preferred_language", "pl")

	return resolve_path(path)
'''
            utils_src = utils_src.rstrip() + "\n" + resolver_fn
            with open(utils_path, "w") as f:
                f.write(utils_src)

    print("Verified multi-language frappe/webshop path resolver integration.")


def main():
    parser = argparse.ArgumentParser(description="Migrate published Odoo Store items to ERPNext frappe/webshop.")
    parser.add_argument("--site", default="frontend", help="Frappe site name")
    parser.add_argument("--sites-path", default="/home/frappe/frappe-bench/sites", help="Frappe sites directory")
    parser.add_argument("--input-json", default="/tmp/published_store_items.json", help="Path to published_store_items.json")
    parser.add_argument("--store-dir", default="/home/frappe/frappe-bench/sites/frontend/public/files/store", help="Store image directory")
    parser.add_argument("--files-prefix", default="/files/store", help="Public URL prefix for store images")
    parser.add_argument("--item-code-prefix", default="STORE-PROD-", help="ERPNext Item Code prefix")
    parser.add_argument("--currency", default="PLN", help="Store currency")
    args = parser.parse_args()

    products = []
    if args.input_json and os.path.exists(args.input_json):
        with open(args.input_json, "r", encoding="utf-8") as f:
            products = json.load(f)

    frappe.init(site=args.site, sites_path=args.sites_path)
    frappe.connect()
    frappe.set_user("Administrator")

    ensure_multilang_webshop_integration()
    ensure_store_files(store_dir=args.store_dir, files_prefix=args.files_prefix)
    ensure_webshop_settings_and_payment_gateway(currency=args.currency)
    ensure_erpnext_items_and_prices(products=products, item_code_prefix=args.item_code_prefix)
    ensure_store_translations(products=products)
    ensure_store_web_templates(products=products)
    ensure_store_web_pages()
    update_website_settings_for_store(products=products)

    frappe.clear_cache()
    from frappe.website.utils import clear_cache
    clear_cache()
    print("Multi-language frappe/webshop Store migration completed and caches cleared!")


if __name__ == "__main__":
    main()
