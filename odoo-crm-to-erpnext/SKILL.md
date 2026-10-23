---
name: odoo-crm-to-erpnext
description: Migrate CRM data (Contacts, Companies/Customers, Addresses, Sales Team Users, CRM Pipeline Stages, Lost Reasons, Tags, Opportunities/Deals with Expected Revenue & Probability, Rich HTML Notes, PDF Attachments, Chatter Comments, Follow-up Activities/Tasks, and Kanban Boards) from Odoo (res.partner, crm.lead, crm.stage, mail.message, mail.activity, ir.attachment) to ERPNext v16 and the standalone Frappe CRM (frappe/crm) app using 100% database configuration and site files without modifying Frappe/ERPNext core code.
---

# Odoo CRM (`crm.lead` & `res.partner`) to ERPNext & Frappe CRM Migration Skill

Use this skill to migrate the complete **Odoo CRM** pipeline and **Contacts / Companies** directory into **ERPNext v16 (`CRM` + `Selling` + `Contacts`)** AND the standalone **Frappe CRM (`frappe/crm`)** workspace (`/crm`) with full multi-language (`PL` | `EN`) stage/tag/lost-reason translations, partner hierarchy resolution (`Customer` & `CRM Organization` -> `Address` + `Contact`), rich HTML notes (`CRM Note` & `FCRM Note`), PDF file attachments (`File`), chatter comments (`Comment`), follow-up tasks (`ToDo` & `CRM Task`), and pipeline Kanban boards (`Kanban Board` & `/crm/deals`).

---

## Core Architecture & Zero-Code-Change Guarantee

1. **100% Database + Site Files (No Core App Edits)**:
   - All migrated CRM entities are stored cleanly in the ERPNext MariaDB database and `/sites/<site>/public/files/crm/` directory. Zero Python/JS modifications to `frappe`, `erpnext`, or `crm` apps are required.
2. **Proper Decomposition of `res.partner`**:
   - Odoo stores companies, individual contact persons, delivery addresses, system accounts, and guest checkouts in a single `res_partner` table.
   - This skill decomposes `res_partner` into:
     - **`Company`** (updates own company VAT `tax_id` and `Office` address)
     - **`Customer` & `CRM Organization`** (top-level commercial corporations, non-profits, and government/school institutions with `tax_id`, `website`, `customer_group` / `industry`, `territory`, `address`, and company logo)
     - **`Address`** (`Billing` primary addresses and `Shipping` child delivery addresses linked to `Customer`)
     - **`Contact`** (individual contact persons with `email_ids`, normalized `phone_nos`, `designation` from `function`, avatar `image`, and `Dynamic Link` to their parent `Customer` — automatically visible in Frappe CRM `/crm/contacts`)
3. **Complete `crm.lead` Opportunity & `CRM Deal` Migration**:
   - Migrates both active (`active=true`) and lost/archived (`active=false`) opportunities into both ERPNext **`Opportunity`** (`opportunity_from='Customer'`) and Frappe CRM **`CRM Deal`** (`/crm/deals`).
   - Preserves `opportunity_amount` / `deal_value` (`expected_revenue`), `probability`, `sales_stage` / `CRM Deal Status` (`New`, `Qualified`, `Proposition`, `Won`, `Lost`), `opportunity_owner` / `deal_owner`, `expected_closure_date`, `lost_reason`, `Tag` links (`Companies`, `Kids`, `Seniors`), rich HTML `CRM Note` & `FCRM Note` entries, attached PDF `File` records, timeline `Comment` records, and `ToDo` / `CRM Task` follow-ups.
   - Enables native **ERPNext <-> Frappe CRM synchronization** (`CRM Settings.enable_frappe_crm_data_synchronization = 1` and `ERPNext CRM Settings.enabled = 1`).

For detailed field-level mappings and edge cases, read [`references/crm-mapping.md`](references/crm-mapping.md).

---

## Step-by-Step Migration Workflow

### Step 0 (Optional / Recommended): Install the Standalone Frappe CRM App (`frappe/crm`)

