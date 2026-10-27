# Odoo `website_sale` to ERPNext (`frappe/webshop` + `frappe/payments`) Multi-Language Store Mapping Reference

## 1. Filtering Only Published Store Items in Odoo

In Odoo 16–18 (`website_sale`), `product_template` holds both internal/backend items (delivery rows, event tickets, unpublished drafts) and public e-commerce items.
Always filter using:

```sql
SELECT
    pt.id,
    pt.website_id,
    pt.is_published,
    pt.website_sequence,
    pt.type,
    pt.list_price,
    pt.default_code,
    pt.name,
    pt.description_sale,
    pt.description_ecommerce,
    pt.website_meta_title,
    pt.website_meta_description
FROM product_template pt
WHERE pt.is_published = true
  AND (pt.website_id = :website_id OR pt.website_id IS NULL)
ORDER BY pt.website_sequence, pt.id;
```

### Example Published Products Mapping

| Odoo `product_template.id` | `website_id` | `is_published` | `type` | `list_price` (PLN) | Primary Name (`pl_PL`) | Secondary Name (`en_US`) | Native `Website Item` Route (PL) | English Counterpart Route (EN) |
|---|---|---|---|---|---|---|---|---|
| `10` | `NULL` | `true` | `service` | `150.00` | Konsultacja online (60 min.) | Online Consultation (60 min) | `/shop/konsultacja-online-60-min-10` | `/en/shop/konsultacja-online-60-min-10` |
| `12` | `1` | `true` | `consu` | `100.00` | Zestaw startowy | Starter Kit | `/shop/zestaw-startowy-12` | `/en/shop/zestaw-startowy-12` |

*(Unpublished items with `is_published = false` or `NULL` are excluded.)*

---

## 2. Odoo-to-ERPNext (`frappe/webshop` + `frappe/payments`) DocType Mapping

| Odoo Source | ERPNext / Webshop Target DocType | Field Mapping |
|---|---|---|
| `product_template` (`is_published = true`) | `Item` | `item_code = f"STORE-PROD-{id}"`, `item_name = name['pl_PL']`, `description = description_ecommerce['pl_PL']`, `item_group = "Services" if type == "service" else "Products"`, `is_stock_item = 0 if type == "service" else 1`, `is_sales_item = 1`, `standard_rate = list_price`, `image = main_image_url` |
| `product_template.list_price` + `product_pricelist` | `Item Price` | `item_code`, `price_list = "Standard Selling"`, `currency = "PLN"`, `price_list_rate = list_price`, `selling = 1` |
| `product.image` (`product_tmpl_id`) | `Website Slideshow` | `slideshow_name = f"STORE-PROD-{id}-Gallery"`, `slideshow_items = [{"image": url, "heading": name_pl}]` |
| `product_template` (`is_published = true`) | `Website Item` (`webshop`) | `item_code`, `web_item_name = name['pl_PL']`, `route = f"shop/{slug_pl}"`, `published = 1`, `website_image = main_image`, `slideshow = f"STORE-PROD-{id}-Gallery"`, `website_warehouse = default_warehouse`, `short_description`, `web_long_description`, `recommended_items` |
| `website` / `payment.provider` | `Webshop Settings` + `Payment Gateway Account` (`webshop` + `payments`) | `enabled = 1`, `enable_checkout = 1`, `company`, `price_list = "Standard Selling"`, `default_customer_group = "Individual"`, `quotation_series = "SAL-QTN-.YYYY.-"`, `payment_gateway_account` |
| `product_template.name->>'en_US'`, `description_ecommerce->>'en_US'` | `Translation` (`language = 'en'` & `'pl'`) | Exact source/target mappings for product titles, short descriptions, full HTML descriptions, and `frappe/webshop` UI strings |
| `/shop` & `/en/shop` | `Web Page` + `Store Product Catalog` (`Web Template`) | Bilingual catalog with search, sorting, link to `/all-products` (`/en/all-products`), and Add-to-Cart buttons calling `webshop.webshop.shopping_cart.update_cart` |
| `/shop/<slug>` & `/en/shop/<slug>` | Native `Website Item` (`frappe/webshop`) + `resolve_multilang_webshop_path` | Both Polish and English product URLs render natively via `Website Item` (`templates/generators/item/item.html`), with `frappe.local.lang` set to `'pl'` or `'en'` by `resolve_multilang_webshop_path` and empty `.product-container.col-9` suppressed when `has_additional_info` is false |
| `/cart`, `/en/cart`, `/all-products`, `/en/all-products` | Native `frappe/webshop` pages | Filterable catalog and shopping cart (`Quotation` -> `Sales Order` -> `Payment Request` checkout) in both PL and EN |
| `delivery.carrier` (Physical Goods Delivery) | `Shipping Rule` + Service `Item` (`IHC-DELIVERY-COURIER`) | `Shipping Rule` (`name = "Dostawa kurierem"`, `shipping_rule_type = "Selling"`, `calculate_based_on = "Fixed"`, `shipping_amount = 15.00 PLN` gross) paired with Service `Item` `IHC-DELIVERY-COURIER` (`is_stock_item = 0`, `published_in_website = 0`, unpublished `Website Item` `published = 0`, `Item Price = 15.00 PLN`). Automatically appended to `Quotation`, `Sales Order`, and `Sales Invoice` whenever the cart contains any physical product (`is_stock_item = 1`), with dynamic ancillary VAT matching under Polish VAT law (`Art. 29a ust. 1 i 6 ustawy o VAT`) |

