#!/usr/bin/env python3
"""
Idempotent Odoo CRM -> ERPNext v16 & Frappe CRM (`frappe/crm`) Migration Script.

Migrates:
1. Sales Users (res_users -> ERPNext User with Sales roles & avatars)
2. CRM Master Data:
   - crm_stage -> Sales Stage ('New', 'Qualified', 'Proposition', 'Won')
   - crm_lost_reason -> Opportunity Lost Reason
   - crm_tag & res_partner_category -> Tag
   - Bilingual PL translations (Translation DocType)
3. Company Tax ID & Address (from own company partner id=1)
4. Customers & Addresses (res_partner companies & commercial counterparties -> Customer & Address)
5. Contacts (res_partner individuals -> Contact with Contact Email, Contact Phone, Dynamic Link to Customer, designation, avatar, and chatter comments)
6. Opportunities (crm_lead -> Opportunity with expected_revenue, probability, sales_stage, status, opportunity_owner, lost_reasons, CRM Notes, PDF File attachments, Tags, Chatter Comments, and ToDo activities)
7. Kanban Boards (updates 'Opportunity Pipeline' and creates 'Sales Stage Pipeline' for New -> Qualified -> Proposition -> Won)
8. Frappe CRM App (`frappe/crm` / `FCRM`):
   - CRM Deal Status, CRM Lost Reason, CRM Organization, CRM Deal, FCRM Note, CRM Task, File attachments, and custom `deal_title` layout

Run inside erpnext-backend-1 from /home/frappe/frappe-bench/sites:
  /home/frappe/frappe-bench/env/bin/python /tmp/migrate_crm_to_erpnext.py --input-json /tmp/odoo_crm_export.json
"""

import argparse
import json
import os
import re
import frappe
from frappe.desk.doctype.tag.tag import add_tag
from frappe.utils import flt, getdate, now_datetime, today

# Standard Odoo template/system partner IDs to exclude from Customer creation
SYSTEM_PARTNER_IDS = {
    1,  # Own Company (handled separately via ensure_own_company_details)
    2,  # OdooBot
    3,  # Administrator
    4,  # Public user
    5,  # Default User Template
    6,  # Portal User Template
}


def get_default_company(explicit_company: str = None) -> str:
    if explicit_company and frappe.db.exists("Company", explicit_company):
        return explicit_company
    default_comp = frappe.db.get_single_value("Global Defaults", "default_company")
    if default_comp and frappe.db.exists("Company", default_comp):
        return default_comp
    companies = frappe.get_all("Company", pluck="name", limit=1)
    return companies[0] if companies else "Example Company Ltd."


def get_default_currency(explicit_currency: str = None) -> str:
    if explicit_currency:
        return explicit_currency
    default_curr = frappe.db.get_single_value("Global Defaults", "default_currency")
    return default_curr or "PLN"


def clean_odoo_html(html: str, lead_attachments: list) -> str:
    """Clean Odoo data-last-history-steps attributes and rewrite /web/content PDF links to ERPNext /files/crm/ URLs."""
    if not html:
        return ""
    cleaned = re.sub(r'\s*data-last-history-steps="[^"]*"', "", html)

    # Rewrite /web/content/<id>... links to ERPNext file URLs and ensure visible link text
    for att in lead_attachments:
        att_id = att["id"]
        url = att.get("erpnext_url") or ""
        name = att.get("name") or "Attachment"
        if not url:
            continue
        pattern = re.compile(
            rf'<a\s+[^>]*href="/web/content/{att_id}[^"]*"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        def _repl(match):
            inner = (match.group(1) or "").strip()
            label = inner if inner else f"📎 {name}"
            return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'

        cleaned = pattern.sub(_repl, cleaned)

    return cleaned.strip()


def split_full_name(full_name: str):
    parts = (full_name or "").strip().split()
    if not parts:
        return ("Unknown", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], " ".join(parts[1:]))


def normalize_phone(phone: str) -> str:
    """Normalize Odoo phone numbers (e.g. '71 123 45 67 wew. 201' -> '71 123 45 67 #201') to satisfy Frappe PHONE_NUMBER_PATTERN."""
    if not phone:
        return ""
    s = str(phone).strip()
    # Replace Polish/English extension markers ('wew.', 'wew', 'ext.', 'ext') with '#'
    s = re.sub(r"\b(?:wew\.?|ext\.?)\s*", "#", s, flags=re.IGNORECASE)
    # Strip any remaining invalid characters not in [0-9 +_-,.#*()]
    s = re.sub(r"[^0-9\ \+\_\-\,\.\*\#\(\)]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:20]


def ensure_file_record(file_url: str, attached_to_doctype: str = None, attached_to_name: str = None):
    if not file_url:
        return
    rel_path = file_url.lstrip("/")
    abs_path = os.path.join(frappe.get_site_path("public"), rel_path)
    if not os.path.exists(abs_path):
        return
    fname = os.path.basename(file_url)
    filters = {"file_name": fname}
    if attached_to_doctype and attached_to_name:
        filters["attached_to_doctype"] = attached_to_doctype
        filters["attached_to_name"] = attached_to_name
    else:
        filters["file_url"] = file_url

    existing_files = frappe.get_all("File", filters=filters, pluck="name")
    if existing_files:
        first = existing_files[0]
        frappe.db.set_value("File", first, "file_url", file_url)
        for dup in existing_files[1:]:
            frappe.delete_doc("File", dup, ignore_permissions=True)
        return

    doc = frappe.get_doc({
        "doctype": "File",
        "file_name": fname,
        "file_url": file_url,
        "is_private": 0,
        "attached_to_doctype": attached_to_doctype,
        "attached_to_name": attached_to_name,
    })
    doc.flags.copy_from_existing_file = True
    doc.insert(ignore_permissions=True)


def ensure_sales_users(data: dict, partner_avatars: dict) -> tuple[dict, set]:
    """
    Ensure active internal Odoo users exist in ERPNext with Sales roles.
    Returns:
      user_map: {odoo_user_id: erpnext_user_email}
      internal_partner_ids: set of partner_ids belonging to internal users
    """
    user_map = {
        1: "Administrator",
        2: "Administrator",
    }
    internal_partner_ids = set()
    roles_to_grant = ["Sales User", "Sales Manager", "Sales Master Manager"]

    for u in data.get("users", []):
        uid = u["id"]
        if uid in (1, 2) or not u.get("active", True) or u.get("share", False):
            continue
        email = (u.get("email") or u.get("login") or "").strip()
        if not email or "@" not in email:
            continue

        pid = u.get("partner_id")
        if pid:
            internal_partner_ids.add(pid)
        first_name, last_name = split_full_name(u.get("name") or email.split("@")[0])
        avatar = partner_avatars.get(pid) if pid else None
        ensure_file_record(avatar)

        if frappe.db.exists("User", email):
            user_doc = frappe.get_doc("User", email)
        else:
            user_doc = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "enabled": 1,
                "user_type": "System User",
                "send_welcome_email": 0,
            })
            user_doc.insert(ignore_permissions=True)

        existing_roles = {r.role for r in user_doc.roles}
        needs_save = False
        if (
            user_doc.first_name != first_name
            or user_doc.last_name != last_name
            or user_doc.enabled != 1
            or user_doc.user_type != "System User"
            or (avatar and user_doc.user_image != avatar)
        ):
            needs_save = True

        user_doc.first_name = first_name
        user_doc.last_name = last_name
        user_doc.enabled = 1
        user_doc.user_type = "System User"
        if avatar:
            user_doc.user_image = avatar

        for role in roles_to_grant:
            if role not in existing_roles and frappe.db.exists("Role", role):
                user_doc.append("roles", {"role": role})
                needs_save = True

        if needs_save:
            user_doc.save(ignore_permissions=True)
        user_map[uid] = email

    frappe.db.commit()
    print(f"Synced Sales Users: {list(user_map.values())}")
    return user_map, internal_partner_ids


