#!/usr/bin/env python3
"""
Generic Odoo Website to ERPNext v16 Migration Script.

Reads the JSON bundle produced by `extract_odoo_website.py` (`website_data.json` + `asset_map.json`)
and migrates:
1. File records for all downloaded images, PDFs, and colorized SVG shapes
2. Color records and Website Theme (with Odoo color combinations .o-cc1..o-cc5, sticky navbar, CTA & Split Section overrides)
3. Reusable custom Web Templates (`Showcase with Central Image`, `Logo Marquee Grid`, `Dynamic Blog Posts Grid`, `Contact and Inquiry Form`, `Headline Footer`)
4. Decomposed QWeb `<section data-snippet="...">` blocks into ERPNext Page Builder `Web Page` documents
5. Blog posts (`blog_post`) into structured Page Builder `Web Page` articles and `Help Article` records
6. Navigation menu hierarchy (`website_menu`) and footer into `Website Settings`
"""
import argparse
import html
import json
import os
import re
import frappe
from bs4 import BeautifulSoup


def ensure_file_records(assets_dir: str, assets_prefix: str = "/files/website"):
    if not os.path.isdir(assets_dir):
        print("Warning: assets dir not found:", assets_dir)
        return
    count = 0
    for fname in sorted(os.listdir(assets_dir)):
        furl = f"{assets_prefix.rstrip('/')}/{fname}"
        if not frappe.db.exists("File", {"file_url": furl}):
            doc = frappe.get_doc({
                "doctype": "File",
                "file_name": fname,
                "file_url": furl,
                "is_private": 0,
                "folder": "Home",
            })
            doc.flags.copy_from_existing_file = True
            doc.insert(ignore_permissions=True)
            count += 1
    frappe.db.commit()
    print(f"Registered {count} new File records in ERPNext.")


