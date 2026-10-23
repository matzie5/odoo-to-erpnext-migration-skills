#!/usr/bin/env python3
"""
Extract CRM data (Contacts, Companies, Addresses, Sales Users, CRM Stages,
Tags, Lost Reasons, Opportunities, Chatter Messages, Activities, and Attachments)
from an Odoo PostgreSQL container and Odoo filestore container into JSON + files.

Usage:
  python3 extract_odoo_crm.py \
    --db-container odoo-db \
    --db-name odoo \
    --odoo-container odoo-app \
    --output-dir /tmp/odoo_crm_extract
"""

import argparse
import json
import os
import re
import subprocess
import sys


def run_psql_json(container: str, db_name: str, db_user: str, sql: str):
    wrapped = f"SELECT COALESCE(json_agg(t), '[]'::json) FROM ({sql}) t;"
    cmd = [
        "sudo", "-n", "docker", "exec", container,
        "psql", "-U", db_user, "-d", db_name, "-t", "-A", "-c", wrapped,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # fallback without sudo if user is in docker group
        cmd_nosudo = cmd[2:]
        res = subprocess.run(cmd_nosudo, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"psql failed: {res.stderr}")
    raw = res.stdout.strip()
    return json.loads(raw) if raw else []


def docker_cp_from_filestore(odoo_container: str, db_name: str, store_fname: str, dest_path: str) -> bool:
    src = f"{odoo_container}:/etc/odoo/filestore/{db_name}/{store_fname}"
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    for prefix in (["sudo", "-n"], []):
        cmd = prefix + ["docker", "cp", src, dest_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and os.path.exists(dest_path):
            return True
    return False


def slugify_filename(name: str) -> str:
    base, ext = os.path.splitext(name)
    trans = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    base = base.translate(trans).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return f"{base}{ext.lower()}"


def main():
    parser = argparse.ArgumentParser(description="Extract Odoo CRM data and attachments for ERPNext migration.")
    parser.add_argument("--db-container", default="odoo-db")
    parser.add_argument("--db-name", default="odoo")
    parser.add_argument("--db-user", default="odoo")
    parser.add_argument("--odoo-container", default="odoo-app")
    parser.add_argument("--files-prefix", default="/files/crm")
    parser.add_argument("--output-dir", default="/tmp/odoo_crm_extract")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    files_dir = os.path.join(args.output_dir, "files")
    avatars_dir = os.path.join(files_dir, "avatars")
    os.makedirs(files_dir, exist_ok=True)
    os.makedirs(avatars_dir, exist_ok=True)

    users = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT u.id AS user_id, u.login, u.active, u.partner_id,
               p.name AS partner_name, p.email, p.phone, p.function
        FROM res_users u
        LEFT JOIN res_partner p ON u.partner_id = p.id
        ORDER BY u.id
        """,
    )

    partners = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT p.id, p.name, p.parent_id, parent.name AS parent_name,
               p.is_company, p.company_name, p.type, p.email, p.phone,
               p.street, p.street2, p.city, p.zip, p.country_id,
               c.code AS country_code, c.name->>'en_US' AS country_name,
               p.vat, p.website, p.function, p.comment, p.active, p.company_id,
               COALESCE(
                   (SELECT json_agg(cat.name->>'en_US')
                    FROM res_partner_res_partner_category_rel rel
                    JOIN res_partner_category cat ON cat.id = rel.category_id
                    WHERE rel.partner_id = p.id),
                   '[]'::json
               ) AS categories
        FROM res_partner p
        LEFT JOIN res_partner parent ON p.parent_id = parent.id
        LEFT JOIN res_country c ON p.country_id = c.id
        ORDER BY p.id
        """,
    )

    stages = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT id, sequence, is_won, name,
               name->>'en_US' AS name_en,
               COALESCE(name->>'pl_PL', name->>'en_US') AS name_pl
        FROM crm_stage
        ORDER BY sequence, id
        """,
    )

    tags = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT id, color, name,
               name->>'en_US' AS name_en,
               COALESCE(name->>'pl_PL', name->>'en_US') AS name_pl
        FROM crm_tag
        ORDER BY id
        """,
    )

    lost_reasons = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT id, active, name,
               name->>'en_US' AS name_en,
               COALESCE(name->>'pl_PL', name->>'en_US') AS name_pl
        FROM crm_lost_reason
        ORDER BY id
        """,
    )

    opportunities = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT l.id, l.name, l.type, l.active, l.priority,
               l.stage_id, s.name->>'en_US' AS stage_name_en,
               l.user_id, u.login AS user_login,
               l.partner_id, l.partner_name, l.contact_name,
               l.email_from, l.phone, l.function, l.website,
               l.street, l.street2, l.city, l.zip,
               l.expected_revenue, l.prorated_revenue,
               l.probability, l.automated_probability,
               l.lost_reason_id, lr.name->>'en_US' AS lost_reason_en,
               lr.name->>'pl_PL' AS lost_reason_pl,
               l.date_deadline, l.date_closed, l.date_open,
               l.create_date, l.write_date, l.description,
               COALESCE(
                   (SELECT json_agg(t.name->>'en_US' ORDER BY t.id)
                    FROM crm_tag_rel rel
                    JOIN crm_tag t ON t.id = rel.tag_id
                    WHERE rel.lead_id = l.id),
                   '[]'::json
               ) AS tags
        FROM crm_lead l
        LEFT JOIN crm_stage s ON l.stage_id = s.id
        LEFT JOIN res_users u ON l.user_id = u.id
        LEFT JOIN crm_lost_reason lr ON l.lost_reason_id = lr.id
        ORDER BY l.id
        """,
    )

    messages = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT m.id, m.model, m.res_id, m.message_type, m.subtype_id,
               m.subject, m.email_from, m.author_id, p.name AS author_name,
               p.email AS author_email, m.date, m.body
        FROM mail_message m
        LEFT JOIN res_partner p ON m.author_id = p.id
        WHERE m.model IN ('crm.lead', 'res.partner')
          AND m.message_type IN ('comment', 'email')
        ORDER BY m.model, m.res_id, m.date
        """,
    )

    activities = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT a.id, a.res_model, a.res_id, a.res_name,
               a.activity_type_id, at.name->>'en_US' AS activity_type_name,
               a.summary, a.note, a.date_deadline,
               a.user_id, u.login AS user_login, a.create_date
        FROM mail_activity a
        LEFT JOIN mail_activity_type at ON a.activity_type_id = at.id
        LEFT JOIN res_users u ON a.user_id = u.id
        WHERE a.res_model IN ('crm.lead', 'res.partner')
        ORDER BY a.id
        """,
    )

    attachments = run_psql_json(
        args.db_container,
        args.db_name,
        args.db_user,
        """
        SELECT id, name, res_model, res_id, store_fname, mimetype, file_size, access_token
        FROM ir_attachment
        WHERE (res_model = 'crm.lead')
           OR (res_model = 'res.partner' AND name = 'image_1920' AND file_size > 500)
        ORDER BY res_model, res_id, id
        """,
    )

    files_prefix = args.files_prefix.rstrip("/")
    downloaded_files = []
    for att in attachments:
        store_fname = att.get("store_fname")
        if not store_fname:
            continue
        if att["res_model"] == "crm.lead":
            clean_name = f"lead_{att['res_id']}_{slugify_filename(att['name'])}"
            dest = os.path.join(files_dir, clean_name)
            rel_url = f"{files_prefix}/{clean_name}"
        else:
            ext = ".png" if "png" in (att.get("mimetype") or "") else ".jpg"
            clean_name = f"partner_{att['res_id']}{ext}"
            dest = os.path.join(avatars_dir, clean_name)
            rel_url = f"{files_prefix}/avatars/{clean_name}"

        ok = docker_cp_from_filestore(args.odoo_container, args.db_name, store_fname, dest)
        att["local_filename"] = clean_name
        att["erpnext_url"] = rel_url
        att["downloaded"] = ok
        downloaded_files.append(att)

    payload = {
        "users": users,
        "partners": partners,
        "stages": stages,
        "tags": tags,
        "lost_reasons": lost_reasons,
        "opportunities": opportunities,
        "messages": messages,
        "activities": activities,
        "attachments": downloaded_files,
    }

    out_json = os.path.join(args.output_dir, "odoo_crm_export.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Extracted {len(partners)} partners, {len(opportunities)} opportunities, "
          f"{len(stages)} stages, {len(tags)} tags, {len(lost_reasons)} lost reasons, "
          f"{len(messages)} chatter messages, {len(activities)} activities, and "
          f"{sum(1 for a in downloaded_files if a['downloaded'])}/{len(downloaded_files)} files -> {out_json}")


if __name__ == "__main__":
    main()