If `crm` is not yet installed in `sites/apps.txt`, install `frappe/crm` in `erpnext-backend-1` and sync the app + built frontend assets to the other ERPNext containers:

```bash
# 1. Fetch & install frappe/crm in erpnext-backend-1
sudo -n docker exec -w /home/frappe/frappe-bench erpnext-backend-1 \
  bench get-app --branch main https://github.com/frappe/crm.git
sudo -n docker exec -w /home/frappe/frappe-bench erpnext-backend-1 \
  bench --site frontend install-app crm

# 2. Sync apps/crm and assets/crm to frontend + worker containers
sudo -n docker cp erpnext-backend-1:/home/frappe/frappe-bench/apps/crm /tmp/frappe_crm_app
for c in erpnext-frontend-1 erpnext-scheduler-1 erpnext-websocket-1 erpnext-queue-short-1 erpnext-queue-long-1; do
  sudo -n docker cp /tmp/frappe_crm_app "$c":/home/frappe/frappe-bench/apps/crm
  sudo -n docker exec -u root "$c" chown -R frappe:frappe /home/frappe/frappe-bench/apps/crm
  sudo -n docker exec "$c" /home/frappe/frappe-bench/env/bin/pip install --no-deps -e /home/frappe/frappe-bench/apps/crm
  sudo -n docker exec "$c" ln -sfn /home/frappe/frappe-bench/apps/crm/crm/public /home/frappe/frappe-bench/assets/crm
done
sudo -n docker exec erpnext-backend-1 ln -sfn /home/frappe/frappe-bench/apps/crm/crm/public /home/frappe/frappe-bench/assets/crm
sudo -n docker restart erpnext-backend-1 erpnext-frontend-1 erpnext-scheduler-1 erpnext-websocket-1 erpnext-queue-short-1 erpnext-queue-long-1
```

### Step 1: Extract CRM & Contact Data + Filestore Binaries from Odoo

Run [`scripts/extract_odoo_crm.py`](scripts/extract_odoo_crm.py) on the Docker host to query the Odoo PostgreSQL database (`res_partner`, `res_users`, `crm_lead`, `crm_stage`, `crm_tag`, `crm_lost_reason`, `mail_message`, `mail_activity`, `ir_attachment`) and copy binary PDFs and partner avatars out of the Odoo container filestore (`/etc/odoo/filestore/<db>/`):

```bash
python3 scripts/extract_odoo_crm.py \
  --db-container odoo-db \
  --db-user odoo \
  --db-name odoo \
  --odoo-container odoo-app \
  --output-dir /tmp/odoo_crm_extract
```