def ensure_colors_and_theme(theme_name: str, palette: dict, heading_font: str = "Quicksand", body_font: str = "Montserrat"):
    c1 = palette.get("o-color-1", "#3B82F6")
    c2 = palette.get("o-color-2", "#F59E0B")
    c3 = palette.get("o-color-3", "#F8FAFC")
    c4 = palette.get("o-color-4", "#FFFFFF")
    c5 = palette.get("o-color-5", "#0F172A")

    colors = {
        f"{theme_name} Primary": c1,
        f"{theme_name} Secondary": c2,
        f"{theme_name} Light": c3,
        f"{theme_name} White": c4,
        f"{theme_name} Dark": c5,
    }
    for name, hex_val in colors.items():
        if not frappe.db.exists("Color", name):
            doc = frappe.get_doc({"doctype": "Color", "__newname": name, "color": hex_val})
            doc.insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Color", name, "color", hex_val)

    custom_overrides = f"""
$font-family-sans-serif: "{body_font}", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
$headings-font-family: "{heading_font}", "{body_font}", sans-serif;
$headings-font-weight: 600;
$primary: {c1};
$secondary: {c2};
$light: {c3};
$dark: {c5};
$body-color: {c5};
$body-bg: {c4};
$border-radius: 0.5rem;
$border-radius-lg: 0.85rem;
$border-radius-sm: 0.375rem;
""".strip()

    custom_scss = f"""
@import url("https://fonts.googleapis.com/css2?family={heading_font.replace(' ', '+')}:wght@500;600;700&display=swap");

body {{
    color: {c5};
    background-color: {c4};
    font-family: "{body_font}", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.65;
}}

h1, h2, h3, h4, h5, h6,
.hero-title, .section-title, .card-title, .feature-title {{
    font-family: "{heading_font}", "{body_font}", sans-serif;
    font-weight: 600;
    color: inherit;
}}

.btn {{
    border-radius: 10rem !important;
    font-weight: 600;
    padding: 0.6rem 1.6rem;
    transition: all 0.2s ease-in-out;
}}

.btn-primary, .btn-dark {{
    background-color: {c1} !important;
    border-color: {c1} !important;
    color: {c4} !important;
}}

.btn-secondary, .btn-primary-light {{
    background-color: {c2} !important;
    border-color: {c2} !important;
    color: {c5} !important;
}}

/* Sticky Navbar */
html {{
    scroll-padding-top: 5rem;
}}
.navbar {{
    position: sticky !important;
    top: 0 !important;
    z-index: 1030 !important;
    width: 100%;
    background-color: rgba(255, 255, 255, 0.97) !important;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    box-shadow: 0 2px 12px rgba(15, 40, 48, 0.08);
    padding-top: 0.75rem;
    padding-bottom: 0.75rem;
}}
.navbar-brand img {{
    max-height: 48px !important;
    width: auto !important;
}}

/* Odoo Color Combination Classes (o_cc1 .. o_cc5) */
.o-cc1 {{
    background-color: {c4} !important;
    color: {c5} !important;
}}
.o-cc2, .section-with-shade {{
    background-color: {c3} !important;
    color: {c5} !important;
}}
.o-cc3 {{
    background-color: {c1} !important;
    color: {c4} !important;
}}
.o-cc3 h1, .o-cc3 h2, .o-cc3 h3, .o-cc3 h4, .o-cc3 p, .o-cc3 .section-title, .o-cc3 .section-description, .o-cc3 .title, .o-cc3 .subtitle {{
    color: {c4} !important;
}}
.o-cc4 {{
    background-color: {c2} !important;
    color: {c5} !important;
}}
.o-cc5 {{
    background-color: {c5} !important;
    color: {c4} !important;
}}
.o-cc5 h1, .o-cc5 h2, .o-cc5 h3, .o-cc5 h4, .o-cc5 p, .o-cc5 .section-title, .o-cc5 .section-description, .o-cc5 .title, .o-cc5 .subtitle {{
    color: {c4} !important;
}}

/* Page Builder Section Refinements */
.section-padding-top {{
    padding-top: 2.5rem !important;
    @media (min-width: 768px) {{
        padding-top: 3.5rem !important;
    }}
}}
.section-padding-bottom {{
    padding-bottom: 2.5rem !important;
    @media (min-width: 768px) {{
        padding-bottom: 3.5rem !important;
    }}
}}

.split-section-with-image {{
    align-items: center;
    .split-section-image {{
        display: block;
        margin-left: auto;
        margin-right: auto;
        max-width: 340px;
        width: 100%;
    }}
    .split-section-content {{
        margin-top: 0 !important;
    }}
    @media (max-width: 767.98px) {{
        > div {{
            flex: 0 0 100% !important;
            max-width: 100% !important;
            order: 1 !important;
        }}
        > div.split-section-content {{
            order: 2 !important;
            margin-top: 1.5rem !important;
        }}
    }}
}}

.section-with-features .section-features {{
    margin-top: 2.25rem !important;
    gap: 2rem !important;
}}
.section-feature {{
    background: {c4};
    border-radius: 1rem;
    padding: 1.75rem;
    border: 1px solid rgba(15, 40, 48, 0.07);
    box-shadow: 0 2px 10px rgba(15, 40, 48, 0.04);
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}}

/* CTA section (Odoo s_cta_box and s_call_to_action) */
.section-cta-container {{
    background: transparent !important;
    padding: 0 !important;
}}
.section-cta {{
    background-color: {c1} !important;
    color: {c4} !important;
    border-radius: 0.75rem !important;
    padding: 2.25rem 2rem !important;
    text-align: center;
    .title, .subtitle {{
        color: {c4} !important;
    }}
}}
.o-cc5 .section-small-cta,
.o-cc5 .section-cta {{
    background-color: transparent !important;
    box-shadow: none !important;
    padding: 0.5rem 0 !important;
}}

/* Footer layout */
html, body {{
    min-height: 100vh;
    height: auto !important;
}}
.web-footer {{
    background-color: {c5} !important;
    color: {c4} !important;
    border-top: none !important;
    padding-top: 3rem;
    padding-bottom: 1.5rem;
    flex-shrink: 0 !important;
    height: auto !important;
    min-height: fit-content !important;
}}
""".strip()

    if frappe.db.exists("Website Theme", theme_name):
        doc = frappe.get_doc("Website Theme", theme_name)
    else:
        doc = frappe.get_doc({"doctype": "Website Theme", "theme": theme_name})

    doc.custom = 1
    doc.module = "Website"
    doc.google_font = body_font
    doc.font_properties = "wght@400;500;600;700"
    doc.primary_color = f"{theme_name} Primary"
    doc.dark_color = f"{theme_name} Dark"
    doc.light_color = f"{theme_name} Light"
    doc.text_color = f"{theme_name} Dark"
    doc.background_color = f"{theme_name} White"
    doc.button_rounded_corners = 1
    doc.button_shadows = 0
    doc.button_gradients = 0
    doc.custom_overrides = custom_overrides
    doc.custom_scss = custom_scss
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"Saved Website Theme '{theme_name}' -> {doc.theme_url}")
    return theme_name