def ensure_crm_master_data(data: dict):
    """Ensure Sales Stages, Opportunity Lost Reasons, Tags, and Polish Translations exist."""
    stage_map = {}
    for st in data.get("stages", []):
        name_en = st["name_en"].strip()
        name_pl = (st.get("name_pl") or name_en).strip()
        if not frappe.db.exists("Sales Stage", name_en):
            doc = frappe.get_doc({
                "doctype": "Sales Stage",
                "stage_name": name_en,
            })
            doc.insert(ignore_permissions=True)
        stage_map[st["id"]] = name_en
        upsert_translation("pl", name_en, name_pl)

    lost_reason_map = {}
    for lr in data.get("lost_reasons", []):
        name_en = lr["name_en"].strip()
        name_pl = (lr.get("name_pl") or name_en).strip()
        if not frappe.db.exists("Opportunity Lost Reason", name_en):
            doc = frappe.get_doc({
                "doctype": "Opportunity Lost Reason",
                "lost_reason": name_en,
            })
            doc.insert(ignore_permissions=True)
        lost_reason_map[lr["id"]] = name_en
        upsert_translation("pl", name_en, name_pl)

    for tg in data.get("tags", []):
        name_en = tg["name_en"].strip()
        name_pl = (tg.get("name_pl") or name_en).strip()
        if not frappe.db.exists("Tag", name_en):
            frappe.get_doc({"doctype": "Tag", "name": name_en}).insert(ignore_permissions=True)
        upsert_translation("pl", name_en, name_pl)

    frappe.db.commit()
    print(f"Synced {len(stage_map)} Sales Stages, {len(lost_reason_map)} Opportunity Lost Reasons, and {len(data.get('tags', []))} CRM Tags.")
    return stage_map, lost_reason_map


def upsert_translation(lang: str, source_text: str, translated_text: str):
    if not source_text or not translated_text or source_text == translated_text:
        return
    existing = frappe.db.get_value(
        "Translation",
        {"language": lang, "source_text": source_text},
        "name",
    )
    if existing:
        frappe.db.set_value("Translation", existing, "translated_text", translated_text)
    else:
        frappe.get_doc({
            "doctype": "Translation",
            "language": lang,
            "source_text": source_text,
            "translated_text": translated_text,
        }).insert(ignore_permissions=True)


def ensure_own_company_details(partners_by_id: dict, company_name: str):
    """Ensure the ERPNext Company has its VAT/Tax ID and headquarters address from res_partner id=1."""
    own = partners_by_id.get(1)
    if not own or not frappe.db.exists("Company", company_name):
        return
    comp = frappe.get_doc("Company", company_name)
    if own.get("vat") and comp.tax_id != own["vat"]:
        comp.tax_id = own["vat"]
        comp.save(ignore_permissions=True)

    if own.get("street") or own.get("city"):
        upsert_address(
            title=company_name,
            address_type="Office",
            street=own.get("street"),
            street2=own.get("street2"),
            city=own.get("city"),
            pincode=own.get("zip"),
            country=own.get("country_name") or "Poland",
            link_doctype="Company",
            link_name=company_name,
            is_your_company_address=1,
        )
    frappe.db.commit()


def upsert_address(
    title: str,
    address_type: str,
    street: str,
    street2: str,
    city: str,
    pincode: str,
    country: str,
    link_doctype: str,
    link_name: str,
    email_id: str = None,
    phone: str = None,
    is_primary: int = 1,
    is_shipping: int = 0,
    is_your_company_address: int = 0,
) -> str:
    if not street and not city:
        return None
    existing_links = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Address",
            "link_doctype": link_doctype,
            "link_name": link_name,
        },
        pluck="parent",
    )
    addr_doc = None
    for addr_name in existing_links:
        doc = frappe.get_doc("Address", addr_name)
        if doc.address_type == address_type:
            addr_doc = doc
            break

    if not addr_doc:
        addr_doc = frappe.new_doc("Address")
        addr_doc.address_title = title[:140]
        addr_doc.address_type = address_type

    addr_doc.address_title = title[:140]
    addr_doc.address_type = address_type
    addr_doc.address_line1 = (street or city or "-")[:140]
    addr_doc.address_line2 = (street2 or "")[:140] or None
    addr_doc.city = (city or "-")[:140]
    addr_doc.pincode = (pincode or "")[:20] or None
    addr_doc.country = country if frappe.db.exists("Country", country) else "Poland"
    addr_doc.email_id = email_id or None
    addr_doc.phone = normalize_phone(phone) or None
    addr_doc.is_primary_address = is_primary
    addr_doc.is_shipping_address = is_shipping
    addr_doc.is_your_company_address = is_your_company_address

    has_link = any(
        l.link_doctype == link_doctype and l.link_name == link_name
        for l in addr_doc.links
    )
    if not has_link:
        addr_doc.append("links", {
            "link_doctype": link_doctype,
            "link_name": link_name,
        })

    if addr_doc.is_new():
        addr_doc.insert(ignore_permissions=True)
    else:
        addr_doc.save(ignore_permissions=True)
    return addr_doc.name


