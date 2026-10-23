# Odoo 18 CRM (`crm.lead` & `res.partner`) to ERPNext v16 CRM Mapping Reference

This reference documents the data model mapping, stage/status resolution, partner hierarchy decomposition, rich HTML note sanitization, and binary attachment migration from **Odoo 18 (`crm` + `contacts` + `mail`)** to **ERPNext v16 (`CRM` + `Selling` + `Contacts`)** and **Frappe CRM (`frappe/crm`)**.

---

## 1. Entity & DocType Mapping Overview

| Odoo 18 Model / Table | ERPNext v16 DocType(s) | Migration Strategy |
| :--- | :--- | :--- |
| `res_users` (Sales Team) | `User` + `Has Role` | Create/update `System User` records (`Sales User`, `Sales Manager`, `Sales Master Manager`) and map `crm_lead.user_id` to `Opportunity.opportunity_owner`. |
| `crm_stage` | `Sales Stage` + `Translation` | Map stage `name->>'en_US'` to `Sales Stage` (`New`, `Qualified`, `Proposition`, `Won`) and `name->>'pl_PL'` (`Nowy`, `Zakwalifikowano`, `Propozycja`, `Wygrano`) to `Translation` (`language='pl'`). |
| `crm_lost_reason` | `Opportunity Lost Reason` + `Translation` | Map `name->>'en_US'` (`Too expensive`, `We don't have people/skills`, `Not enough stock`) to `Opportunity Lost Reason` and `name->>'pl_PL'` to `Translation`. |
| `crm_tag` & `res_partner_category` | `Tag` + `Tag Link` + `Translation` | Map tag names to `Tag`, link via `frappe.desk.doctype.tag.tag.add_tag`, and add Polish `Translation` records. |
| `res_partner` (`is_company=true` or commercial counterparty) | `Customer` | Map top-level companies/institutions to `Customer` (`customer_type='Company'`, `customer_group='Commercial' | 'Non Profit' | 'Government'`, `tax_id=vat`, `website`, `image` logo). |
| `res_partner` (street / city / zip / `type='delivery'`) | `Address` + `Dynamic Link` | Map billing and delivery addresses (`type='contact'` -> `Billing`, `type='delivery'` -> `Shipping`, own company -> `Office`) linked to `Customer` or `Company`. |
| `res_partner` (`is_company=false`) | `Contact` + `Contact Email` + `Contact Phone` + `Dynamic Link` | Map individual contacts to `Contact` (`first_name`, `last_name`, `designation=function`, `company_name`, `image` avatar), populate `email_ids` and normalized `phone_nos`, and link to parent `Customer`. |
| `crm_lead` (`type='opportunity'` / `'lead'`) | `Opportunity` + `CRM Note` + `Opportunity Lost Reason Detail` | Map all active and archived/lost opportunities to `Opportunity` (`opportunity_from='Customer'`, `party_name`, `contact_person`, `sales_stage`, `status`, `opportunity_amount`, `probability`, `expected_closing`, `opportunity_owner`, `notes`, `lost_reasons`). |
| `ir_attachment` (`res_model IN ('crm.lead', 'res.partner')`) | `File` | Extract binary files from Odoo's filestore (`/etc/odoo/filestore/<db>/<store_fname>`), copy to `/sites/frontend/public/files/crm/`, and register `File` records (`flags.copy_from_existing_file = True`). |
| `mail_message` (`message_type='comment'`) | `Comment` + `CRM Note` | Preserve user-authored chatter messages on `Contact` and `Opportunity` timelines (`Comment`) and in the Opportunity `notes` table (`CRM Note`). |
| `mail_activity` (`res_model='crm.lead'`) | `ToDo` | Migrate scheduled CRM follow-up activities (`summary`, `note`, `date_deadline`, `user_id`) to `ToDo` (`reference_type='Opportunity'`). |
| Odoo CRM Pipeline Kanban | `Kanban Board` | Configure both `Opportunity Pipeline` (grouped by `status`) and `Sales Stage Pipeline` (grouped by `sales_stage`: `New` -> `Qualified` -> `Proposition` -> `Won`). |

---

## 2. `res.partner` Hierarchy Decomposition (`Customer` vs `Contact` vs `Address`)

In Odoo, `res_partner` is a single polymorphic table storing companies, individual contacts, delivery addresses, system users, and e-commerce guest checkouts. In ERPNext, these are strictly separated into `Company`, `Customer`, `Contact`, and `Address`.

