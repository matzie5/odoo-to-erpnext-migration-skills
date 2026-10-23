#!/usr/bin/env python3
"""
Enable Multi-Language Support (PL | EN) on an ERPNext Website.

Configures:
1. Language records (pl, en), Translation DocType entries (common UI + extracted Odoo menu/page strings),
   and Store readiness (Item / Item Group translated_doctype=1).
2. Multilingual Navbar Web Template (type='Navbar') with top PL | EN switcher, route-aware links,
   and preferred_language cookie sync.
3. Bilingual Headline Footer Web Template (type='Footer') and localized Dynamic Blog Posts Grid /
   Contact and Inquiry Form templates.
4. English Blog Posts (/en/<blog-prefix>/<slug>) and English Web Pages (/en and /en/<slug>) built
   from Odoo extracted JSON (--data-json) or cloned from existing Page Builder pages.
"""
import argparse
import html
import json
import os
import re
import frappe


def strip_tags(raw_html: str) -> str:
    if not raw_html:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(re.sub(r"\s+", " ", cleaned)).strip()


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    replacements = {
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
        "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "page"


def block(web_template, values, css_class="", add_shade=0, add_top_padding=1, add_bottom_padding=1, add_container=1):
    return {
        "web_template": web_template,
        "web_template_values": json.dumps(values, ensure_ascii=False),
        "css_class": css_class,
        "add_shade": add_shade,
        "add_top_padding": add_top_padding,
        "add_bottom_padding": add_bottom_padding,
        "add_container": add_container,
    }


def upsert_web_page(name, title, route, blocks, meta_description="", meta_image=""):
    existing_name = frappe.db.get_value("Web Page", {"route": route}, "name") or (
        name if frappe.db.exists("Web Page", name) else None
    )
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
    doc.insert_style = 0
    doc.meta_title = title
    if meta_description:
        doc.meta_description = meta_description
    if meta_image:
        doc.meta_image = meta_image
    doc.set("page_blocks", blocks)
    doc.save(ignore_permissions=True)
    return doc.name


def ensure_languages_and_translations(odoo_data=None, extra_translations=None):
    for lang_code in ("pl", "en"):
        if frappe.db.exists("Language", lang_code):
            frappe.db.set_value("Language", lang_code, "enabled", 1)

    for dt in ("Item", "Item Group"):
        if frappe.db.exists("DocType", dt):
            frappe.db.set_value("DocType", dt, "translated_doctype", 1)

    en_translations = {
        "Strona główna": "Home",
        "O nas": "About us",
        "Oferta": "Services",
        "Blog": "Blog",
        "Skontaktuj się z nami": "Contact Us",
        "Polityka Cookie": "Cookie Policy",
        "Polityka prywatności": "Privacy Policy",
        "Polityka zwrotów i odstąpienia od umowy": "Return and Withdrawal Policy",
        "Sklep": "Shop",
        "Dowiedz się więcej": "Learn more",
        "Czytaj więcej →": "Read more →",
        "Wyślij wiadomość": "Send message",
        "Dodaj do koszyka": "Add to Cart",
        "Koszyk": "Cart",
        "Kup teraz": "Buy Now",
        "Wszystkie produkty": "All Products",
        "Kategorie": "Categories",
        "Szukaj produktów": "Search products",
    }

    if odoo_data:
        for m in odoo_data.get("menus", []):
            name_obj = m.get("name")
            if isinstance(name_obj, dict):
                pl_txt = (name_obj.get("pl_PL") or "").strip()
                en_txt = (name_obj.get("en_US") or "").strip()
                if pl_txt and en_txt:
                    en_translations[pl_txt] = en_txt

    if extra_translations:
        en_translations.update(extra_translations)

    pl_translations = {
        "Learn more": "Dowiedz się więcej",
        "Read more": "Czytaj więcej",
        "Log in": "Zaloguj się",
        "My Account": "Moje konto",
        "Log out": "Wyloguj się",
    }

    count = 0
    for src, tgt in en_translations.items():
        existing = frappe.db.get_value(
            "Translation", {"language": "en", "source_text": src}, "name"
        )
        if existing:
            frappe.db.set_value("Translation", existing, "translated_text", tgt)
        else:
            doc = frappe.get_doc(
                {
                    "doctype": "Translation",
                    "language": "en",
                    "source_text": src,
                    "translated_text": tgt,
                }
            )
            doc.insert(ignore_permissions=True)
            count += 1

    for src, tgt in pl_translations.items():
        existing = frappe.db.get_value(
            "Translation", {"language": "pl", "source_text": src}, "name"
        )
        if existing:
            frappe.db.set_value("Translation", existing, "translated_text", tgt)
        else:
            doc = frappe.get_doc(
                {
                    "doctype": "Translation",
                    "language": "pl",
                    "source_text": src,
                    "translated_text": tgt,
                }
            )
            doc.insert(ignore_permissions=True)
            count += 1

    frappe.db.commit()
    print(f"Configured languages (pl, en), Store translated_doctype flags, and {count} new Translation records.")


def update_theme_with_lang_switcher():
    theme_name = frappe.db.get_single_value("Website Settings", "website_theme") or "Standard"
    if not frappe.db.exists("Website Theme", theme_name):
        return theme_name
    doc = frappe.get_doc("Website Theme", theme_name)
    switcher_scss = """
/* Sticky Navbar & Language Switcher Pill */
html {
    scroll-padding-top: 5rem;
}
.navbar {
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
    transition: box-shadow 0.2s ease, background-color 0.2s ease;
}
.site-lang-switcher {
    display: inline-flex;
    align-items: center;
    background-color: #F6F5ED;
    border: 1px solid rgba(15, 40, 48, 0.12);
    border-radius: 10rem;
    padding: 0.18rem;
    .lang-pill {
        display: inline-block;
        padding: 0.22rem 0.68rem !important;
        border-radius: 10rem;
        font-size: 0.8rem;
        font-weight: 700;
        line-height: 1.2;
        text-decoration: none !important;
        color: #0F2830 !important;
        transition: all 0.15s ease;
    }
    .lang-pill.active {
        background-color: var(--primary, #3B82F6) !important;
        color: #FFFFFF !important;
    }
    .lang-pill:not(.active):hover {
        color: var(--primary, #3B82F6) !important;
    }
}
""".strip()
    current_scss = doc.custom_scss or ""
    if "/* Sticky Navbar & Language Switcher Pill */" not in current_scss:
        doc.custom_scss = current_scss + "\n\n" + switcher_scss
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"Added sticky .navbar and .site-lang-switcher styles to Website Theme '{theme_name}'.")
    return theme_name