def ensure_customers_and_contacts(
    data: dict,
    partner_avatars: dict,
    internal_partner_ids: set,
    company_name: str,
    default_currency: str,
):
    """
    Migrate Odoo res_partner records into ERPNext Customer, Address, and Contact records.
    Returns:
      partner_to_customer: {odoo_partner_id: erpnext_customer_name}
      partner_to_contact:  {odoo_partner_id: erpnext_contact_name}
    """
    partners = data.get("partners", [])
    partners_by_id = {p["id"]: p for p in partners}
    ensure_own_company_details(partners_by_id, company_name)

    # Identify partner IDs directly referenced on Opportunities or acting as parent organizations
    opp_partner_ids = {
        opp["partner_id"]
        for opp in data.get("opportunities", [])
        if opp.get("partner_id")
    }
    parent_partner_ids = {
        p["parent_id"]
        for p in partners
        if p.get("parent_id")
    }

    partner_to_customer = {}
    partner_to_contact = {}

    # 1. Create/Update Customers for top-level organizations and commercial counterparties
    for p in partners:
        pid = p["id"]
        if pid in SYSTEM_PARTNER_IDS or pid in internal_partner_ids:
            continue
        if p.get("type") in ("delivery", "invoice", "other"):
            continue

        is_top_level_customer = (p.get("parent_id") is None) and (
            bool(p.get("is_company"))
            or pid in opp_partner_ids
            or pid in parent_partner_ids
        )
        if not is_top_level_customer:
            continue

        cust_name = p["name"].strip()
        is_individual = not bool(p.get("is_company")) and pid not in parent_partner_ids
        cust_type = "Individual" if is_individual else "Company"
        cust_group = "Commercial"

        existing_name = frappe.db.get_value("Customer", {"customer_name": cust_name}, "name")
        if existing_name:
            cust_doc = frappe.get_doc("Customer", existing_name)
        else:
            cust_doc = frappe.new_doc("Customer")
            cust_doc.customer_name = cust_name

        cust_doc.customer_type = cust_type
        cust_doc.customer_group = cust_group
        cust_doc.territory = "Poland" if frappe.db.exists("Territory", "Poland") else "All Territories"
        cust_doc.default_currency = default_currency
        if p.get("vat"):
            cust_doc.tax_id = p["vat"].strip()
        if p.get("website"):
            cust_doc.website = p["website"].strip()

        avatar = partner_avatars.get(pid)
        if avatar:
            ensure_file_record(avatar)
            cust_doc.image = avatar

        if cust_doc.is_new():
            cust_doc.insert(ignore_permissions=True)
        else:
            cust_doc.save(ignore_permissions=True)

        partner_to_customer[pid] = cust_doc.name

        # Apply partner category tags
        for cat in (p.get("categories") or []):
            if cat:
                if not frappe.db.exists("Tag", cat):
                    frappe.get_doc({"doctype": "Tag", "name": cat}).insert(ignore_permissions=True)
                add_tag(cat, "Customer", cust_doc.name)

        # Create primary Billing Address if street or city is present
        if p.get("street") or p.get("city"):
            addr_name = upsert_address(
                title=cust_name,
                address_type="Billing",
                street=p.get("street"),
                street2=p.get("street2"),
                city=p.get("city"),
                pincode=p.get("zip"),
                country=p.get("country_name") or "Poland",
                link_doctype="Customer",
                link_name=cust_doc.name,
                email_id=p.get("email"),
                phone=p.get("phone"),
                is_primary=1,
            )
            if addr_name and cust_doc.customer_primary_address != addr_name:
                frappe.db.set_value("Customer", cust_doc.name, "customer_primary_address", addr_name)

    # 2. Handle child delivery addresses under parent Customers
    for p in partners:
        parent_id = p.get("parent_id")
        if p.get("type") == "delivery" and parent_id in partner_to_customer:
            parent_cust = partner_to_customer[parent_id]
            upsert_address(
                title=p["name"],
                address_type="Shipping",
                street=p.get("street") or p["name"],
                street2=p.get("street2"),
                city=p.get("city") or "-",
                pincode=p.get("zip"),
                country=p.get("country_name") or "Poland",
                link_doctype="Customer",
                link_name=parent_cust,
                is_primary=0,
                is_shipping=1,
            )

    # 3. Create/Update Contact records for all individual contacts & standalone counterparties
    frappe.db.commit()
    for p in partners:
        pid = p["id"]
        if pid in SYSTEM_PARTNER_IDS:
            continue
        if p.get("type") == "delivery":
            continue

        parent_id = p.get("parent_id")
        is_contact_person = (not bool(p.get("is_company"))) and (pid not in parent_partner_ids)
        if not is_contact_person:
            continue

        linked_customer = None
        if parent_id and parent_id in partner_to_customer:
            linked_customer = partner_to_customer[parent_id]
            partner_to_customer[pid] = linked_customer
        elif pid in partner_to_customer:
            linked_customer = partner_to_customer[pid]

        full_name = p["name"].strip()
        first_name, last_name = split_full_name(full_name)
        email = (p.get("email") or "").strip()
        phone = normalize_phone(p.get("phone") or "")
        designation = (p.get("function") or "").strip()
        parent_comp_name = p.get("parent_name") or (linked_customer if linked_customer else None)

        # Find existing Contact by email or full_name
        frappe.db.commit()
        contact_name = None
        if email:
            contact_name = frappe.db.get_value("Contact Email", {"email_id": email}, "parent")
        if not contact_name:
            contact_name = frappe.db.get_value(
                "Contact",
                {"first_name": first_name, "last_name": last_name},
                "name",
            )

        if contact_name and frappe.db.exists("Contact", contact_name):
            contact_doc = frappe.get_doc("Contact", contact_name)
        else:
            contact_doc = frappe.new_doc("Contact")

        contact_doc.first_name = first_name
        contact_doc.last_name = last_name
        contact_doc.full_name = full_name
        if designation:
            contact_doc.designation = designation[:140]
        if parent_comp_name:
            contact_doc.company_name = parent_comp_name[:140]

        avatar = partner_avatars.get(pid)
        if avatar:
            ensure_file_record(avatar)
            contact_doc.image = avatar

        # Link to ERPNext User if internal team member
        if email and frappe.db.exists("User", email):
            contact_doc.user = email

        # Populate email_ids child table
        if email:
            has_email = any(e.email_id == email for e in contact_doc.email_ids)
            if not has_email:
                contact_doc.append("email_ids", {
                    "email_id": email,
                    "is_primary": 1,
                })
            else:
                for e in contact_doc.email_ids:
                    if e.email_id == email:
                        e.is_primary = 1

        # Populate phone_nos child table
        if phone:
            has_phone = any(ph.phone == phone for ph in contact_doc.phone_nos)
            if not has_phone:
                contact_doc.append("phone_nos", {
                    "phone": phone,
                    "is_primary_phone": 1,
                    "is_primary_mobile_no": 1,
                })

        # Link to Customer
        if linked_customer:
            has_link = any(
                l.link_doctype == "Customer" and l.link_name == linked_customer
                for l in contact_doc.links
            )
            if not has_link:
                contact_doc.append("links", {
                    "link_doctype": "Customer",
                    "link_name": linked_customer,
                })
            contact_doc.is_primary_contact = 1

        if contact_doc.is_new():
            contact_doc.insert(ignore_permissions=True)
        else:
            contact_doc.save(ignore_permissions=True)
        frappe.db.commit()

        partner_to_contact[pid] = contact_doc.name

        # Apply partner category tags to Contact and parent Customer
        for cat in (p.get("categories") or []):
            if cat:
                if not frappe.db.exists("Tag", cat):
                    frappe.get_doc({"doctype": "Tag", "name": cat}).insert(ignore_permissions=True)
                add_tag(cat, "Contact", contact_doc.name)
                if linked_customer:
                    add_tag(cat, "Customer", linked_customer)

        # If parent Customer has no address yet but child contact has an address, add it to Customer
        if linked_customer and (p.get("street") or p.get("city")):
            cust_primary_addr = frappe.db.get_value("Customer", linked_customer, "customer_primary_address")
            if not cust_primary_addr:
                addr_name = upsert_address(
                    title=linked_customer,
                    address_type="Billing",
                    street=p.get("street"),
                    street2=p.get("street2"),
                    city=p.get("city"),
                    pincode=p.get("zip"),
                    country=p.get("country_name") or "Poland",
                    link_doctype="Customer",
                    link_name=linked_customer,
                    email_id=email or None,
                    phone=phone or None,
                    is_primary=1,
                )
                if addr_name:
                    frappe.db.set_value("Customer", linked_customer, "customer_primary_address", addr_name)

    # 4. Migrate chatter comments on res.partner
    for msg in data.get("messages", []):
        if msg.get("model") == "res.partner":
            res_id = msg.get("res_id")
            target_contact = partner_to_contact.get(res_id)
            if target_contact and msg.get("body"):
                ensure_comment(
                    reference_doctype="Contact",
                    reference_name=target_contact,
                    content=msg["body"],
                    comment_email=msg.get("author_email") or "Administrator",
                    comment_by=msg.get("author_name") or "Administrator",
                )

    frappe.db.commit()
    print(f"Synced {len(set(partner_to_customer.values()))} Customers and {len(partner_to_contact)} Contacts.")
    return partner_to_customer, partner_to_contact


