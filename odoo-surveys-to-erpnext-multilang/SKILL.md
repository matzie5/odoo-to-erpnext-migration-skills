---
name: odoo-surveys-to-erpnext-multilang
description: Migrate active non-draft surveys and their non-draft responses (> 2 answers) from Odoo (survey.survey, survey.question, survey.question.answer, survey.grade, survey.user_input, survey.user_input.line) to ERPNext v16 using native Frappe Custom DocTypes (Survey, Survey Response), bilingual Web Forms (/surveys/<slug> and /en/surveys/<slug>), client-side and server-side scoring/grading for assessments, bilingual Survey Directory Web Pages (/surveys and /en/surveys), and legacy Odoo route redirects.
---

# Odoo Surveys to ERPNext Multi-Language Migration Skill

## Purpose

Migrate active Odoo surveys (`survey.survey`) and their historical respondent submissions (`survey.user_input` / `survey.user_input.line`) into ERPNext v15/v16 using **100% native Frappe capabilities** (`Custom DocType`, `Web Form`, `Server Script`, `Web Page`, and `Website Route Redirect`) with full multi-language (`PL | EN` or any primary/secondary language pair) support, **strictly filtering to non-draft surveys and responses with more than 2 answered questions (`> 2` answers)**.

This skill bridges:
1. **Strict Non-Draft `> 2` Answers Filtering**:
   - Filters out draft/inactive surveys (`active = false`) and test/empty surveys that have `<= 2` valid responses.
   - Filters out draft/empty participant sessions (`state = 'new'` or `COUNT(survey_user_input_line WHERE skipped = false) <= 2`), exporting only non-draft responses (`state IN ('done', 'in_progress')`) with `> 2` answered lines.
2. **Native ERPNext Custom DocTypes (`Survey` & `Survey Response`)**:
   - **`Survey`** (`autoname = "field:slug"`): Stores bilingual metadata (`title_pl`, `title_en`, `description_pl`, `description_en`, `scoring_type`, `odoo_survey_id`, `odoo_access_token`, `pl_web_form`, `en_web_form`, `total_responses`) along with child tables:
     - **`Survey Question Item`**: Bilingual questions and section headers (`question_code` `q_01`..`q_20`, `section_pl`, `section_en`, `question_pl`, `question_en`, `question_type`, `options_pl`, `options_en`, `score_map_json`).
     - **`Survey Grade Item`**: Bilingual grading brackets for scored assessments (`grade_name_pl`, `grade_name_en`, `min_score_percentage`, `max_score_percentage`, `description_pl`, `description_en`).
   - **`Survey Response`**: Stores both migrated historical Odoo submissions and new public `Web Form` submissions in a unified structure:
     - Flat fields `q_01`..`q_20` (`Data` / `Small Text`) so native Frappe **`Web Form`** can bind directly to each question in both Polish and English.
     - Child table **`Survey Response Answer`** (`answers`) storing structured per-question records (`question_code`, `question_text`, `answer_value`, `answer_score`, `odoo_question_id`).
     - Scoring & grading summary fields (`scoring_total`, `scoring_percentage`, `achieved_grade`, `achieved_grade_description`, `state`, `language`, `submitted_at`, `respondent_email`, `respondent_name`, `odoo_input_id`, `odoo_access_token`).
3. **Bilingual Native `Web Form`s (`/surveys/<slug>` & `/en/surveys/<slug>`)**:
   - Creates two native Frappe `Web Form` records (`doc_type = "Survey Response"`, `anonymous = 1`, `login_required = 0`, `allow_multiple = 1`) per survey:
     - Primary language (Polish): `/surveys/<slug>`
     - Secondary language (English): `/en/surveys/<slug>`
   - Because `WebForm.validate_fields()` in Frappe only verifies `meta.has_field(df.fieldname)`, both the Polish and English `Web Form`s map to the same `q_01`..`q_20` fields on `Survey Response` while providing language-specific `label`, `fieldtype` (`Select` or `Small Text`), `options`, `Section Break` headers, and UI strings.
   - Because the routes follow `/<path>` and `/en/<path>`, the `Multilingual Navbar` (`🌐 PL ▾` / `🌐 EN ▾`) and `Headline Footer` language dropdown switchers automatically toggle between the Polish and English versions of every survey `Web Form`.
   - Includes interactive `client_script` + `custom_css` on each `Web Form` that renders radio-pill/Likert cards for `Select` questions and calculates the participant's score (`%`) and achieved grade (`Balanced` / `Zrównoważony`, `Controlled` / `Pod kontrolą`, `At Risk` / `W grupie ryzyka`, `Unhealthy` / `Niezdrowy`) immediately upon submission, plus a `Before Save` `Server Script` on `Survey Response` that populates the `answers` child table and verifies scores server-side.