def ensure_multilang_web_templates():
    templates = [
        {
            "name": "Multilingual Navbar",
            "type": "Navbar",
            "fields": [
                {"label": "Primary Language Code", "fieldname": "primary_lang", "fieldtype": "Data", "default": "pl"},
                {"label": "Secondary Language Code", "fieldname": "secondary_lang", "fieldtype": "Data", "default": "en"},
                {"label": "Secondary CTA Label", "fieldname": "cta_label_en", "fieldtype": "Data", "default": "Contact Us"},
            ],
            "template": """
{%- set req_path = (frappe.request.path if frappe.request else ('/' ~ (path or ''))) -%}
{%- set is_en = (req_path == '/en' or req_path.startswith('/en/') or path == 'en' or (path and path.startswith('en/'))) -%}
{%- set curr_lang = 'en' if is_en else 'pl' -%}
{%- if is_en -%}
    {%- set stripped = req_path[3:] if req_path.startswith('/en') else '/' -%}
    {%- set pl_url = stripped if (stripped and stripped.startswith('/')) else '/' -%}
    {%- set en_url = req_path if req_path.startswith('/en') else '/en' -%}
{%- else -%}
    {%- set pl_url = '/' if (req_path in ['', '/', '/home']) else req_path -%}
    {%- set en_url = '/en' if pl_url == '/' else ('/en' ~ pl_url) -%}
{%- endif -%}
{%- set brand_href = '/en' if is_en else ( url_prefix or '/' ) -%}

<nav class="navbar navbar-light navbar-expand-lg sticky-top">
	<div class="container">
		<a class="navbar-brand" href="{{ brand_href }}">
			{%- if brand_html -%}
			{{ brand_html }}
			{%- elif banner_image -%}
			<img src="{{ banner_image | abs_url }}" alt="{{ _(app_name or 'Website', curr_lang) }}">
			{%- else -%}
			<span>{{ _(app_name or 'Website', curr_lang) }}</span>
			{%- endif -%}
		</a>
		<button class="navbar-toggler" type="button"
			data-toggle="collapse" data-target="#navbarSupportedContent"
			aria-controls="navbarSupportedContent" aria-expanded="false"
			aria-label="Toggle navigation">
			<span>
				<svg class="icon icon-lg">
					<use href="#icon-menu"></use>
				</svg>
			</span>
		</button>

		<div class="collapse navbar-collapse" id="navbarSupportedContent">
			<ul class="mr-auto navbar-nav">
				{%- for page in top_bar_items -%}
				{%- if not page.parent_label and not page.right -%}
					{%- set raw_url = page.url or '' -%}
					{%- if is_en and raw_url.startswith('/') and not raw_url.startswith('/en') and not raw_url.startswith('/files') -%}
						{%- set item_url = '/en' if raw_url in ['/', '/home'] else ('/en' ~ raw_url) -%}
					{%- else -%}
						{%- set item_url = raw_url or '#' -%}
					{%- endif -%}
					{%- set item_label = _(page.label, curr_lang) -%}
					{%- if page.child_items -%}
					<li class="nav-item dropdown">
						<a class="nav-link dropdown-toggle" href="#" id="nav-dropdown-{{ loop.index }}" role="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
							{{ item_label }}
						</a>
						<ul class="dropdown-menu" aria-labelledby="nav-dropdown-{{ loop.index }}">
							{%- for child in page.child_items -%}
							{%- set c_raw = child.url or '' -%}
							{%- if is_en and c_raw.startswith('/') and not c_raw.startswith('/en') and not c_raw.startswith('/files') -%}
								{%- set c_url = '/en' if c_raw in ['/', '/home'] else ('/en' ~ c_raw) -%}
							{%- else -%}
								{%- set c_url = c_raw | abs_url -%}
							{%- endif -%}
							<li class="dropdown-item">
								<a href="{{ c_url }}" {% if child.open_in_new_tab %}target="_blank" rel="noreferrer"{% endif %}>
									{{ _(child.label, curr_lang) }}
								</a>
							</li>
							{%- endfor -%}
						</ul>
					</li>
					{%- else -%}
					<li class="nav-item">
						<a class="nav-link" href="{{ item_url }}" {% if page.open_in_new_tab %}target="_blank" rel="noreferrer"{% endif %}>
							{{ item_label }}
						</a>
					</li>
					{%- endif -%}
				{%- endif -%}
				{%- endfor -%}
			</ul>

			<ul class="ml-auto navbar-nav align-items-lg-center">
				{%- for page in top_bar_items -%}
				{%- if not page.parent_label and page.right -%}
					{%- set raw_url = page.url or '' -%}
					{%- if is_en and raw_url.startswith('/') and not raw_url.startswith('/en') and not raw_url.startswith('/files') -%}
						{%- set item_url = '/en' if raw_url in ['/', '/home'] else ('/en' ~ raw_url) -%}
					{%- else -%}
						{%- set item_url = raw_url or '#' -%}
					{%- endif -%}
					<li class="nav-item">
						<a class="nav-link" href="{{ item_url }}" {% if page.open_in_new_tab %}target="_blank" rel="noreferrer"{% endif %}>
							{{ _(page.label, curr_lang) }}
						</a>
					</li>
				{%- endif -%}
				{%- endfor -%}

				<!-- Language Switcher (PL | EN) -->
				<li class="nav-item d-flex align-items-center my-2 my-lg-0 mr-lg-3 me-lg-3">
					<div class="site-lang-switcher" role="group" aria-label="Language switcher">
						<a href="{{ pl_url }}" class="lang-pill {{ 'active' if not is_en else '' }}" onclick="window.setSiteLangCookie('pl');" title="Polski">PL</a>
						<a href="{{ en_url }}" class="lang-pill {{ 'active' if is_en else '' }}" onclick="window.setSiteLangCookie('en');" title="English">EN</a>
					</div>
				</li>

				{%- if call_to_action -%}
				{%- set cta_raw = call_to_action_url or '/contactus' -%}
				{%- if is_en and cta_raw.startswith('/') and not cta_raw.startswith('/en') -%}
					{%- set cta_href = '/en' if cta_raw in ['/', '/home'] else ('/en' ~ cta_raw) -%}
				{%- else -%}
					{%- set cta_href = cta_raw | abs_url -%}
				{%- endif -%}
				<li class="nav-item my-2 my-lg-0">
					<a class="btn btn-primary navbar-cta mr-lg-2" href="{{ cta_href }}">
						{{ cta_label_en if is_en and cta_label_en else _(call_to_action, curr_lang) }}
					</a>
				</li>
				{%- endif -%}

				{%- if not hide_login -%}
				<li class="nav-item btn-login-area">
					<a class="nav-link" href="/login">{{ _("Login", curr_lang) }}</a>
				</li>
				{%- endif -%}
			</ul>
		</div>
	</div>
</nav>
<script>
window.setSiteLangCookie = function(lang) {
	document.cookie = "preferred_language=" + lang + "; path=/; max-age=31536000; SameSite=Lax";
};
(function() {
	var p = window.location.pathname || "/";
	var isEn = (p === "/en" || p.indexOf("/en/") === 0);
	var targetLang = isEn ? "en" : "pl";
	if (document.documentElement) {
		document.documentElement.setAttribute("lang", targetLang);
	}
	var m = document.cookie.match(/(?:^|; )preferred_language=([^;]*)/);
	if (!m || m[1] !== targetLang) {
		window.setSiteLangCookie(targetLang);
	}
})();
</script>
""".strip(),
        },
        {
            "name": "Headline Footer",
            "type": "Footer",
            "fields": [
                {"label": "Headline Title (PL)", "fieldname": "headline_title", "fieldtype": "Data"},
                {"label": "Headline Lead Text (PL)", "fieldname": "headline_lead", "fieldtype": "Small Text"},
                {"label": "Headline Title (EN)", "fieldname": "headline_title_en", "fieldtype": "Data"},
                {"label": "Headline Lead Text (EN)", "fieldname": "headline_lead_en", "fieldtype": "Small Text"},
                {"label": "Phone", "fieldname": "phone", "fieldtype": "Data"},
                {"label": "Email", "fieldname": "email", "fieldtype": "Data"},
            ],
            "template": """
{%- set req_path = (frappe.request.path if frappe.request else ('/' ~ (path or ''))) -%}
{%- set is_en = (req_path == '/en' or req_path.startswith('/en/') or path == 'en' or (path and path.startswith('en/'))) -%}
{%- set curr_lang = 'en' if is_en else 'pl' -%}
{%- if is_en -%}
    {%- set stripped = req_path[3:] if req_path.startswith('/en') else '/' -%}
    {%- set pl_url = stripped if (stripped and stripped.startswith('/')) else '/' -%}
    {%- set en_url = req_path if req_path.startswith('/en') else '/en' -%}
{%- else -%}
    {%- set pl_url = '/' if (req_path in ['', '/', '/home']) else req_path -%}
    {%- set en_url = '/en' if pl_url == '/' else ('/en' ~ pl_url) -%}
{%- endif -%}
{%- set raw_ftv = frappe.db.get_single_value("Website Settings", "footer_template_values") -%}
{%- set ftv = json.loads(raw_ftv) if raw_ftv else {} -%}
{%- if is_en -%}
    {%- set h_title = headline_title_en or ftv.get("headline_title_en") or "" -%}
    {%- set h_lead = headline_lead_en or ftv.get("headline_lead_en") or "" -%}
{%- else -%}
    {%- set h_title = headline_title or ftv.get("headline_title") or "" -%}
    {%- set h_lead = headline_lead or ftv.get("headline_lead") or "" -%}
{%- endif -%}
{%- set c_phone = phone or ftv.get("phone") -%}
{%- set c_email = email or ftv.get("email") -%}

<footer class="web-footer o-cc5 site-headline-footer">
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
				<ul class="site-footer-links pl-3 ps-3 mb-0">
					{% for item in footer_items if item.label and not item.parent_label %}
					{%- set f_raw = item.url or '' -%}
					{%- if is_en and f_raw.startswith('/') and not f_raw.startswith('/en') and not f_raw.startswith('/files') -%}
						{%- set f_url = '/en' if f_raw in ['/', '/home'] else ('/en' ~ f_raw) -%}
					{%- else -%}
						{%- set f_url = f_raw | abs_url -%}
					{%- endif -%}
					<li class="mb-1">
						<a href="{{ f_url }}" {% if item.open_in_new_tab %}target="_blank" rel="noreferrer"{% endif %}>{{ _(item.label, curr_lang) }}</a>
					</li>
					{% endfor %}
				</ul>
				{% endif %}
			</div>
			<div class="col-lg-6 pb-3 pb-lg-0">
				{% if footer_address %}
				<div class="site-footer-address">
					{{ footer_address }}
				</div>
				{% elif c_phone or c_email %}
				<ul class="list-unstyled mb-0 site-footer-address">
					{% if c_phone %}
					<li class="mb-1"><span class="mr-2 me-2">&#9742;</span><small>{{ c_phone }}</small></li>
					{% endif %}
					{% if c_email %}
					<li><span class="mr-2 me-2">&#9993;</span><a href="mailto:{{ c_email }}">{{ c_email }}</a></li>
					{% endif %}
				</ul>
				{% endif %}
			</div>
			<div class="col-lg-3 text-lg-right">
				{% if footer_logo %}
				<img src="{{ footer_logo }}" alt="Footer Logo" class="footer-logo">
				{% endif %}
			</div>
		</div>

		<div class="footer-info border-top pt-3" style="border-color: rgba(255, 255, 255, 0.15) !important;">
			<div class="row align-items-center">
				<div class="footer-col-left col-sm-6 col-12 py-1">
					{% if copyright %}
					<span class="o_footer_copyright_name">Copyright &copy; {{ _(copyright, curr_lang) }}</span>
					{% endif %}
				</div>
				<div class="footer-col-right col-sm-6 col-12 py-1 text-sm-right">
					<span class="site-footer-lang small">
						<a href="{{ pl_url }}" onclick="window.setSiteLangCookie('pl');" style="{{ 'font-weight:700; text-decoration:underline;' if not is_en else 'opacity:0.8;' }}">Polski</a>
						<span class="mx-1">|</span>
						<a href="{{ en_url }}" onclick="window.setSiteLangCookie('en');" style="{{ 'font-weight:700; text-decoration:underline;' if is_en else 'opacity:0.8;' }}">English</a>
					</span>
				</div>
			</div>
		</div>
	</div>
</footer>
<style>
html, body {
	min-height: 100vh;
	height: auto !important;
}
.web-footer.site-headline-footer {
	background-color: #0F2830 !important;
	color: #FFFFFF !important;
	border-top: none !important;
	padding-top: 3rem;
	padding-bottom: 1.5rem;
	flex-shrink: 0 !important;
	height: auto !important;
	min-height: fit-content !important;
}
.web-footer.site-headline-footer h1,
.web-footer.site-headline-footer h2,
.web-footer.site-headline-footer h3,
.web-footer.site-headline-footer h4,
.web-footer.site-headline-footer h5,
.web-footer.site-headline-footer h6,
.web-footer.site-headline-footer p,
.web-footer.site-headline-footer .lead,
.web-footer.site-headline-footer li,
.web-footer.site-headline-footer span,
.web-footer.site-headline-footer small {
	color: #FFFFFF;
}
.web-footer.site-headline-footer a,
.web-footer.site-headline-footer .footer-link {
	color: #bed693 !important;
	text-decoration: none;
}
.web-footer.site-headline-footer a:hover,
.web-footer.site-headline-footer .footer-link:hover {
	color: #9dc15c !important;
	text-decoration: underline;
}
.web-footer.site-headline-footer .site-footer-links {
	list-style-type: disc;
	padding-left: 1.25rem;
	color: #FFFFFF;
}
.web-footer.site-headline-footer .footer-info,
.web-footer.site-headline-footer .o_footer_copyright_name {
	color: rgba(255, 255, 255, 0.7) !important;
	font-size: 0.875rem;
}
</style>
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
            "template": """
{%- set req_path = (frappe.request.path if frappe.request else ('/' ~ (path or ''))) -%}
{%- set is_en = (req_path == '/en' or req_path.startswith('/en/') or path == 'en' or (path and path.startswith('en/'))) -%}
<div class="section-with-cards py-3">
    {%- if title -%}
    <h1 class="section-title text-center mb-2">{{ title }}</h1>
    {%- endif -%}
    {%- if subtitle -%}
    <p class="section-description text-center mb-5">{{ subtitle }}</p>
    {%- endif -%}
    <div class="row">
        {%- for post in posts or [] -%}
        <div class="col-12 col-md-6 col-lg-4 mb-4">
            <div class="card h-100">
                {%- if post.cover_image -%}
                <img src="{{ post.cover_image }}" class="card-img-top" alt="{{ post.post_title }}" loading="lazy" />
                {%- else -%}
                <div class="card-img-top d-flex align-items-center justify-content-center" style="height: 210px; background: linear-gradient(135deg, #0f13ff 0%, #72a2e9 61%, #b2ffda 100%); color: #fff; padding: 1.5rem; text-align: center; font-weight: 600;">
                    <span>{{ post.post_title }}</span>
                </div>
                {%- endif -%}
                <div class="card-body d-flex flex-column">
                    {%- if post.published_date -%}
                    <small class="text-muted mb-2">{{ post.published_date }}</small>
                    {%- endif -%}
                    <h3 class="card-title h5 mt-0">{{ post.post_title }}</h3>
                    {%- if post.post_subtitle -%}
                    <p class="card-text text-muted flex-grow-1">{{ post.post_subtitle }}</p>
                    {%- endif -%}
                    <div class="mt-3">
                        <span class="font-weight-bold" style="color: var(--primary, #3B82F6);">{{ 'Read more →' if is_en else 'Czytaj więcej →' }}</span>
                    </div>
                </div>
                <a href="{{ post.post_route }}" class="stretched-link"></a>
            </div>
        </div>
        {%- endfor -%}
    </div>
</div>
""".strip(),
        },
        {
            "name": "Contact and Inquiry Form",
            "type": "Section",
            "fields": [
                {"label": "Title", "fieldname": "title", "fieldtype": "Data"},
                {"label": "Subtitle", "fieldname": "subtitle", "fieldtype": "Text"},
                {"label": "Form Mode", "fieldname": "form_mode", "fieldtype": "Select", "options": "contact\nschool\nwaitlist", "default": "contact"},
                {"label": "Org Label", "fieldname": "org_label", "fieldtype": "Data", "default": "Twoja firma"},
                {"label": "Extra Field Label", "fieldname": "extra_label", "fieldtype": "Data", "default": "Temat"},
                {"label": "Extra Field Type", "fieldname": "extra_type", "fieldtype": "Data", "default": "text"},
                {"label": "Message Label", "fieldname": "message_label", "fieldtype": "Data", "default": "Twoje pytanie"},
                {"label": "Submit Button Label", "fieldname": "submit_label", "fieldtype": "Data", "default": "Wyślij wiadomość"},
                {"label": "Show Contact Sidebar", "fieldname": "show_sidebar", "fieldtype": "Check", "default": "1"},
                {"label": "Organization Name", "fieldname": "org_name", "fieldtype": "Data"},
                {"label": "Phone", "fieldname": "phone", "fieldtype": "Data"},
                {"label": "Email", "fieldname": "email", "fieldtype": "Data"},
            ],
            "template": """
{%- set req_path = (frappe.request.path if frappe.request else ('/' ~ (path or ''))) -%}
{%- set is_en = (req_path == '/en' or req_path.startswith('/en/') or path == 'en' or (path and path.startswith('en/'))) -%}
<div class="site-contact-section py-3" id="{{ 'inquiry-form' if is_en else 'formularz-kontaktowy' }}">
    {%- if title -%}
    <h2 class="section-title mb-2">{{ title }}</h2>
    {%- endif -%}
    {%- if subtitle -%}
    <p class="section-description mb-4">{{ subtitle }}</p>
    {%- endif -%}
    <div class="row">
        <div class="{{ 'col-lg-8' if show_sidebar else 'col-lg-10 mx-auto' }}">
            <div class="card p-4">
                <form class="site-inquiry-form" data-lang="{{ 'en' if is_en else 'pl' }}" onsubmit="return window.submitSiteForm(event, this);">
                    <div class="form-row row">
                        <div class="form-group col-md-6 mb-3">
                            <label class="font-weight-bold">{{ 'Your Name *' if is_en else 'Imię i nazwisko *' }}</label>
                            <input type="text" name="full_name" class="form-control" required />
                        </div>
                        <div class="form-group col-md-6 mb-3">
                            <label class="font-weight-bold">{{ 'Phone Number' if is_en else 'Numer telefonu' }}</label>
                            <input type="tel" name="phone" class="form-control" />
                        </div>
                    </div>
                    <div class="form-row row">
                        <div class="form-group col-md-6 mb-3">
                            <label class="font-weight-bold">{{ 'Your Email *' if is_en else 'Twój email *' }}</label>
                            <input type="email" name="email" class="form-control" required />
                        </div>
                        <div class="form-group col-md-6 mb-3">
                            <label class="font-weight-bold">{{ org_label or ('Your Company' if is_en else 'Twoja firma') }}</label>
                            <input type="text" name="organization" class="form-control" />
                        </div>
                    </div>
                    <div class="form-group mb-3">
                        <label class="font-weight-bold">{{ extra_label or ('Subject' if is_en else 'Temat') }} *</label>
                        <input type="{{ extra_type or 'text' }}" name="subject_extra" class="form-control" required />
                    </div>
                    <div class="form-group mb-4">
                        <label class="font-weight-bold">{{ message_label or ('Your Question' if is_en else 'Twoje pytanie') }} *</label>
                        <textarea name="message" rows="4" class="form-control" required></textarea>
                    </div>
                    <button type="submit" class="btn btn-primary btn-lg">{{ submit_label or ('Submit' if is_en else 'Wyślij wiadomość') }}</button>
                </form>
            </div>
        </div>
        {%- if show_sidebar -%}
        <div class="col-lg-4 mt-4 mt-lg-0">
            <div class="section-feature h-100">
                {%- if org_name -%}
                <h3 class="h5 mt-0 mb-3">{{ org_name }}</h3>
                {%- endif -%}
                {%- if phone -%}
                <p class="mb-2"><strong>{{ 'Phone:' if is_en else 'Telefon:' }}</strong> <a href="tel:{{ phone }}">{{ phone }}</a></p>
                {%- endif -%}
                {%- if email -%}
                <p class="mb-3"><strong>Email:</strong> <a href="mailto:{{ email }}">{{ email }}</a></p>
                {%- endif -%}
                <hr />
                <p class="text-muted small mb-0">{{ "Contact us about anything related to our company or services. We'll do our best to get back to you as soon as possible." if is_en else "Skontaktuj się z nami we wszystkim, co jest związane z naszą firmą lub usługami. Zrobimy co w naszej mocy, aby odpowiedzieć jak najszybciej." }}</p>
            </div>
        </div>
        {%- endif -%}
    </div>
</div>
<script>
window.submitSiteForm = function(e, form) {
    e.preventDefault();
    var isEn = form.getAttribute('data-lang') === 'en';
    var thankYouUrl = isEn ? '/en/contactus-thank-you' : '/contactus-thank-you';
    var btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.innerText = isEn ? 'Sending...' : 'Wysyłanie...';
    var data = new FormData(form);
    var sender = data.get('email');
    var fullName = data.get('full_name');
    var phone = data.get('phone') || '-';
    var org = data.get('organization') || '-';
    var subj = data.get('subject_extra') || (isEn ? 'Website Inquiry' : 'Zapytanie ze strony');
    var msg = 'Name: ' + fullName + '\\nPhone: ' + phone + '\\nOrganization/City: ' + org + '\\nSubject/Date: ' + subj + '\\n\\n' + (data.get('message') || '');
    if (window.frappe && frappe.call) {
        frappe.call({
            method: 'frappe.www.contact.send_message',
            args: { sender: sender, subject: subj + ' (' + fullName + ')', message: msg },
            callback: function() {
                window.location.href = thankYouUrl;
            },
            error: function() {
                window.location.href = thankYouUrl;
            }
        });
    } else {
        window.location.href = thankYouUrl;
    }
    return false;
};
</script>
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
    print(f"Created/Updated {len(templates)} multilingual Web Templates.")


def ensure_english_web_forms():
    web_forms = [
        {
            "name": "en-contact-form",
            "title": "Contact Us",
            "route": "en/contact-form",
            "doc_type": "Lead",
            "button_label": "Submit",
            "success_title": "Thank You!",
            "success_message": "Your message has been sent. We will get back to you shortly.",
            "success_url": "/en/contactus-thank-you",
            "introduction_text": "<p>Contact us about anything related to our company or services.</p>",
            "fields": [
                {"fieldname": "first_name", "fieldtype": "Data", "label": "Your Name", "reqd": 1},
                {"fieldname": "phone", "fieldtype": "Data", "label": "Phone Number", "reqd": 0},
                {"fieldname": "email_id", "fieldtype": "Data", "label": "Your Email", "reqd": 1},
                {"fieldname": "company_name", "fieldtype": "Data", "label": "Your Company", "reqd": 0},
                {"fieldname": "title", "fieldtype": "Data", "label": "Subject", "reqd": 1},
            ],
        },
    ]
    for wf in web_forms:
        existing_name = frappe.db.get_value("Web Form", {"route": wf["route"]}, "name")
        if not existing_name and frappe.db.exists("Web Form", wf["name"]):
            existing_name = wf["name"]
        if existing_name:
            doc = frappe.get_doc("Web Form", existing_name)
        else:
            doc = frappe.get_doc({"doctype": "Web Form", "__newname": wf["name"]})
        doc.title = wf["title"]
        doc.route = wf["route"]
        doc.doc_type = wf["doc_type"]
        doc.module = "Website"
        doc.published = 1
        doc.anonymous = 1
        doc.login_required = 0
        doc.allow_multiple = 1
        doc.button_label = wf["button_label"]
        doc.success_title = wf["success_title"]
        doc.success_message = wf["success_message"]
        doc.success_url = wf["success_url"]
        doc.introduction_text = wf["introduction_text"]
        doc.set("web_form_fields", wf["fields"])
        doc.save(ignore_permissions=True)
    frappe.db.commit()
    print("Configured English Web Forms.")


def parse_odoo_sections_to_blocks(arch_html: str, lang_prefix: str = "en") -> list:
    """Convert Odoo QWeb <section> elements into ERPNext Page Builder blocks."""
    blocks = []
    sections = re.findall(r"(<section\b[^>]*>.*?</section>)", arch_html or "", flags=re.DOTALL)
    if not sections and arch_html:
        sections = [arch_html]

    for sec in sections:
        sec_class_m = re.search(r'<section[^>]*class="([^"]*)"', sec)
        sec_classes = sec_class_m.group(1) if sec_class_m else ""
        cc_m = re.search(r"\b(o_cc[1-5])\b", sec_classes)
        css_class = cc_m.group(1).replace("_", "-") if cc_m else ""
        add_shade = 1 if ("o_cc2" in sec_classes or "s_secondary_color" in sec_classes) else 0

        h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", sec, flags=re.DOTALL)
        h2_m = re.search(r"<h2[^>]*>(.*?)</h2>", sec, flags=re.DOTALL)
        title = strip_tags(h1_m.group(1) if h1_m else (h2_m.group(1) if h2_m else ""))
        paragraphs = [strip_tags(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", sec, flags=re.DOTALL) if strip_tags(p)]
        img_m = re.search(r'<img[^>]+src="([^"]+)"', sec)
        img_src = img_m.group(1) if img_m else ""

        if "s_website_form" in sec_classes:
            blocks.append(
                block(
                    "Contact and Inquiry Form",
                    {
                        "title": title or "Contact Us",
                        "subtitle": paragraphs[0] if paragraphs else "",
                        "form_mode": "contact",
                        "show_sidebar": 1,
                    },
                    css_class=css_class,
                    add_shade=add_shade,
                )
            )
        elif img_src and h1_m:
            blocks.append(
                block(
                    "Hero with Right Image",
                    {
                        "title": title,
                        "subtitle": "\n\n".join(paragraphs[:2]),
                        "image": img_src,
                        "contain_image": 0,
                    },
                    css_class=css_class,
                    add_shade=add_shade,
                )
            )
        else:
            blocks.append(
                block(
                    "Markdown",
                    {
                        "content": f'<div class="rich-content">{sec}</div>',
                    },
                    css_class=css_class,
                    add_shade=add_shade,
                )
            )
    return blocks


def migrate_english_pages_and_blogs(odoo_data=None, blog_route_prefix="blog"):
    if not odoo_data:
        return

    blog_cards = []
    for bp in odoo_data.get("blog_posts", []):
        if not bp.get("is_published"):
            continue
        name_obj = bp.get("name") or {}
        sub_obj = bp.get("subtitle") or {}
        content_obj = bp.get("content") or {}
        pl_title = name_obj.get("pl_PL") or next(iter(name_obj.values()), "Post") if isinstance(name_obj, dict) else str(name_obj)
        en_title = name_obj.get("en_US") or pl_title if isinstance(name_obj, dict) else str(name_obj)
        en_sub = sub_obj.get("en_US") or sub_obj.get("pl_PL") or "" if isinstance(sub_obj, dict) else str(sub_obj or "")
        en_html = content_obj.get("en_US") or content_obj.get("pl_PL") or "" if isinstance(content_obj, dict) else str(content_obj or "")

        slug = slugify(pl_title)
        route = f"en/{blog_route_prefix}/{slug}"
        pub_date = str(bp.get("published_date") or "")[:10]

        cover = ""
        cov_props = bp.get("cover_properties")
        if cov_props:
            try:
                props = json.loads(cov_props) if isinstance(cov_props, str) else cov_props
                bg = props.get("background-image", "")
                m = re.search(r"url\(['\"]?([^'\")\s]+)['\"]?\)", bg)
                if m:
                    cover = m.group(1)
            except Exception:
                pass

        blocks = [
            block(
                "Hero with Right Image",
                {
                    "title": en_title,
                    "subtitle": f"{pub_date}\n\n{en_sub}".strip(),
                    "image": cover,
                    "contain_image": 0,
                },
                css_class="o-cc2",
                add_shade=1,
            ),
            block("Markdown", {"content": f'<div class="blog-article-content">{en_html}</div>'}),
        ]
        upsert_web_page(f"en-blog-{slug}"[:140], en_title, route, blocks, meta_description=en_sub, meta_image=cover)
        blog_cards.append(
            {
                "post_title": en_title,
                "post_subtitle": en_sub,
                "cover_image": cover,
                "post_route": f"/{route}",
                "published_date": pub_date,
            }
        )

    if blog_cards:
        upsert_web_page(
            f"en-{blog_route_prefix}",
            "Blog",
            f"en/{blog_route_prefix}",
            [
                block(
                    "Dynamic Blog Posts Grid",
                    {
                        "title": "Blog",
                        "subtitle": "Latest articles and insights",
                        "posts": blog_cards,
                    },
                )
            ],
        )

    count = 0
    for pg in odoo_data.get("pages", []):
        if not pg.get("is_published"):
            continue
        raw_url = (pg.get("url") or "").strip()
        if not raw_url:
            continue
        pl_route = "home" if raw_url == "/" else raw_url.lstrip("/")
        en_route = "en" if pl_route == "home" else f"en/{pl_route}"

        arch_db = pg.get("arch_db") or {}
        en_arch = arch_db.get("en_US") or arch_db.get("pl_PL") or "" if isinstance(arch_db, dict) else str(arch_db)
        blocks = parse_odoo_sections_to_blocks(en_arch, lang_prefix="en")
        if not blocks:
            continue
        title = pg.get("view_name") or en_route
        upsert_web_page(f"en-{slugify(pl_route)}"[:140], title, en_route, blocks)
        count += 1

    frappe.db.commit()
    print(f"Created/Updated {len(blog_cards)} English blog posts and {count} English Web Pages.")


def update_website_settings_for_multilang():
    ws = frappe.get_doc("Website Settings", "Website Settings")
    ws.navbar_template = "Multilingual Navbar"
    ws.navbar_template_values = json.dumps(
        {
            "primary_lang": "pl",
            "secondary_lang": "en",
            "cta_label_en": "Contact Us",
        },
        ensure_ascii=False,
    )
    ws.footer_template = "Headline Footer"
    ws.save(ignore_permissions=True)
    frappe.db.commit()
    print("Updated Website Settings with Multilingual Navbar and bilingual Headline Footer.")


def main():
    parser = argparse.ArgumentParser(description="Enable multi-language (PL | EN) support on ERPNext website.")
    parser.add_argument("--site", default="frontend", help="Frappe site name")
    parser.add_argument("--sites-path", default="/home/frappe/frappe-bench/sites", help="Frappe sites path")
    parser.add_argument("--data-json", default="", help="Optional path to odoo_website_data.json")
    parser.add_argument("--translations-json", default="", help="Optional path to custom PL->EN JSON dictionary")
    parser.add_argument("--blog-route-prefix", default="blog", help="Primary blog route prefix")
    args = parser.parse_args()

    odoo_data = None
    if args.data_json and os.path.exists(args.data_json):
        with open(args.data_json, "r", encoding="utf-8") as f:
            odoo_data = json.load(f)

    extra_translations = None
    if args.translations_json and os.path.exists(args.translations_json):
        with open(args.translations_json, "r", encoding="utf-8") as f:
            extra_translations = json.load(f)

    frappe.init(site=args.site, sites_path=args.sites_path)
    frappe.connect()
    frappe.set_user("Administrator")

    ensure_languages_and_translations(odoo_data=odoo_data, extra_translations=extra_translations)
    update_theme_with_lang_switcher()
    ensure_multilang_web_templates()
    ensure_english_web_forms()
    if odoo_data:
        migrate_english_pages_and_blogs(odoo_data=odoo_data, blog_route_prefix=args.blog_route_prefix)
    update_website_settings_for_multilang()

    frappe.clear_cache()
    from frappe.website.utils import clear_cache

    clear_cache()
    print("Multi-language (PL | EN) website setup completed and caches cleared!")


if __name__ == "__main__":
    main()