def ensure_comment(reference_doctype: str, reference_name: str, content: str, comment_email: str, comment_by: str):
    exists = frappe.db.exists(
        "Comment",
        {
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "comment_type": "Comment",
            "content": content,
        },
    )
    if not exists:
        doc = frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Comment",
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "comment_email": comment_email,
            "comment_by": comment_by,
            "content": content,
        })
        doc.insert(ignore_permissions=True)


def map_opportunity_status(active: bool, stage_id: int) -> str:
    """
    Map Odoo crm_lead (active, stage_id) to ERPNext Opportunity.status:
      - active = False -> 'Lost'
      - stage_id = 1 (New) -> 'Open'
      - stage_id = 2 (Qualified) -> 'Replied'
      - stage_id = 3 (Proposition) -> 'Quotation'
      - stage_id = 4 (Won) -> 'Converted'
    """
    if not active:
        return "Lost"
    if stage_id == 4:
        return "Converted"
    if stage_id == 3:
        return "Quotation"
    if stage_id == 2:
        return "Replied"
    return "Open"


def ensure_opportunities(
    data: dict,
    partner_to_customer: dict,
    partner_to_contact: dict,
    user_map: dict,
    stage_map: dict,
    lost_reason_map: dict,
    lead_attachments_by_id: dict,
    company_name: str,
    default_currency: str,
):
    """Migrate Odoo crm_lead records into ERPNext Opportunity records."""
    opportunities = data.get("opportunities", [])
    messages_by_lead = {}
    for msg in data.get("messages", []):
        if msg.get("model") == "crm.lead":
            messages_by_lead.setdefault(msg["res_id"], []).append(msg)

    activities_by_lead = {}
    for act in data.get("activities", []):
        if act.get("res_model") == "crm.lead":
            activities_by_lead.setdefault(act["res_id"], []).append(act)

    migrated_opps = []

    for opp in opportunities:
        odoo_id = opp["id"]
        title = opp["name"].strip()
        active = bool(opp.get("active", True))
        stage_id = opp.get("stage_id") or 1
        sales_stage = stage_map.get(stage_id, "New")
        status = map_opportunity_status(active, stage_id)

        # Resolve Customer (party_name) and Contact (contact_person)
        pid = opp.get("partner_id")
        customer_name = None
        contact_name = None

        if pid:
            customer_name = partner_to_customer.get(pid)
            contact_name = partner_to_contact.get(pid)
        elif opp.get("partner_name"):
            customer_name = frappe.db.get_value(
                "Customer",
                {"customer_name": opp["partner_name"].strip()},
                "name",
            )

        if not customer_name:
            fallback_cust = (opp.get("partner_name") or title).strip()
            customer_name = frappe.db.get_value("Customer", {"customer_name": fallback_cust}, "name")
            if not customer_name:
                cdoc = frappe.get_doc({
                    "doctype": "Customer",
                    "customer_name": fallback_cust,
                    "customer_type": "Company",
                    "customer_group": "Commercial",
                    "territory": "Poland" if frappe.db.exists("Territory", "Poland") else "All Territories",
                    "default_currency": default_currency,
                })
                cdoc.insert(ignore_permissions=True)
                customer_name = cdoc.name
            if pid:
                partner_to_customer[pid] = customer_name

        if not contact_name and opp.get("contact_name"):
            first_n, last_n = split_full_name(opp["contact_name"])
            contact_name = frappe.db.get_value(
                "Contact",
                {"first_name": first_n, "last_name": last_n},
                "name",
            )

        if not contact_name and customer_name:
            contact_name = frappe.db.get_value(
                "Dynamic Link",
                {
                    "parenttype": "Contact",
                    "link_doctype": "Customer",
                    "link_name": customer_name,
                },
                "parent",
            )

        owner_email = user_map.get(opp.get("user_id"), "Administrator")
        tx_date = getdate(opp.get("create_date") or today())
        expected_closing = None
        if opp.get("date_deadline"):
            expected_closing = getdate(opp["date_deadline"])
        elif opp.get("date_closed"):
            expected_closing = getdate(opp["date_closed"])

        amount = flt(opp.get("expected_revenue") or 0.0)
        probability = flt(opp.get("probability") if opp.get("probability") is not None else (100.0 if stage_id == 4 else 0.0))

        # Check if Opportunity already exists by title + party_name
        existing_opp_name = frappe.db.get_value(
            "Opportunity",
            {"title": title, "party_name": customer_name},
            "name",
        )
        if existing_opp_name:
            opp_doc = frappe.get_doc("Opportunity", existing_opp_name)
        else:
            opp_doc = frappe.new_doc("Opportunity")

        opp_doc.title = title
        opp_doc.opportunity_from = "Customer"
        opp_doc.party_name = customer_name
        opp_doc.customer_name = customer_name
        opp_doc.opportunity_type = "Sales"
        opp_doc.status = status
        opp_doc.sales_stage = sales_stage
        opp_doc.opportunity_owner = owner_email
        opp_doc.company = company_name
        opp_doc.transaction_date = tx_date
        opp_doc.expected_closing = expected_closing
        opp_doc.currency = default_currency
        opp_doc.conversion_rate = 1.0
        opp_doc.opportunity_amount = amount
        opp_doc.base_opportunity_amount = amount
        opp_doc.probability = probability
        opp_doc.territory = "Poland" if frappe.db.exists("Territory", "Poland") else "All Territories"

        if contact_name:
            opp_doc.contact_person = contact_name
        if opp.get("email_from"):
            opp_doc.contact_email = opp["email_from"].strip()
        if opp.get("phone"):
            norm_phone = normalize_phone(opp["phone"])
            if norm_phone:
                opp_doc.contact_mobile = norm_phone
                opp_doc.phone = norm_phone
        if opp.get("function"):
            opp_doc.job_title = opp["function"].strip()[:140]

        # Lost reasons
        opp_doc.set("lost_reasons", [])
        lr_id = opp.get("lost_reason_id")
        if lr_id and lr_id in lost_reason_map:
            lr_name = lost_reason_map[lr_id]
            opp_doc.append("lost_reasons", {"lost_reason": lr_name})
            opp_doc.order_lost_reason = lr_name

        # Notes (description + chatter comments)
        lead_atts = lead_attachments_by_id.get(odoo_id, [])
        cleaned_desc = clean_odoo_html(opp.get("description") or "", lead_atts)
        opp_doc.set("notes", [])
        if cleaned_desc:
            opp_doc.append("notes", {
                "note": cleaned_desc,
                "added_by": owner_email,
                "added_on": opp.get("create_date") or str(now_datetime()),
            })

        for msg in messages_by_lead.get(odoo_id, []):
            body = (msg.get("body") or "").strip()
            if body:
                author_user = msg.get("author_email") if frappe.db.exists("User", msg.get("author_email") or "") else owner_email
                opp_doc.append("notes", {
                    "note": body,
                    "added_by": author_user or "Administrator",
                    "added_on": msg.get("date"),
                })

        if opp_doc.is_new():
            opp_doc.insert(ignore_permissions=True)
        else:
            opp_doc.save(ignore_permissions=True)

        # Attach PDF files to Opportunity
        for att in lead_atts:
            ensure_file_record(
                att.get("erpnext_url"),
                attached_to_doctype="Opportunity",
                attached_to_name=opp_doc.name,
            )

        # Add Tags from Odoo crm_tag_rel
        for tag_name in (opp.get("tags") or []):
            if tag_name:
                if not frappe.db.exists("Tag", tag_name):
                    frappe.get_doc({"doctype": "Tag", "name": tag_name}).insert(ignore_permissions=True)
                add_tag(tag_name, "Opportunity", opp_doc.name)

        # Add Chatter Comments to Timeline
        for msg in messages_by_lead.get(odoo_id, []):
            if msg.get("body"):
                ensure_comment(
                    reference_doctype="Opportunity",
                    reference_name=opp_doc.name,
                    content=msg["body"],
                    comment_email=msg.get("author_email") or owner_email,
                    comment_by=msg.get("author_name") or owner_email,
                )

        # Add Mail Activities as ERPNext ToDo records
        for act in activities_by_lead.get(odoo_id, []):
            summary = (act.get("summary") or act.get("activity_type_name") or "Follow up").strip()
            note = (act.get("note") or "").strip()
            desc = f"<b>{summary}</b><br>{note}" if note else summary
            allocated_to = user_map.get(act.get("user_id"), owner_email)
            exists_todo = frappe.db.exists(
                "ToDo",
                {
                    "reference_type": "Opportunity",
                    "reference_name": opp_doc.name,
                    "allocated_to": allocated_to,
                },
            )
            if not exists_todo:
                todo = frappe.get_doc({
                    "doctype": "ToDo",
                    "allocated_to": allocated_to,
                    "reference_type": "Opportunity",
                    "reference_name": opp_doc.name,
                    "description": desc,
                    "date": getdate(act.get("date_deadline")) if act.get("date_deadline") else tx_date,
                    "status": "Open",
                    "priority": "Medium",
                })
                todo.insert(ignore_permissions=True)

        migrated_opps.append(opp_doc.name)

    frappe.db.commit()
    print(f"Synced {len(migrated_opps)} Opportunities: {migrated_opps}")
    return migrated_opps