### 2.1 Classification Rules
1. **Own Company (`id=1`)**:
   - Maps to ERPNext's existing `Company` (`Global Defaults.default_company`), updating `Company.tax_id` (`vat`) and creating an `Office` `Address` (`is_your_company_address=1`).
2. **System / Template / Test Checkout Duplicates**:
   - Exclude Odoo system accounts (`odoobot`, `Administrator`, `Public user`, `Default User Template`, `Portal User Template`) and duplicate test checkout partners from `Customer` creation.
3. **Internal Team & Collaborators**:
   - Internal sales users (`res_users`) are created as `Contact` records and linked to `User`, never as `Customer` records.
4. **Top-Level Organizations (`is_company=True` and `parent_id IS NULL`)**:
   - Created as `Customer` (`customer_type='Company'`) with:
     - `customer_group`: `'Government'` (municipalities/public schools), `'Non Profit'` (foundations/associations), or `'Commercial'` (commercial corporations).
     - Primary `Billing` `Address` created from `street`, `street2`, `zip`, `city`, `country_id` and linked via `Customer.customer_primary_address`.
5. **Child Delivery Addresses (`type='delivery'` and `parent_id IS NOT NULL`)**:
   - Created as `Shipping` `Address` (`is_shipping_address=1`) linked to the parent `Customer`.
6. **Child Individual Contacts (`is_company=False` and `parent_id IS NOT NULL`)**:
   - Created as `Contact` records linked to `partner_to_customer[parent_id]` via `Dynamic Link` (`link_doctype='Customer'`), with:
     - `designation` <- `res_partner.function`
     - `email_ids` <- `res_partner.email` (`is_primary=1`)
     - `phone_nos` <- normalized `res_partner.phone` (`is_primary_phone=1`, `is_primary_mobile_no=1`)
     - `image` <- extracted `image_1920` avatar from Odoo filestore.

---

## 3. Phone Number Normalization (`frappe.InvalidPhoneNumberError`)

Frappe validates `Contact Phone.phone`, `Address.phone`, and `Opportunity.contact_mobile` against `PHONE_NUMBER_PATTERN = r"^([0-9\ \+\_\-\,\.\*\#\(\)]){1,20}$"`.
- Polish phone numbers in Odoo often contain extension markers such as `wew.` (e.g., `71 123 45 67 wew. 201`), which raises `frappe.exceptions.InvalidPhoneNumberError`.
- Always normalize phone numbers before saving:
  ```python
  def normalize_phone(phone: str) -> str:
      if not phone:
          return ""
      s = str(phone).strip()
      s = re.sub(r"\b(?:wew\.?|ext\.?)\s*", "#", s, flags=re.IGNORECASE)
      s = re.sub(r"[^0-9\ \+\_\-\,\.\*\#\(\)]", "", s)
      s = re.sub(r"\s+", " ", s).strip()
      return s[:20]
  ```

---

## 4. `crm.lead` Stage & Status Mapping to ERPNext `Opportunity`

In Odoo 18:
- Pipeline stage is stored in `crm_lead.stage_id` (`1: New`, `2: Qualified`, `3: Proposition`, `4: Won`).
- Lost opportunities have `active = false` and `probability = 0`, while retaining the `stage_id` they were in when marked lost, plus `lost_reason_id`.

In ERPNext v16 `Opportunity`:
- `sales_stage` (`Link` to `Sales Stage`) stores the pipeline stage (`New`, `Qualified`, `Proposition`, `Won`) — preserving the exact stage even for Lost opportunities.
- `status` (`Select`: `Open`, `Quotation`, `Converted`, `Lost`, `Replied`, `Closed`) stores the lifecycle status:

| Odoo `active` | Odoo `stage_id` (`crm_stage`) | ERPNext `Opportunity.sales_stage` | ERPNext `Opportunity.status` |
| :--- | :--- | :--- | :--- |
| `True` | `1` (`New` / `Nowy`) | `New` | `Open` |
| `True` | `2` (`Qualified` / `Zakwalifikowano`) | `Qualified` | `Replied` |
| `True` | `3` (`Proposition` / `Propozycja`) | `Proposition` | `Quotation` |
| `True` | `4` (`Won` / `Wygrano`) | `Won` | `Converted` |
| `False` (Archived / Lost) | `1..4` (Retained stage) | `New` / `Qualified` / `Proposition` | `Lost` (with `lost_reasons` child table & `order_lost_reason`) |