def ensure_custom_web_templates(brand_name: str = "My Organization"):
    """Create reusable custom Web Templates (standard=0) for Odoo patterns not in built-in blocks."""
    templates = [
        {
            "name": "Showcase with Central Image",
            "type": "Section",
            "fields": [
                {"label": "Title", "fieldname": "title", "fieldtype": "Data"},
                {"label": "Subtitle", "fieldname": "subtitle", "fieldtype": "Text"},
                {"label": "Central Image", "fieldname": "image", "fieldtype": "Attach Image"},
                {"label": "CTA Label", "fieldname": "cta_label", "fieldtype": "Data"},
                {"label": "CTA URL", "fieldname": "cta_url", "fieldtype": "Data"},
                {"label": "Features", "fieldname": "features", "fieldtype": "Table Break"},
                {"label": "Feature Title", "fieldname": "feature_title", "fieldtype": "Data"},
                {"label": "Feature Content", "fieldname": "feature_content", "fieldtype": "Text"},
                {"label": "Feature URL", "fieldname": "feature_url", "fieldtype": "Data"},
            ],
            "template": """
<div class="odoo-showcase py-4">
    <div class="text-center mb-5">
        {%- if title -%}<h2 class="section-title">{{ title }}</h2>{%- endif -%}
        {%- if subtitle -%}<p class="section-description mx-auto" style="max-width: 760px;">{{ subtitle }}</p>{%- endif -%}
    </div>
    <div class="row align-items-center">
        <div class="col-lg-6">
            <div class="row">
                {%- for feat in features or [] -%}
                <div class="col-12 mb-4">
                    <div class="section-feature h-100">
                        <h3 class="feature-title h5 mt-0">
                            {%- if feat.feature_url -%}<a href="{{ feat.feature_url }}">{{ feat.feature_title }}</a>{%- else -%}{{ feat.feature_title }}{%- endif -%}
                        </h3>
                        <p class="feature-content mb-0">{{ feat.feature_content }}</p>
                    </div>
                </div>
                {%- endfor -%}
            </div>
        </div>
        <div class="col-lg-6 text-center mt-4 mt-lg-0">
            {%- if image -%}<img src="{{ image }}" alt="{{ title or '' }}" class="img-fluid" style="max-height: 380px;" loading="lazy" />{%- endif -%}
            {%- if cta_label and cta_url -%}
            <div class="mt-4"><a href="{{ cta_url }}" class="btn btn-primary btn-lg">{{ cta_label }}</a></div>
            {%- endif -%}
        </div>
    </div>
</div>
""".strip(),
        },
        {
            "name": "Logo Marquee Grid",
            "type": "Section",
            "fields": [
                {"label": "Title", "fieldname": "title", "fieldtype": "Data"},
                {"label": "Subtitle", "fieldname": "subtitle", "fieldtype": "Data"},
                {"label": "Logos", "fieldname": "logos", "fieldtype": "Table Break"},
                {"label": "Partner Name", "fieldname": "partner_name", "fieldtype": "Data"},
                {"label": "Logo Image", "fieldname": "logo_image", "fieldtype": "Attach Image"},
                {"label": "Partner URL", "fieldname": "partner_url", "fieldtype": "Data"},
            ],
            "template": """
<div class="odoo-partners-section py-3">
    {%- if title -%}<h2 class="section-title text-center mb-2">{{ title }}</h2>{%- endif -%}
    {%- if subtitle -%}<p class="section-description text-center mb-4">{{ subtitle }}</p>{%- endif -%}
    <div class="row mt-4 justify-content-center">
        {%- for item in logos or [] -%}
        <div class="col-6 col-sm-4 col-md-3 col-lg-2 mb-4 text-center">
            <div class="card p-3 h-100 d-flex align-items-center justify-content-center">
                {%- if item.logo_image -%}<img src="{{ item.logo_image }}" alt="{{ item.partner_name or '' }}" class="img-fluid" style="max-height: 64px;" loading="lazy" />{%- endif -%}
                {%- if item.partner_name -%}<small class="mt-2 font-weight-bold">{{ item.partner_name }}</small>{%- endif -%}
            </div>
        </div>
        {%- endfor -%}
    </div>
</div>
""".strip(),
        },
        {
            "name": "Dynamic Blog Posts Grid",
            "type": "Section",
            "fields": [
                {"label": "Title", "fieldname": "title", "fieldtype": "Data"},
                {"label": "Subtitle", "fieldname": "subtitle", "fieldtype": "Data"},
                {"label": "Posts", "fieldname": "posts", "fieldtype": "Table Break"},
                {"label": "Post Title", "fieldname": "post_title", "fieldtype": "Data"},
                {"label": "Post Subtitle", "fieldname": "post_subtitle", "fieldtype": "Small Text"},
                {"label": "Cover Image", "fieldname": "cover_image", "fieldtype": "Attach Image"},
                {"label": "Post Route", "fieldname": "post_route", "fieldtype": "Data"},
                {"label": "Published Date", "fieldname": "published_date", "fieldtype": "Data"},
            ],
            "template": f"""
<div class="section-with-cards py-3">
    {{%- if title -%}}<h1 class="section-title text-center mb-2">{{{{ title }}}}</h1>{{%- endif -%}}
    {{%- if subtitle -%}}<p class="section-description text-center mb-5">{{{{ subtitle }}}}</p>{{%- endif -%}}
    <div class="row">
        {{%- for post in posts or [] -%}}
        <div class="col-12 col-md-6 col-lg-4 mb-4">
            <div class="card h-100">
                {{%- if post.cover_image -%}}
                <img src="{{{{ post.cover_image }}}}" class="card-img-top" alt="{{{{ post.post_title }}}}" loading="lazy" />
                {{%- endif -%}}
                <div class="card-body d-flex flex-column">
                    {{%- if post.published_date -%}}<small class="text-muted mb-2">{{{{ post.published_date }}}}</small>{{%- endif -%}}
                    <h3 class="card-title h5 mt-0">{{{{ post.post_title }}}}</h3>
                    {{%- if post.post_subtitle -%}}<p class="card-text text-muted flex-grow-1">{{{{ post.post_subtitle }}}}</p>{{%- endif -%}}
                    <div class="mt-3"><span class="font-weight-bold">{{{{ _("Read more") }}}} →</span></div>
                </div>
                <a href="{{{{ post.post_route }}}}" class="stretched-link"></a>
            </div>
        </div>
        {{%- endfor -%}}
    </div>
</div>
""".strip(),
        },
        {
            "name": "Headline Footer",
            "type": "Footer",
            "fields": [
                {"label": "Headline Title", "fieldname": "headline_title", "fieldtype": "Data"},
                {"label": "Headline Lead Text", "fieldname": "headline_lead", "fieldtype": "Small Text"},
                {"label": "Phone", "fieldname": "phone", "fieldtype": "Data"},
                {"label": "Email", "fieldname": "email", "fieldtype": "Data"},
            ],
            "template": """
{%- set raw_ftv = frappe.db.get_single_value("Website Settings", "footer_template_values") -%}
{%- set ftv = json.loads(raw_ftv) if raw_ftv else {} -%}
{%- set h_title = headline_title or ftv.get("headline_title") -%}
{%- set h_lead = headline_lead or ftv.get("headline_lead") -%}
{%- set c_phone = phone or ftv.get("phone") -%}
{%- set c_email = email or ftv.get("email") -%}

<footer class="web-footer o-cc5">
	<div class="container">
		{% if h_title or h_lead %}
		<div class="row pt-2 pb-4 align-items-start">
			<div class="col-lg-3 pb-3 pb-lg-0">
				{% if h_title %}<h4 class="mb-0 text-white">{{ h_title }}</h4>{% endif %}
			</div>
			<div class="col-lg-9">
				{% if h_lead %}<p class="lead mb-0 text-white">{{ h_lead }}</p>{% endif %}
			</div>
		</div>
		{% endif %}
		<div class="row align-items-center pb-4">
			<div class="col-lg-3 pb-3 pb-lg-0">
				{% if footer_items %}
				<ul class="pl-3 ps-3 mb-0">
					{% for item in footer_items if item.label and not item.parent_label %}
					<li class="mb-1">
						<a href="{{ item.url | abs_url }}" {% if item.open_in_new_tab %}target="_blank" rel="noreferrer"{% endif %}>{{ _(item.label) }}</a>
					</li>
					{% endfor %}
				</ul>
				{% endif %}
			</div>
			<div class="col-lg-6 pb-3 pb-lg-0">
				{% if footer_address %}
				<div>{{ footer_address }}</div>
				{% elif c_phone or c_email %}
				<ul class="list-unstyled mb-0">
					{% if c_phone %}<li class="mb-1"><small>{{ c_phone }}</small></li>{% endif %}
					{% if c_email %}<li><a href="mailto:{{ c_email }}">{{ c_email }}</a></li>{% endif %}
				</ul>
				{% endif %}
			</div>
			<div class="col-lg-3 text-lg-right">
				{% if footer_logo %}<img src="{{ footer_logo }}" alt="Footer Logo" class="footer-logo">{% endif %}
			</div>
		</div>
	</div>
</footer>
""".strip(),
        },
    ]

    for tpl in templates:
        if frappe.db.exists("Web Template", tpl["name"]):
            doc = frappe.get_doc("Web Template", tpl["name"])
        else:
            doc = frappe.get_doc({"doctype": "Web Template", "__newname": tpl["name"]})
        doc.type = tpl["type"]
        doc.standard = 0
        doc.module = "Website"
        doc.template = tpl["template"]
        doc.set("fields", tpl["fields"])
        doc.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"Created/Updated {len(templates)} custom Web Templates.")