def ensure_crm_kanban_boards():
    """Configure Opportunity Pipeline and Sales Stage Pipeline Kanban Boards for CRM."""
    if frappe.db.exists("Kanban Board", "Opportunity Pipeline"):
        frappe.db.set_value(
            "Kanban Board",
            "Opportunity Pipeline",
            {
                "show_tags_on_card": 1,
                "show_assigned_to": 1,
                "show_labels": 1,
            },
        )

    board_name = "Sales Stage Pipeline"
    if frappe.db.exists("Kanban Board", board_name):
        kb = frappe.get_doc("Kanban Board", board_name)
    else:
        kb = frappe.new_doc("Kanban Board")
        kb.kanban_board_name = board_name
        kb.reference_doctype = "Opportunity"
        kb.field_name = "sales_stage"
        kb.is_standard = "No"
        kb.private = 0

    kb.title_field = "title"
    kb.show_assigned_to = 1
    kb.show_tags_on_card = 1
    kb.show_labels = 1
    kb.use_kanban_v2 = 1

    kb.set("columns", [
        {"column_name": "New", "status": "Active", "indicator": "Blue"},
        {"column_name": "Qualified", "status": "Active", "indicator": "Orange"},
        {"column_name": "Proposition", "status": "Active", "indicator": "Yellow"},
        {"column_name": "Won", "status": "Active", "indicator": "Green"},
    ])
    kb.set("card_fields", [
        {"fieldname": "customer_name", "label": "Customer Name"},
        {"fieldname": "opportunity_amount", "label": "Opportunity Amount"},
        {"fieldname": "probability", "label": "Probability (%)"},
        {"fieldname": "expected_closing", "label": "Expected Closing Date"},
    ])

    if kb.is_new():
        kb.insert(ignore_permissions=True)
    else:
        kb.save(ignore_permissions=True)

    frappe.db.commit()
    print("Configured 'Opportunity Pipeline' and 'Sales Stage Pipeline' Kanban Boards.")