---

## 5. Rich HTML Notes (`CRM Note`) & PDF Attachments (`File`)

1. **Odoo Internal Notes (`crm_lead.description`)**:
   - ERPNext v16 `Opportunity` inherits from `CRMNote` and stores rich HTML notes in its `notes` child table (`CRM Note` DocType: `note`, `added_by`, `added_on`).
   - Odoo's `description` field contains `data-last-history-steps="..."` attributes and inline attachment links of the form:
     ```html
     <a href="/web/content/1001?download=true" class="o_image" title="Proposal.pdf" data-mimetype="application/pdf"></a>
     ```
   - Because Odoo renders the filename via CSS on `.o_image` with empty inner HTML text, `clean_odoo_html()` rewrites `/web/content/<id>...` to `/files/crm/<filename>` and injects visible `📎 <filename>` anchor text.
2. **Preventing Duplicate `File` Blobs in Frappe**:
   - When creating a `File` record for a file already copied into `/sites/frontend/public/files/crm/`, set `doc.flags.copy_from_existing_file = True` before `doc.insert(ignore_permissions=True)`. Otherwise, `File.before_insert()` re-reads the file and writes a duplicate copy to `/files/<filename>`.

---

## 6. Standalone Frappe CRM (`frappe/crm`) App Mapping

When the standalone **Frappe CRM** app (`frappe/crm`, mounted at `/crm`) is installed alongside ERPNext, `ensure_frappe_crm_app_data()` populates and synchronizes all Frappe CRM DocTypes:

| Odoo 18 Model | Frappe CRM (`FCRM`) DocType | Key Fields & Synchronization Notes |
| :--- | :--- | :--- |
| System / App Settings | `FCRM Settings` + `ERPNext CRM Settings` + `CRM Settings` | Set `FCRM Settings.currency = 'PLN'`, `setup_completed = 1`; set `CRM Settings.enable_frappe_crm_data_synchronization = 1`; set `ERPNext CRM Settings` (`enabled = 1`, `erpnext_company`, `sync_products = 1`, `create_customer_on_status_change = 1`, `deal_status = 'Won'`). |
| `crm_stage` | `CRM Deal Status` + `Translation` | Map Odoo stages (`New` -> `type='Open'`, `Qualified` -> `type='Ongoing'`, `Proposition` -> `type='Ongoing'`, `Won` -> `type='Won'`, `Lost` -> `type='Lost'`) with `position` ordering and Polish `Translation` records. |
| `crm_lost_reason` | `CRM Lost Reason` + `Translation` | Map `Too expensive`, `We don't have people/skills`, `Not enough stock` to `CRM Lost Reason`. |
| `res_partner` (`Customer`) | `CRM Organization` | Map CRM Customers to `CRM Organization` (`organization_name`, `website`, `territory`, `industry`, `currency='PLN'`, `address` linked to primary `Billing` `Address`, `organization_logo`). Note: Frappe CRM shares core `Contact` and `Address` DocTypes directly (`/crm/contacts`). |
| `crm_lead` (`Opportunity`) | `CRM Deal` + `CRM Contacts` | Map Odoo opportunities to `CRM Deal` (`organization`, `deal_title` custom field shown in `CRM Fields Layout`, `status`, `deal_value`, `annual_revenue`, `probability`, `expected_closure_date`, `closed_date`, `deal_owner`, `erpnext_customer`, `contacts` child table, `lost_reason`, `lost_notes`). |
| `crm_lead.description` & `mail_message` | `FCRM Note` | Create rich HTML `FCRM Note` cards (`reference_doctype='CRM Deal'`, `reference_docname=deal.name`, `title`, `content`) for both internal Opportunity notes and user-authored chatter comments. |
| `mail_activity` | `CRM Task` | Create follow-up `CRM Task` cards (`reference_doctype='CRM Deal'`, `reference_docname=deal.name`, `title`, `description`, `assigned_to`, `due_date`, `status='Todo'`). |
| `ir_attachment` (`crm.lead`) | `File` (`attached_to_doctype='CRM Deal'`) | Attach extracted PDF offers/agreements directly to each `CRM Deal` so they appear in the Deal's **Attachments** tab in `/crm/deals/<deal_name>`. |