4. **Bilingual Survey Directory (`Web Page`) & Legacy Odoo Redirects**:
   - Creates `/surveys` (Polish) and `/en/surveys` (English) Page Builder `Web Page`s listing the public surveys and assessments, plus `/ankiety` $\rightarrow$ `/surveys`, `/en/ankiety` $\rightarrow$ `/en/surveys`, and `/survey/start/<odoo_access_token>` $\rightarrow$ `/surveys/<slug>` redirects in `Website Settings`.

---

## Core Rules

1. **Export Only Non-Draft Surveys and Responses with `> 2` Answers**:
   - In Odoo, clicking a survey link immediately creates a `survey_user_input` row in `state = 'new'` with `0` answer lines. Always filter `survey_user_input` with `state != 'new'` and `COUNT(survey_user_input_line WHERE skipped = false) > 2`, and only export surveys (`active = true`) that have `> 2` such valid responses.
2. **Share One `Survey Response` DocType Across All Languages via `q_01`..`q_20` Fields**:
   - Define `q_01`..`q_20` on `Survey Response` with `fieldtype = "Small Text"` (or `Data`). In each `Web Form` (`surveys/<slug>` and `en/surveys/<slug>`), configure `Web Form Field` with `fieldtype = "Select"` (for `simple_choice` and `scale` questions) or `Small Text` (for `text_box` questions) and language-specific `label` and `options`.
3. **Zero Core Code Modifications**:
   - Keep 100% of the implementation in database records (`DocType`, `Web Form`, `Server Script`, `Web Page`, `Website Settings`).

---

## Step-by-Step Workflow

### Step 1: Extract Non-Draft Surveys & Responses (`> 2` Answers) from Odoo
Run [`scripts/extract_odoo_surveys.py`](scripts/extract_odoo_surveys.py) against the Odoo PostgreSQL container:

```bash
python3 /home/matthias/.agents/skills/odoo-surveys-to-erpnext-multilang/scripts/extract_odoo_surveys.py \
  --db-container 20261022-db-1 \
  --db-name digitaldetox \
  --db-user odoo \
  --min-answers 2 \
  --output /tmp/odoo_surveys_data.json
```

### Step 2: Migrate Custom DocTypes, Surveys, Historical Responses & Bilingual `Web Form`s into ERPNext
Copy the extracted JSON and migration script into `erpnext-backend-1` and execute with `-w /home/frappe/frappe-bench/sites`:

```bash
sudo docker cp /tmp/odoo_surveys_data.json erpnext-backend-1:/tmp/odoo_surveys_data.json
sudo docker cp /home/matthias/.agents/skills/odoo-surveys-to-erpnext-multilang/scripts/migrate_surveys_to_erpnext.py erpnext-backend-1:/tmp/migrate_surveys_to_erpnext.py
sudo docker exec -w /home/frappe/frappe-bench/sites erpnext-backend-1 \
  /home/frappe/frappe-bench/env/bin/python /tmp/migrate_surveys_to_erpnext.py \
  --site frontend \
  --input /tmp/odoo_surveys_data.json
```

### Step 3: Verify Desk Records, Bilingual `Web Form`s & Scoring
1. Verify `Survey` (`/app/survey`) and `Survey Response` (`/app/survey-response`) records in ERPNext Desk.
2. Verify HTTP `200` on `/surveys`, `/en/surveys`, and all `/surveys/<slug>` ↔ `/en/surveys/<slug>` `Web Form` routes.
3. Submit a test response via `frappe.website.doctype.web_form.web_form.accept` (or browser) and confirm that `Survey Response` automatically populates the `answers` child table, `scoring_total`, `scoring_percentage`, and `achieved_grade`.

---

## References & Scripts
- Field & Schema Mapping Reference: [`references/survey-mapping.md`](references/survey-mapping.md)
- Odoo Survey & Response Extractor: [`scripts/extract_odoo_surveys.py`](scripts/extract_odoo_surveys.py)
- ERPNext Survey, Response & Bilingual Web Form Migrator: [`scripts/migrate_surveys_to_erpnext.py`](scripts/migrate_surveys_to_erpnext.py)