def ensure_frappe_crm_app_data(
    data: dict,
    partner_to_customer: dict,
    partner_to_contact: dict,
    user_map: dict,
    stage_map: dict,
    lost_reason_map: dict,
    lead_attachments_by_id: dict,
    company_name: str,
    default_currency: str,
):
    """
    If the standalone Frappe CRM app (`frappe/crm`, module `FCRM`) is installed on the site,
    configure FCRM Settings & ERPNext CRM Settings and populate:
      - CRM Deal Status ('New', 'Qualified', 'Proposition', 'Won', 'Lost')
      - CRM Lost Reason
      - CRM Organization
      - CRM Deal (with deal_title, deal_value, probability, contacts, lost_reason)
      - FCRM Note (rich HTML notes on CRM Deal)
      - CRM Task (follow-up tasks from mail_activity on CRM Deal)
      - File attachments on CRM Deal
    """
    if not frappe.db.exists("DocType", "CRM Deal"):
        return

    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    # 1. Configure ERPNext CRM Settings, FCRM Settings & ERPNext CRM Settings
    if frappe.db.exists("DocType", "CRM Settings"):
        crm_settings = frappe.get_single("CRM Settings")
        if hasattr(crm_settings, "enable_frappe_crm_data_synchronization"):
            crm_settings.enable_frappe_crm_data_synchronization = 1
            crm_settings.save(ignore_permissions=True)

    fcrm_settings = frappe.get_single("FCRM Settings")
    fcrm_settings.currency = default_currency
    fcrm_settings.brand_name = company_name
    fcrm_settings.setup_completed = 1
    fcrm_settings.save(ignore_permissions=True)

    erpnext_crm = frappe.get_single("ERPNext CRM Settings")
    erpnext_crm.enabled = 1
    erpnext_crm.is_erpnext_in_different_site = 0
    erpnext_crm.erpnext_company = company_name
    erpnext_crm.sync_products = 1
    # Keep create_customer_on_status_change=0 during bulk deal import since Customers already exist
    erpnext_crm.create_customer_on_status_change = 0
    erpnext_crm.deal_status = "Won"
    erpnext_crm.save(ignore_permissions=True)
    frappe.db.commit()

    # 2. Ensure 'deal_title' custom field exists on CRM Deal and is shown in CRM Fields Layout
    create_custom_fields(
        {
            "CRM Deal": [
                {
                    "fieldname": "deal_title",
                    "label": "Deal Title",
                    "fieldtype": "Data",
                    "insert_after": "organization",
                    "in_list_view": 1,
                    "in_standard_filter": 1,
                    "bold": 1,
                }
            ]
        },
        ignore_validate=True,
    )

    for layout_name in ("CRM Deal-Data Fields", "CRM Deal-Side Panel"):
        if frappe.db.exists("CRM Fields Layout", layout_name):
            layout_doc = frappe.get_doc("CRM Fields Layout", layout_name)
            if layout_doc.layout and '"deal_title"' not in layout_doc.layout:
                layout_doc.layout = layout_doc.layout.replace(
                    '"organization"',
                    '"deal_title", "organization", "deal_value"',
                    1,
                )
                layout_doc.save(ignore_permissions=True)

    # 3. Ensure Odoo pipeline statuses exist in CRM Deal Status & CRM Lost Reason
    odoo_deal_statuses = [
        {"name": "New", "type": "Open", "position": 1, "probability": 10.0, "color": "blue", "pl": "Nowy"},
        {"name": "Qualified", "type": "Ongoing", "position": 2, "probability": 50.0, "color": "cyan", "pl": "Zakwalifikowano"},
        {"name": "Proposition", "type": "Ongoing", "position": 3, "probability": 75.0, "color": "orange", "pl": "Propozycja"},
        {"name": "Won", "type": "Won", "position": 6, "probability": 100.0, "color": "green", "pl": "Wygrano"},
        {"name": "Lost", "type": "Lost", "position": 7, "probability": 0.0, "color": "red", "pl": "Przegrane"},
    ]
    for st in odoo_deal_statuses:
        if frappe.db.exists("CRM Deal Status", st["name"]):
            sdoc = frappe.get_doc("CRM Deal Status", st["name"])
        else:
            sdoc = frappe.new_doc("CRM Deal Status")
            sdoc.deal_status = st["name"]
        sdoc.type = st["type"]
        sdoc.position = st["position"]
        sdoc.probability = st["probability"]
        sdoc.color = st["color"]
        if sdoc.is_new():
            sdoc.insert(ignore_permissions=True)
        else:
            sdoc.save(ignore_permissions=True)
        upsert_translation("pl", st["name"], st["pl"])

    for lr in data.get("lost_reasons", []):
        name_en = lr["name_en"].strip()
        if not frappe.db.exists("CRM Lost Reason", name_en):
            frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": name_en}).insert(ignore_permissions=True)

    # 4. Sync CRM Organization for all migrated Customers
    cust_to_org = {}
    for cust_name in sorted(set(partner_to_customer.values())):
        if not frappe.db.exists("Customer", cust_name):
            continue
        cust_doc = frappe.get_doc("Customer", cust_name)
        if frappe.db.exists("CRM Organization", cust_name):
            org_doc = frappe.get_doc("CRM Organization", cust_name)
        else:
            org_doc = frappe.new_doc("CRM Organization")
            org_doc.organization_name = cust_name

        org_doc.organization_name = cust_name
        org_doc.currency = default_currency
        org_doc.exchange_rate = 1.0
        if cust_doc.website:
            org_doc.website = cust_doc.website
        if cust_doc.image:
            org_doc.organization_logo = cust_doc.image
        if cust_doc.customer_primary_address:
            org_doc.address = cust_doc.customer_primary_address

        if org_doc.is_new():
            org_doc.insert(ignore_permissions=True)
        else:
            org_doc.save(ignore_permissions=True)
        cust_to_org[cust_name] = org_doc.name

    # Ensure Contact.company_name points to the linked CRM Organization so Organization -> Contacts tab works
    for pid, contact_name in partner_to_contact.items():
        linked_cust = partner_to_customer.get(pid)
        if linked_cust and linked_cust in cust_to_org and frappe.db.exists("Contact", contact_name):
            frappe.db.set_value("Contact", contact_name, "company_name", cust_to_org[linked_cust])

    # 5. Sync all Odoo Opportunities into CRM Deal + FCRM Note + CRM Task + File
    messages_by_lead = {}
    for msg in data.get("messages", []):
        if msg.get("model") == "crm.lead":
            messages_by_lead.setdefault(msg["res_id"], []).append(msg)

    activities_by_lead = {}
    for act in data.get("activities", []):
        if act.get("res_model") == "crm.lead":
            activities_by_lead.setdefault(act["res_id"], []).append(act)

    migrated_deals = []
    for opp in data.get("opportunities", []):
        odoo_id = opp["id"]
        title = opp["name"].strip()
        active = bool(opp.get("active", True))
        stage_id = opp.get("stage_id") or 1
        stage_name = stage_map.get(stage_id, "New")
        deal_status = "Lost" if not active else stage_name

        pid = opp.get("partner_id")
        customer_name = partner_to_customer.get(pid) if pid else None
        if not customer_name:
            customer_name = (opp.get("partner_name") or title).strip()
        org_name = cust_to_org.get(customer_name) or customer_name

        contact_name = partner_to_contact.get(pid) if pid else None
        if not contact_name and opp.get("contact_name"):
            first_n, last_n = split_full_name(opp["contact_name"])
            contact_name = frappe.db.get_value("Contact", {"first_name": first_n, "last_name": last_n}, "name")
        if not contact_name and customer_name:
            contact_name = frappe.db.get_value(
                "Dynamic Link",
                {"parenttype": "Contact", "link_doctype": "Customer", "link_name": customer_name},
                "parent",
            )

        owner_email = user_map.get(opp.get("user_id"), "Administrator")
        amount = flt(opp.get("expected_revenue") or 0.0)
        probability = flt(opp.get("probability") if opp.get("probability") is not None else (100.0 if stage_id == 4 else 0.0))
        expected_closing = getdate(opp["date_deadline"]) if opp.get("date_deadline") else (getdate(opp["date_closed"]) if opp.get("date_closed") else None)
        closed_date = getdate(opp["date_closed"]) if opp.get("date_closed") else None

        existing_deal = frappe.db.get_value(
            "CRM Deal",
            {"lead_name": title, "organization": org_name},
            "name",
        )
        if existing_deal:
            deal_doc = frappe.get_doc("CRM Deal", existing_deal)
        else:
            deal_doc = frappe.new_doc("CRM Deal")

        deal_doc.organization = org_name if frappe.db.exists("CRM Organization", org_name) else None
        deal_doc.organization_name = org_name
        deal_doc.deal_title = title
        deal_doc.lead_name = title
        deal_doc.next_step = f"{title} ({stage_name})" if not active else title
        deal_doc.erpnext_customer = customer_name
        deal_doc.status = deal_status
        deal_doc.deal_owner = owner_email
        deal_doc.currency = default_currency
        deal_doc.exchange_rate = 1.0
        deal_doc.deal_value = amount
        deal_doc.expected_deal_value = amount
        deal_doc.annual_revenue = amount
        deal_doc.probability = probability
        deal_doc.expected_closure_date = expected_closing
        if closed_date:
            deal_doc.closed_date = closed_date
        if opp.get("function"):
            deal_doc.job_title = opp["function"].strip()[:140]

        # Lost reason validation in Frappe CRM requires lost_reason when status type == 'Lost'
        if deal_status == "Lost":
            lr_id = opp.get("lost_reason_id")
            if lr_id and lr_id in lost_reason_map:
                deal_doc.lost_reason = lost_reason_map[lr_id]
                deal_doc.lost_notes = f"Stage before loss: {stage_name}"
            else:
                deal_doc.lost_reason = "Other"
                deal_doc.lost_notes = f"Archived / Lost in Odoo (Stage: {stage_name})"
        else:
            deal_doc.lost_reason = None
            deal_doc.lost_notes = None

        # Populate CRM Contacts child table
        deal_doc.set("contacts", [])
        if contact_name and frappe.db.exists("Contact", contact_name):
            cdoc = frappe.get_doc("Contact", contact_name)
            c_phone = normalize_phone(opp.get("phone") or cdoc.phone or cdoc.mobile_no or "")
            deal_doc.contact = cdoc.name
            deal_doc.first_name = cdoc.first_name
            deal_doc.last_name = cdoc.last_name
            deal_doc.append("contacts", {
                "contact": cdoc.name,
                "full_name": cdoc.full_name or cdoc.first_name,
                "email": (opp.get("email_from") or cdoc.email_id or "").strip(),
                "mobile_no": c_phone,
                "phone": c_phone,
                "is_primary": 1,
            })

        if deal_doc.is_new():
            deal_doc.insert(ignore_permissions=True)
        else:
            deal_doc.save(ignore_permissions=True)

        # Link Customer.crm_deal to this Deal
        if customer_name and frappe.db.exists("Customer", customer_name):
            frappe.db.set_value("Customer", customer_name, "crm_deal", deal_doc.name)

        # Create/Update FCRM Note for description & chatter messages
        lead_atts = lead_attachments_by_id.get(odoo_id, [])
        cleaned_desc = clean_odoo_html(opp.get("description") or "", lead_atts)
        if cleaned_desc:
            note_title = f"Notes: {title}"[:140]
            existing_note = frappe.db.get_value(
                "FCRM Note",
                {"reference_doctype": "CRM Deal", "reference_docname": deal_doc.name, "title": note_title},
                "name",
            )
            if existing_note:
                ndoc = frappe.get_doc("FCRM Note", existing_note)
                ndoc.content = cleaned_desc
                ndoc.save(ignore_permissions=True)
            else:
                frappe.get_doc({
                    "doctype": "FCRM Note",
                    "title": note_title,
                    "content": cleaned_desc,
                    "reference_doctype": "CRM Deal",
                    "reference_docname": deal_doc.name,
                }).insert(ignore_permissions=True)

        for idx, msg in enumerate(messages_by_lead.get(odoo_id, []), start=1):
            body = (msg.get("body") or "").strip()
            if body:
                m_title = f"Comment #{idx} ({msg.get('author_name') or 'Chatter'})"[:140]
                existing_m = frappe.db.get_value(
                    "FCRM Note",
                    {"reference_doctype": "CRM Deal", "reference_docname": deal_doc.name, "title": m_title},
                    "name",
                )
                if not existing_m:
                    frappe.get_doc({
                        "doctype": "FCRM Note",
                        "title": m_title,
                        "content": body,
                        "reference_doctype": "CRM Deal",
                        "reference_docname": deal_doc.name,
                    }).insert(ignore_permissions=True)

        # Attach PDF files to CRM Deal
        for att in lead_atts:
            ensure_file_record(
                att.get("erpnext_url"),
                attached_to_doctype="CRM Deal",
                attached_to_name=deal_doc.name,
            )

        # Add Tags to CRM Deal
        for tag_name in (opp.get("tags") or []):
            if tag_name:
                add_tag(tag_name, "CRM Deal", deal_doc.name)

        # Create CRM Task for follow-up activities
        for act in activities_by_lead.get(odoo_id, []):
            summary = (act.get("summary") or act.get("activity_type_name") or "Follow up").strip()
            note = (act.get("note") or "").strip()
            assigned_to = user_map.get(act.get("user_id"), owner_email)
            existing_task = frappe.db.get_value(
                "CRM Task",
                {"reference_doctype": "CRM Deal", "reference_docname": deal_doc.name, "title": summary[:140]},
                "name",
            )
            if not existing_task:
                frappe.get_doc({
                    "doctype": "CRM Task",
                    "title": summary[:140],
                    "description": note or summary,
                    "reference_doctype": "CRM Deal",
                    "reference_docname": deal_doc.name,
                    "assigned_to": assigned_to,
                    "due_date": act.get("date_deadline") or opp.get("create_date"),
                    "status": "Todo",
                    "priority": "Medium",
                }).insert(ignore_permissions=True)

        migrated_deals.append(deal_doc.name)
        frappe.db.commit()

    # Enable create_customer_on_status_change for future deals marked Won
    frappe.db.set_single_value("ERPNext CRM Settings", "create_customer_on_status_change", 1)
    frappe.db.commit()
    print(f"Synced Frappe CRM app: {len(cust_to_org)} CRM Organizations and {len(migrated_deals)} CRM Deals.")