**Verify extraction output:**
- `/tmp/odoo_crm_extract/odoo_crm_export.json` contains all partners, users, stages, tags, lost reasons, opportunities, chatter messages, activities, and attachment metadata.
- `/tmp/odoo_crm_extract/files/` contains all PDF attachments (`lead_*.pdf`) and `/tmp/odoo_crm_extract/files/avatars/` contains real partner logos/avatars (`file_size > 500`, skipping Odoo's 147-byte SVG placeholders).

---

### Step 2: Copy Extracted Assets & Run Idempotent Migration in ERPNext

Copy the extracted files and [`scripts/migrate_crm_to_erpnext.py`](scripts/migrate_crm_to_erpnext.py) into the ERPNext backend container (`erpnext-backend-1`) and run the migration script from `/home/frappe/frappe-bench/sites`:

```bash
docker exec erpnext-backend-1 mkdir -p /home/frappe/frappe-bench/sites/frontend/public/files/crm/avatars
docker cp /tmp/odoo_crm_extract/files/. erpnext-backend-1:/home/frappe/frappe-bench/sites/frontend/public/files/crm/
docker cp /tmp/odoo_crm_extract/odoo_crm_export.json erpnext-backend-1:/tmp/odoo_crm_export.json
docker cp scripts/migrate_crm_to_erpnext.py erpnext-backend-1:/tmp/migrate_crm_to_erpnext.py

docker exec -w /home/frappe/frappe-bench/sites erpnext-backend-1 \
  /home/frappe/frappe-bench/env/bin/python /tmp/migrate_crm_to_erpnext.py \
  --input-json /tmp/odoo_crm_export.json \
  --site frontend
```

---

### Step 3: Verify Migrated CRM Data in ERPNext

Run a verification check inside `erpnext-backend-1` to confirm all records and totals match Odoo:

```bash
sudo -n docker exec -w /home/frappe/frappe-bench/sites erpnext-backend-1 \
  /home/frappe/frappe-bench/env/bin/python -c '
import frappe
frappe.init(site="frontend")
frappe.connect()
print("Customers:", frappe.db.count("Customer"))
print("Contacts:", frappe.db.count("Contact"))
print("Addresses:", frappe.db.count("Address"))
print("Opportunities:", frappe.db.count("Opportunity"))
print("CRM Notes:", frappe.db.count("CRM Note"))
print("Opportunity Files:", frappe.db.count("File", {"attached_to_doctype": "Opportunity"}))
print("Opportunity ToDos:", frappe.db.count("ToDo", {"reference_type": "Opportunity"}))
print("Kanban Boards:", frappe.get_all("Kanban Board", filters={"reference_doctype": "Opportunity"}, pluck="name"))
if frappe.db.exists("DocType", "CRM Deal"):
    print("Frappe CRM Organizations:", frappe.db.count("CRM Organization"))
    print("Frappe CRM Deals:", frappe.db.count("CRM Deal"))
    print("Frappe CRM Notes (FCRM Note):", frappe.db.count("FCRM Note"))
    print("Frappe CRM Tasks:", frappe.db.count("CRM Task"))
'
```

---

## Important Implementation Rules & Guardrails

1. **Phone Number Normalization (`normalize_phone`)**:
   - Frappe enforces `PHONE_NUMBER_PATTERN = r"^([0-9\ \+\_\-\,\.\*\#\(\)]){1,20}$"` on `Contact Phone`, `Address.phone`, and `Opportunity.contact_mobile`.
   - Polish phone extensions like `71 718 66 50 wew. 201` must be normalized (`wew.` / `ext.` -> `#`, e.g. `71 718 66 50 #201`) before saving, or `frappe.exceptions.InvalidPhoneNumberError` will be raised.
2. **Preventing Duplicate File Blobs (`copy_from_existing_file`)**:
   - When registering `File` DocType records for files already copied into `/sites/frontend/public/files/crm/`, always set `doc.flags.copy_from_existing_file = True` before calling `doc.insert(ignore_permissions=True)`.
3. **HTML Note Link Rewriting (`clean_odoo_html`)**:
   - Odoo `crm_lead.description` embeds PDF attachments as `<a href="/web/content/<id>?download=true" class="o_image"></a>` with empty inner text. Always rewrite the `href` to `/files/crm/<filename>` and populate visible anchor text (`📎 <filename>`).
4. **Dual Kanban Pipeline Views**:
   - ERPNext's default `Opportunity Pipeline` groups by `status` (`Open`, `Replied`, `Quotation`, `Converted`, `Lost`).
   - Always also create/update `Sales Stage Pipeline` grouped by `sales_stage` (`New` -> `Qualified` -> `Proposition` -> `Won`) so sales users can view the exact 4-column Odoo CRM Kanban board in ERPNext Desk (`/app/opportunity/view/kanban/Sales Stage Pipeline`), alongside the modern Frappe CRM Deals board (`/crm/deals`).
5. **ERPNext <-> Frappe CRM Data Sync Guard (`validate_frappe_crm_sync`)**:
   - Before saving `CRM Deal` records when `ERPNext CRM Settings.enabled = 1`, ensure `CRM Settings.enable_frappe_crm_data_synchronization = 1` is set on ERPNext.
   - During bulk migration of Deals whose ERPNext `Customer` already exists, keep `ERPNext CRM Settings.create_customer_on_status_change = 0` while inserting/saving Deals (linking `deal.erpnext_customer = customer_name` directly), then set `create_customer_on_status_change = 1` after the migration finishes.