def rewrite_asset_urls(text: str, asset_map: dict) -> str:
    if not text:
        return ""
    out = html.unescape(text)
    for orig, mapped in sorted(asset_map.items(), key=lambda x: -len(x[0])):
        out = out.replace(orig, mapped)
    return out


def parse_section_to_block(sec, asset_map: dict) -> dict:
    """Convert an Odoo QWeb <section data-snippet='...'> element into an ERPNext Page Builder Web Page Block."""
    snippet = sec.get("data-snippet") or ""
    classes = sec.get("class") or []
    css_class = "o-cc1"
    add_shade = 0
    for c in classes:
        if c in ("o_cc1", "o_cc2", "o_cc3", "o_cc4", "o_cc5"):
            css_class = c.replace("_", "-")
            if c == "o_cc2":
                add_shade = 1

    h_el = sec.find(["h1", "h2", "h3"])
    title = h_el.get_text(" ", strip=True) if h_el else ""
    p_el = sec.find("p")
    subtitle = p_el.get_text(" ", strip=True) if p_el else ""
    img_el = sec.find("img")
    img_src = rewrite_asset_urls(img_el.get("src") or "", asset_map) if img_el else ""
    btn_el = sec.find("a", class_=re.compile(r"btn"))
    cta_label = btn_el.get_text(" ", strip=True) if btn_el else ""
    cta_url = (btn_el.get("href") or "") if btn_el else ""

    if snippet in ("s_banner", "s_text_cover") and img_src:
        return {
            "web_template": "Hero with Right Image",
            "web_template_values": json.dumps({
                "title": title or "Welcome",
                "subtitle": subtitle,
                "primary_action_label": cta_label,
                "primary_action": cta_url,
                "image": img_src,
                "contain_image": 1 if img_src.endswith(".svg") else 0,
            }, ensure_ascii=False),
            "css_class": css_class,
            "add_shade": add_shade,
            "add_top_padding": 1,
            "add_bottom_padding": 1,
            "add_container": 1,
        }
    if snippet in ("s_text_image", "s_image_text", "s_image_text_box") and img_src:
        body_html = "".join(str(p) for p in sec.find_all(["p", "ul", "ol"]))
        return {
            "web_template": "Split Section with Image",
            "web_template_values": json.dumps({
                "title": title or "Section",
                "content": rewrite_asset_urls(body_html or subtitle, asset_map),
                "image": img_src,
                "image_on_right": 1 if snippet == "s_text_image" else 0,
                "split": "6 columns - 6 columns",
                "vertical_align": "Middle",
                "url_label": cta_label,
                "url": cta_url,
                "link_label": cta_label,
                "link_url": cta_url,
            }, ensure_ascii=False),
            "css_class": css_class,
            "add_shade": add_shade,
            "add_top_padding": 1,
            "add_bottom_padding": 1,
            "add_container": 1,
        }
    if snippet == "s_cta_box":
        return {
            "web_template": "Section with CTA",
            "web_template_values": json.dumps({
                "title": title or "Call to Action",
                "subtitle": subtitle,
                "cta_label": cta_label or "Contact Us",
                "cta_url": cta_url or "/contactus",
                "show_confetti": 0,
            }, ensure_ascii=False),
            "css_class": "o-cc1",
            "add_shade": 0,
            "add_top_padding": 0,
            "add_bottom_padding": 1,
            "add_container": 1,
        }
    if snippet == "s_call_to_action":
        return {
            "web_template": "Section with Small CTA",
            "web_template_values": json.dumps({
                "title": title or "Call to Action",
                "subtitle": subtitle,
                "cta_label": cta_label or "Contact Us",
                "cta_url": cta_url or "/contactus",
            }, ensure_ascii=False),
            "css_class": "o-cc5",
            "add_shade": 0,
            "add_top_padding": 1,
            "add_bottom_padding": 1,
            "add_container": 1,
        }
    if snippet in ("s_accordion_image", "s_faq_collapse"):
        items = []
        for idx, card in enumerate(sec.select(".accordion-item, .card"), start=1):
            q = card.find(["a", "button", "h4", "h5", "h6"])
            a = card.select_one(".accordion-body, .card-body")
            if q and a:
                items.append({
                    "idx": idx,
                    "title": q.get_text(" ", strip=True),
                    "content": rewrite_asset_urls(a.decode_contents(), asset_map),
                })
        if items:
            return {
                "web_template": "Section with Collapsible Content",
                "web_template_values": json.dumps({
                    "title": title,
                    "subtitle": subtitle,
                    "align": "Left",
                    "items": items,
                }, ensure_ascii=False),
                "css_class": css_class,
                "add_shade": add_shade,
                "add_top_padding": 1,
                "add_bottom_padding": 1,
                "add_container": 1,
            }

    return {
        "web_template": "Markdown",
        "web_template_values": json.dumps({
            "content": rewrite_asset_urls(sec.decode_contents(), asset_map),
        }, ensure_ascii=False),
        "css_class": css_class,
        "add_shade": add_shade,
        "add_top_padding": 1,
        "add_bottom_padding": 1,
        "add_container": 1,
    }