def main():
    parser = argparse.ArgumentParser(description="Migrate extracted Odoo CRM JSON into ERPNext.")
    parser.add_argument("--input-json", default="/tmp/odoo_crm_export.json")
    parser.add_argument("--site", default="frontend")
    parser.add_argument("--company", default=None, help="Target ERPNext Company name (auto-detected if omitted)")
    parser.add_argument("--currency", default=None, help="Target currency code (auto-detected if omitted)")
    args = parser.parse_args()

    with open(args.input_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    frappe.init(site=args.site)
    frappe.connect()

    company_name = get_default_company(args.company)
    default_currency = get_default_currency(args.currency)

    partner_avatars = {}
    lead_attachments_by_id = {}
    for att in data.get("attachments", []):
        if not att.get("downloaded"):
            continue
        if att.get("res_model") == "res.partner":
            partner_avatars[att["res_id"]] = att["erpnext_url"]
        elif att.get("res_model") == "crm.lead":
            lead_attachments_by_id.setdefault(att["res_id"], []).append(att)

    user_map, internal_partner_ids = ensure_sales_users(data, partner_avatars)
    stage_map, lost_reason_map = ensure_crm_master_data(data)
    partner_to_customer, partner_to_contact = ensure_customers_and_contacts(
        data,
        partner_avatars,
        internal_partner_ids,
        company_name,
        default_currency,
    )
    ensure_opportunities(
        data,
        partner_to_customer,
        partner_to_contact,
        user_map,
        stage_map,
        lost_reason_map,
        lead_attachments_by_id,
        company_name,
        default_currency,
    )
    ensure_crm_kanban_boards()
    ensure_frappe_crm_app_data(
        data,
        partner_to_customer,
        partner_to_contact,
        user_map,
        stage_map,
        lost_reason_map,
        lead_attachments_by_id,
        company_name,
        default_currency,
    )
    frappe.clear_cache()
    print("Odoo CRM -> ERPNext migration completed successfully!")


if __name__ == "__main__":
    main()