def migrate_pages_and_menus(data: dict, asset_map: dict, theme_name: str, brand_name: str):
    for p in data.get("pages", []):
        if not p.get("is_published", True):
            continue
        raw_url = (p.get("url") or "").strip("/")
        route = "home" if raw_url in ("", "/") else raw_url
        arch = p.get("arch_lang") or p.get("arch_en") or p.get("arch_raw") or ""
        soup = BeautifulSoup(arch, "html.parser")
        sections = soup.find_all("section")
        blocks = [parse_section_to_block(sec, asset_map) for sec in sections]
        if not blocks and arch.strip():
            blocks = [{
                "web_template": "Markdown",
                "web_template_values": json.dumps({"content": rewrite_asset_urls(arch, asset_map)}, ensure_ascii=False),
                "css_class": "o-cc1",
                "add_top_padding": 1,
                "add_bottom_padding": 1,
                "add_container": 1,
            }]
        title = p.get("view_name") or route.replace("-", " ").title()
        existing_name = frappe.db.get_value("Web Page", {"route": route}, "name")
        doc = frappe.get_doc("Web Page", existing_name) if existing_name else frappe.get_doc({"doctype": "Web Page", "__newname": route[:140]})
        doc.title = title
        doc.route = route
        doc.published = 1
        doc.content_type = "Page Builder"
        doc.full_width = 1
        doc.show_title = 0
        doc.set("page_blocks", blocks)
        doc.save(ignore_permissions=True)

    ws = frappe.get_single("Website Settings")
    ws.app_name = brand_name
    ws.home_page = "home"
    ws.website_theme = theme_name
    ws.footer_template = "Headline Footer"

    menus = data.get("menus", [])
    by_id = {m["id"]: m for m in menus}
    top_bar = []
    for m in menus:
        if m.get("parent_id") is None:
            continue
        parent = by_id.get(m["parent_id"])
        parent_label = ""
        if parent and parent.get("parent_id") is not None:
            parent_label = parent.get("name_lang") or parent.get("name_en") or ""
        label = m.get("name_lang") or m.get("name_en") or ""
        if label:
            top_bar.append({
                "label": label,
                "url": m.get("url") or "/",
                "parent_label": parent_label,
            })
    if top_bar:
        ws.set("top_bar_items", top_bar)
    ws.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"Migrated {len(data.get('pages', []))} pages and updated Website Settings.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate extracted Odoo website bundle into ERPNext.")
    parser.add_argument("--site", default="frontend", help="Frappe site name")
    parser.add_argument("--data-json", default="/tmp/odoo_website_extract/website_data.json", help="Path to website_data.json")
    parser.add_argument("--asset-map", default="/tmp/odoo_website_extract/asset_map.json", help="Path to asset_map.json")
    parser.add_argument("--assets-dir", default="/home/frappe/frappe-bench/sites/frontend/public/files/website", help="Public files dir in ERPNext")
    parser.add_argument("--assets-prefix", default="/files/website", help="Public URL prefix for migrated assets")
    parser.add_argument("--theme-name", default="Odoo Migrated Theme", help="Website Theme name")
    parser.add_argument("--brand-name", default="My Organization", help="Website Settings brand/app name")
    args = parser.parse_args()

    frappe.init(site=args.site)
    frappe.connect()

    with open(args.data_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    asset_map = {}
    if os.path.exists(args.asset_map):
        with open(args.asset_map, "r", encoding="utf-8") as f:
            asset_map = json.load(f)

    palette = {
        "o-color-1": "#3B82F6",
        "o-color-2": "#F59E0B",
        "o-color-3": "#F8FAFC",
        "o-color-4": "#FFFFFF",
        "o-color-5": "#0F172A",
    }
    ensure_file_records(args.assets_dir, args.assets_prefix)
    ensure_colors_and_theme(args.theme_name, palette)
    ensure_custom_web_templates(args.brand_name)
    migrate_pages_and_menus(data, asset_map, args.theme_name, args.brand_name)
    frappe.clear_cache()
