#!/usr/bin/env python3
"""
Migrate extracted Odoo surveys and responses into ERPNext using:
1. Custom DocTypes: Survey, Survey Question Item, Survey Grade Item, Survey Response, Survey Response Answer
2. Server Script: Survey Response - Process Web Form Submission (Before Save)
3. Bilingual Web Forms: /surveys/<slug> (PL) and /en/surveys/<slug> (EN)
4. Bilingual Survey Directory Web Pages: /surveys and /en/surveys (with Survey Catalog Section Web Template)
5. Legacy Odoo route redirects (/survey/start/<access_token> -> /surveys/<slug>, /ankiety -> /surveys)
"""
import argparse
import json
import os
import frappe


CUSTOM_CSS = """
.web-form-container {
    max-width: 860px;
    margin: 2.5rem auto;
    background: #ffffff;
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(49, 69, 89, 0.08);
    padding: 2.5rem 2.75rem;
}
.web-form-header {
    border-bottom: 1px solid #e7eef4;
    padding-bottom: 1.25rem;
    margin-bottom: 1.75rem;
}
.web-form-title h1 {
    color: #314559;
    font-weight: 700;
    font-size: 2rem;
}
.web-form-introduction {
    color: #4a5d70;
    font-size: 1.05rem;
    line-height: 1.6;
}
.frappe-control[data-fieldname^="q_"] {
    background: #f8fafb;
    border: 1px solid #e6eef4;
    border-radius: 12px;
    padding: 1.15rem 1.35rem;
    margin-bottom: 1.15rem;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.frappe-control[data-fieldname^="q_"]:hover {
    border-color: #6099b9;
}
.frappe-control[data-fieldname^="q_"] .control-label {
    font-size: 1.02rem;
    font-weight: 600;
    color: #243746;
    margin-bottom: 0.7rem;
    line-height: 1.45;
}
.form-section .section-head {
    color: #314559;
    font-size: 1.25rem;
    font-weight: 700;
    margin-top: 1.5rem;
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid #6099b9;
}
.ihc-choice-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
    margin-top: 0.35rem;
}
.ihc-choice-pill {
    border: 1.5px solid #cbd8e3;
    background: #ffffff;
    color: #314559;
    border-radius: 999px;
    padding: 0.48rem 1rem;
    font-size: 0.92rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
    user-select: none;
}
.ihc-choice-pill:hover {
    border-color: #6099b9;
    background: #f0f6fa;
}
.ihc-choice-pill.active {
    background: #314559;
    border-color: #314559;
    color: #ffffff;
    box-shadow: 0 3px 10px rgba(49, 69, 89, 0.2);
}
.ihc-grade-result-card {
    margin: 1.5rem auto 1rem;
    padding: 1.75rem;
    border-radius: 14px;
    background: #f4f8fb;
    border-left: 6px solid #6099b9;
    text-align: left;
    max-width: 680px;
}
.ihc-grade-badge {
    display: inline-block;
    background: #314559;
    color: #fff;
    font-weight: 700;
    padding: 0.35rem 0.95rem;
    border-radius: 999px;
    font-size: 0.95rem;
    margin-bottom: 0.75rem;
}
.ihc-grade-score {
    font-size: 2rem;
    font-weight: 800;
    color: #314559;
    margin-bottom: 0.5rem;
}
.ihc-lang-dropdown .ihc-lang-toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.35rem 0.85rem !important;
    border-radius: 999px;
    border: 1.5px solid #314559;
    background: #fff;
    color: #314559 !important;
    font-weight: 700;
    font-size: 0.85rem;
}
.ihc-lang-dropdown .ihc-lang-menu {
    min-width: 160px;
    border-radius: 12px;
    padding: 0.4rem;
    box-shadow: 0 8px 24px rgba(15, 40, 48, 0.14);
}
"""


def build_client_script(survey: dict, lang: str) -> str:
    slug = survey["slug"]
    cfg = {
        "slug": slug,
        "lang": lang,
        "pl_url": f"/surveys/{slug}",
        "en_url": f"/en/surveys/{slug}",
        "scoring_type": survey["scoring_type"],
        "questions": [
            {
                "code": q["question_code"],
                "type": q["question_type"],
                "score_map": q["score_map"],
            }
            for q in survey["questions"]
        ],
        "grades": [
            {
                "name": g["grade_name_pl"] if lang == "pl" else g["grade_name_en"],
                "min": g["min_score_percentage"],
                "max": g["max_score_percentage"],
                "desc": g["description_pl"] if lang == "pl" else g["description_en"],
            }
            for g in survey["grades"]
        ],
    }
    cfg_json = json.dumps(cfg, ensure_ascii=False)
    return f"""
const IHC_SURVEY_CFG = {cfg_json};

frappe.ready(function() {{
    const urlSearch = window.location.search || '';
    const params = new URLSearchParams(urlSearch);
    const courseParam = (
        params.get('course') ||
        params.get('course_id') ||
        params.get('id') ||
        params.get('event') ||
        params.get('cohort') ||
        params.get('group') ||
        ''
    ).trim();

    // 1. Inject Multilingual Language Dropdown Switcher & English Navbar Translations on Web Form pages
    const $rightNav = $('.navbar .navbar-collapse ul.ml-auto');
    if ($rightNav.length && !$('#ihc-lang-dropdown-btn').length) {{
        const currUpper = IHC_SURVEY_CFG.lang.toUpperCase();
        const plActive = IHC_SURVEY_CFG.lang === 'pl' ? 'active-lang font-weight-bold' : '';
        const enActive = IHC_SURVEY_CFG.lang === 'en' ? 'active-lang font-weight-bold' : '';
        const switcherHtml = `
            <li class="nav-item dropdown ihc-lang-dropdown my-2 my-lg-0 mr-lg-3">
                <a class="nav-link dropdown-toggle ihc-lang-toggle" href="#" id="ihc-lang-dropdown-btn" role="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
                    <span aria-hidden="true">🌐</span>
                    <span class="ihc-lang-curr-code">${{currUpper}}</span>
                </a>
                <ul class="dropdown-menu dropdown-menu-right ihc-lang-menu" aria-labelledby="ihc-lang-dropdown-btn">
                    <li class="dropdown-item ${{plActive}}">
                        <a class="d-flex align-items-center justify-content-between" href="${{IHC_SURVEY_CFG.pl_url}}${{urlSearch}}" onclick="document.cookie='preferred_language=pl; path=/; max-age=31536000';">
                            <span>Polski <small class="text-muted">(PL)</small></span>${{IHC_SURVEY_CFG.lang === 'pl' ? '<span class="ml-2">✓</span>' : ''}}
                        </a>
                    </li>
                    <li class="dropdown-item ${{enActive}}">
                        <a class="d-flex align-items-center justify-content-between" href="${{IHC_SURVEY_CFG.en_url}}${{urlSearch}}" onclick="document.cookie='preferred_language=en; path=/; max-age=31536000';">
                            <span>English <small class="text-muted">(EN)</small></span>${{IHC_SURVEY_CFG.lang === 'en' ? '<span class="ml-2">✓</span>' : ''}}
                        </a>
                    </li>
                </ul>
            </li>`;
        $rightNav.append(switcherHtml);
    }}

    if (IHC_SURVEY_CFG.lang === 'en') {{
        const navMap = {{
            'Strona główna': 'Home',
            'Instytut Higieny Cyfrowej': 'Digital Hygiene Institute',
            'O nas': 'About us',
            'Oferta': 'Services',
            'Szkolenia dla firm': 'Trainings for business',
            'Warsztaty dla dzieci i szkół': 'Workshops for children & schools',
            'Oferty indywidualne i rodzinne': 'Individual & family offers',
            'Indywidualna konsultacja online': 'Individual online consultation',
            'Metoda LEGO® SERIOUS PLAY®': 'LEGO® SERIOUS PLAY® Method',
            'Sklep': 'Shop',
            'Wiedza': 'Knowledge',
            'Blog': 'Blog',
            'Samoocena': 'Self-assessment',
            'Ankiety': 'Surveys',
            'Wydarzenia': 'Events',
            'Skontaktuj się z nami': 'Contact us'
        }};
        $('.navbar a.nav-link, .navbar a.dropdown-item, .navbar a.navbar-cta').each(function() {{
            const txt = $(this).text().trim();
            if (navMap[txt]) {{
                $(this).text(navMap[txt]);
            }}
            const href = $(this).attr('href');
            if (href && href.startsWith('/') && !href.startsWith('/en') && !href.startsWith('/files')) {{
                $(this).attr('href', href === '/' ? '/en' : '/en' + href);
            }}
        }});
        $('.navbar a.navbar-brand').attr('href', '/en');
    }}

    // 2. Capture course_id from URL parameter (?course=..., ?course_id=..., ?id=..., ?event=..., ?cohort=...)
    setTimeout(function() {{
        const effectiveCourse = courseParam || 'general';
        if (frappe.web_form && frappe.web_form.set_value) {{
            frappe.web_form.set_value('course_id', effectiveCourse);
        }}
        $('[data-fieldname="course_id"]').hide();
        if (courseParam && !$('#ihc-course-badge').length) {{
            const badgeLabel = IHC_SURVEY_CFG.lang === 'pl' ? 'Szkolenie / Kurs' : 'Course / Event';
            const $badge = $(`<div id="ihc-course-badge" class="mb-3"><span class="badge badge-pill px-3 py-2" style="background:#e3eff6; color:#314559; font-size:0.88rem; font-weight:600;">${{badgeLabel}}: ${{frappe.utils.escape_html(courseParam)}}</span></div>`);
            $('.web-form-header, .web-form-introduction, .web-form-body').first().prepend($badge);
        }}

        // 3. Enhance Select questions with interactive pill buttons
        IHC_SURVEY_CFG.questions.forEach(function(q) {{
            if (q.type !== 'simple_choice' && q.type !== 'scale') return;
            const $ctrl = $('[data-fieldname="' + q.code + '"]');
            const $select = $ctrl.find('select');
            if (!$select.length || $ctrl.find('.ihc-choice-pills').length) return;

            const $pills = $('<div class="ihc-choice-pills"></div>');
            $select.find('option').each(function() {{
                const val = $(this).val();
                if (!val) return;
                const $btn = $('<button type="button" class="ihc-choice-pill"></button>').text(val);
                $btn.on('click', function() {{
                    $pills.find('.ihc-choice-pill').removeClass('active');
                    $btn.addClass('active');
                    frappe.web_form.set_value(q.code, val);
                }});
                $pills.append($btn);
            }});
            $select.hide();
            $select.after($pills);
        }});
    }}, 250);

    function computeSurveyScore() {{
        let total = 0;
        let answered = 0;
        IHC_SURVEY_CFG.questions.forEach(function(q) {{
            const val = (frappe.web_form.get_value(q.code) || '').trim();
            if (val) {{
                answered += 1;
                const sc = q.score_map[val];
                if (typeof sc === 'number') {{
                    total += sc;
                }}
            }}
        }});
        const maxScore = IHC_SURVEY_CFG.questions.length * 5.0;
        const pct = maxScore > 0 ? Math.round((total / maxScore) * 1000) / 10 : 0;
        let gradeName = '';
        let gradeDesc = '';
        if (IHC_SURVEY_CFG.scoring_type === 'grading_with_answers' && IHC_SURVEY_CFG.grades.length) {{
            const roundedPct = Math.round(pct);
            IHC_SURVEY_CFG.grades.forEach(function(g) {{
                if (roundedPct >= g.min && roundedPct <= g.max) {{
                    gradeName = g.name;
                    gradeDesc = g.desc;
                }}
            }});
        }}
        return {{ total: total, pct: pct, gradeName: gradeName, gradeDesc: gradeDesc, answered: answered }};
    }}

    frappe.web_form.validate = function() {{
        const res = computeSurveyScore();
        window._ihcLastSurveyResult = res;
        if (frappe.web_form.fields_dict['scoring_total']) {{
            frappe.web_form.set_value('scoring_total', res.total);
        }}
        if (frappe.web_form.fields_dict['scoring_percentage']) {{
            frappe.web_form.set_value('scoring_percentage', res.pct);
        }}
        if (res.gradeName && frappe.web_form.fields_dict['achieved_grade']) {{
            frappe.web_form.set_value('achieved_grade', res.gradeName);
        }}
        if (res.gradeDesc && frappe.web_form.fields_dict['achieved_grade_description']) {{
            frappe.web_form.set_value('achieved_grade_description', res.gradeDesc);
        }}
        return true;
    }};

    frappe.web_form.after_save = function() {{
        const res = window._ihcLastSurveyResult || computeSurveyScore();
        if (IHC_SURVEY_CFG.scoring_type === 'grading_with_answers' && res.gradeName) {{
            setTimeout(function() {{
                const scoreLbl = IHC_SURVEY_CFG.lang === 'pl' ? 'Twój wynik' : 'Your score';
                const gradeLbl = IHC_SURVEY_CFG.lang === 'pl' ? 'Poziom higieny cyfrowej' : 'Digital hygiene level';
                const html = '<div class="ihc-grade-result-card">' +
                    '<div class="ihc-grade-badge">' + gradeLbl + ': ' + res.gradeName + '</div>' +
                    '<div class="ihc-grade-score">' + scoreLbl + ': ' + res.pct + '%</div>' +
                    '<div class="ihc-grade-desc">' + res.gradeDesc + '</div>' +
                    '</div>';
                const $target = $('.success-body, .web-form-success, .page-content-wrapper').first();
                if ($target.length && !$target.find('.ihc-grade-result-card').length) {{
                    $target.find('.success-message, p').first().after(html);
                }}
            }}, 200);
        }}
    }};
}});
"""


def ensure_custom_doctypes():
    # 1. Survey Question Item (Child Table)
    if not frappe.db.exists("DocType", "Survey Question Item"):
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Survey Question Item",
            "module": "Website",
            "custom": 1,
            "istable": 1,
            "editable_grid": 1,
            "fields": [
                {"fieldname": "question_code", "label": "Question Code", "fieldtype": "Data", "reqd": 1, "in_list_view": 1, "columns": 1},
                {"fieldname": "section_pl", "label": "Section (PL)", "fieldtype": "Data", "in_list_view": 1, "columns": 2},
                {"fieldname": "section_en", "label": "Section (EN)", "fieldtype": "Data"},
                {"fieldname": "question_pl", "label": "Question (PL)", "fieldtype": "Small Text", "reqd": 1, "in_list_view": 1, "columns": 3},
                {"fieldname": "question_en", "label": "Question (EN)", "fieldtype": "Small Text", "reqd": 1, "in_list_view": 1, "columns": 3},
                {"fieldname": "question_type", "label": "Type", "fieldtype": "Select", "options": "simple_choice\nscale\ntext_box", "default": "simple_choice", "in_list_view": 1, "columns": 1},
                {"fieldname": "mandatory", "label": "Mandatory", "fieldtype": "Check", "default": "1"},
                {"fieldname": "options_pl", "label": "Options (PL)", "fieldtype": "Small Text"},
                {"fieldname": "options_en", "label": "Options (EN)", "fieldtype": "Small Text"},
                {"fieldname": "score_map_json", "label": "Score Map JSON", "fieldtype": "Code", "options": "JSON"},
                {"fieldname": "odoo_question_id", "label": "Odoo Question ID", "fieldtype": "Int"},
            ],
        })
        doc.insert(ignore_permissions=True)

    # 2. Survey Grade Item (Child Table)
    if not frappe.db.exists("DocType", "Survey Grade Item"):
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Survey Grade Item",
            "module": "Website",
            "custom": 1,
            "istable": 1,
            "editable_grid": 1,
            "fields": [
                {"fieldname": "grade_name_pl", "label": "Grade Name (PL)", "fieldtype": "Data", "reqd": 1, "in_list_view": 1, "columns": 2},
                {"fieldname": "grade_name_en", "label": "Grade Name (EN)", "fieldtype": "Data", "reqd": 1, "in_list_view": 1, "columns": 2},
                {"fieldname": "min_score_percentage", "label": "Min Score (%)", "fieldtype": "Float", "in_list_view": 1, "columns": 2},
                {"fieldname": "max_score_percentage", "label": "Max Score (%)", "fieldtype": "Float", "in_list_view": 1, "columns": 2},
                {"fieldname": "description_pl", "label": "Description (PL)", "fieldtype": "Small Text", "in_list_view": 1, "columns": 2},
                {"fieldname": "description_en", "label": "Description (EN)", "fieldtype": "Small Text"},
                {"fieldname": "odoo_grade_id", "label": "Odoo Grade ID", "fieldtype": "Int"},
            ],
        })
        doc.insert(ignore_permissions=True)

    # 3. Survey Response Answer (Child Table)
    if not frappe.db.exists("DocType", "Survey Response Answer"):
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Survey Response Answer",
            "module": "Website",
            "custom": 1,
            "istable": 1,
            "editable_grid": 1,
            "fields": [
                {"fieldname": "question_code", "label": "Code", "fieldtype": "Data", "reqd": 1, "in_list_view": 1, "columns": 1},
                {"fieldname": "question_text", "label": "Question", "fieldtype": "Small Text", "in_list_view": 1, "columns": 5},
                {"fieldname": "answer_value", "label": "Answer", "fieldtype": "Small Text", "in_list_view": 1, "columns": 3},
                {"fieldname": "answer_score", "label": "Score", "fieldtype": "Float", "in_list_view": 1, "columns": 1},
                {"fieldname": "odoo_question_id", "label": "Odoo Question ID", "fieldtype": "Int"},
            ],
        })
        doc.insert(ignore_permissions=True)

    # 4. Survey (Main DocType)
    if not frappe.db.exists("DocType", "Survey"):
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Survey",
            "module": "Website",
            "custom": 1,
            "autoname": "field:slug",
            "naming_rule": "By fieldname",
            "title_field": "title_pl",
            "search_fields": "title_pl,title_en,slug",
            "fields": [
                {"fieldname": "slug", "label": "Slug", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
                {"fieldname": "title_pl", "label": "Title (PL)", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "title_en", "label": "Title (EN)", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
                {"fieldname": "column_break_meta", "fieldtype": "Column Break"},
                {"fieldname": "scoring_type", "label": "Scoring Type", "fieldtype": "Select", "options": "no_scoring\ngrading_with_answers\nscoring_with_answers", "default": "no_scoring", "in_list_view": 1},
                {"fieldname": "total_responses", "label": "Total Responses", "fieldtype": "Int", "default": "0", "read_only": 1, "in_list_view": 1},
                {"fieldname": "pl_web_form", "label": "Polish Web Form", "fieldtype": "Link", "options": "Web Form", "read_only": 1},
                {"fieldname": "en_web_form", "label": "English Web Form", "fieldtype": "Link", "options": "Web Form", "read_only": 1},
                {"fieldname": "pl_route", "label": "Polish Public URL", "fieldtype": "Data", "read_only": 1},
                {"fieldname": "en_route", "label": "English Public URL", "fieldtype": "Data", "read_only": 1},
                {"fieldname": "odoo_survey_id", "label": "Odoo Survey ID", "fieldtype": "Int", "read_only": 1},
                {"fieldname": "odoo_access_token", "label": "Odoo Access Token", "fieldtype": "Data", "read_only": 1},
                {"fieldname": "section_descriptions", "label": "Descriptions", "fieldtype": "Section Break"},
                {"fieldname": "description_pl", "label": "Description (PL)", "fieldtype": "Text Editor"},
                {"fieldname": "column_break_desc", "fieldtype": "Column Break"},
                {"fieldname": "description_en", "label": "Description (EN)", "fieldtype": "Text Editor"},
                {"fieldname": "section_questions", "label": "Questions", "fieldtype": "Section Break"},
                {"fieldname": "questions", "label": "Questions", "fieldtype": "Table", "options": "Survey Question Item"},
                {"fieldname": "section_grades", "label": "Grading Brackets", "fieldtype": "Section Break"},
                {"fieldname": "grades", "label": "Grades", "fieldtype": "Table", "options": "Survey Grade Item"},
            ],
            "permissions": [
                {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "export": 1, "report": 1},
                {"role": "Website Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "export": 1, "report": 1},
                {"role": "All", "read": 1},
            ],
        })
        doc.insert(ignore_permissions=True)

    # 5. Survey Response (Main DocType backing native Web Forms + historical Odoo results)
    if not frappe.db.exists("DocType", "Survey Response"):
        fields = [
            {"fieldname": "survey", "label": "Survey", "fieldtype": "Link", "options": "Survey", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "course_id", "label": "Course / Event ID", "fieldtype": "Data", "default": "general", "in_list_view": 1, "in_standard_filter": 1, "search_index": 1},
            {"fieldname": "state", "label": "Status", "fieldtype": "Select", "options": "done\nin_progress", "default": "done", "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "language", "label": "Language", "fieldtype": "Select", "options": "pl\nen", "default": "pl", "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "submitted_at", "label": "Submitted At", "fieldtype": "Datetime", "in_list_view": 1},
            {"fieldname": "column_break_score", "fieldtype": "Column Break"},
            {"fieldname": "scoring_total", "label": "Total Score", "fieldtype": "Float", "in_list_view": 1},
            {"fieldname": "scoring_percentage", "label": "Score (%)", "fieldtype": "Float", "in_list_view": 1},
            {"fieldname": "achieved_grade", "label": "Achieved Grade", "fieldtype": "Data", "in_list_view": 1, "in_standard_filter": 1},
            {"fieldname": "respondent_name", "label": "Respondent Name", "fieldtype": "Data"},
            {"fieldname": "respondent_email", "label": "Respondent Email", "fieldtype": "Data"},
            {"fieldname": "is_test_entry", "label": "Test Entry", "fieldtype": "Check", "default": "0"},
            {"fieldname": "odoo_input_id", "label": "Odoo Input ID", "fieldtype": "Int", "read_only": 1},
            {"fieldname": "odoo_access_token", "label": "Odoo Access Token", "fieldtype": "Data", "read_only": 1},
            {"fieldname": "section_grade_desc", "label": "Assessment Feedback", "fieldtype": "Section Break"},
            {"fieldname": "achieved_grade_description", "label": "Achieved Grade Description", "fieldtype": "Text Editor"},
            {"fieldname": "section_answers", "label": "Structured Answers", "fieldtype": "Section Break"},
            {"fieldname": "answers", "label": "Answers", "fieldtype": "Table", "options": "Survey Response Answer"},
            {"fieldname": "section_webform_questions", "label": "Web Form Question Fields (q_01 .. q_20)", "fieldtype": "Section Break", "collapsible": 1},
        ]
        for idx in range(1, 21):
            fields.append({
                "fieldname": f"q_{idx:02d}",
                "label": f"Question {idx:02d}",
                "fieldtype": "Small Text",
            })
        doc = frappe.get_doc({
            "doctype": "DocType",
            "name": "Survey Response",
            "module": "Website",
            "custom": 1,
            "autoname": "format:SR-{#####}",
            "naming_rule": "Expression",
            "title_field": "survey",
            "search_fields": "survey,course_id,achieved_grade,respondent_email,state",
            "fields": fields,
            "permissions": [
                {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "export": 1, "report": 1},
                {"role": "Website Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "export": 1, "report": 1},
            ],
        })
        doc.insert(ignore_permissions=True)
    else:
        doc = frappe.get_doc("DocType", "Survey Response")
        changed = False
        if not any(f.fieldname == "course_id" for f in doc.fields):
            doc.insert_field if hasattr(doc, "insert_field") else None
            new_fields = []
            for f in doc.fields:
                new_fields.append(f.as_dict())
                if f.fieldname == "survey":
                    new_fields.append({
                        "fieldname": "course_id",
                        "label": "Course / Event ID",
                        "fieldtype": "Data",
                        "default": "general",
                        "in_list_view": 1,
                        "in_standard_filter": 1,
                        "search_index": 1,
                    })
            doc.set("fields", new_fields)
            doc.search_fields = "survey,course_id,achieved_grade,respondent_email,state"
            changed = True
        if any(p.role == "Guest" for p in doc.permissions):
            doc.permissions = [p for p in doc.permissions if p.role != "Guest"]
            changed = True
        if changed:
            doc.save(ignore_permissions=True)

    frappe.db.commit()


def ensure_server_script():
    # Ensure server_script_enabled is active in common_site_config.json
    common_config_path = os.path.join(frappe.get_site_path(".."), "common_site_config.json")
    if os.path.exists(common_config_path):
        with open(common_config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if not cfg.get("server_script_enabled"):
            cfg["server_script_enabled"] = 1
            with open(common_config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=1)
        frappe.conf["server_script_enabled"] = 1
        frappe.get_common_site_config(cached=False)

    script_name = "Survey Response - Process Web Form Submission"
    script_code = """
if not doc.submitted_at:
    doc.submitted_at = frappe.utils.now_datetime()

if not doc.state:
    doc.state = "done"

if not doc.course_id:
    doc.course_id = "general"

if doc.survey and not doc.answers:
    survey_doc = frappe.get_doc("Survey", doc.survey)
    lang = doc.language or "pl"
    total_score = 0.0
    max_possible = 0.0
    for q in survey_doc.questions:
        score_map = json.loads(q.score_map_json or "{}")
        if score_map:
            max_possible = max_possible + max([float(v) for v in score_map.values()])
        val = (doc.get(q.question_code) or "").strip()
        if not val:
            continue
        sc = float(score_map.get(val, 0.0))
        total_score = total_score + sc
        doc.append("answers", {
            "question_code": q.question_code,
            "question_text": q.question_pl if lang == "pl" else q.question_en,
            "answer_value": val,
            "answer_score": sc,
            "odoo_question_id": q.odoo_question_id,
        })

    if doc.answers and max_possible > 0:
        doc.scoring_total = total_score
        doc.scoring_percentage = round((total_score / max_possible) * 100.0, 2)
        if survey_doc.scoring_type == "grading_with_answers":
            rounded_pct = round(doc.scoring_percentage or 0.0)
            for g in survey_doc.grades:
                if g.min_score_percentage <= rounded_pct <= g.max_score_percentage:
                    if g.grade_name_pl and g.grade_name_en and g.grade_name_pl != g.grade_name_en:
                        doc.achieved_grade = f"{g.grade_name_pl} / {g.grade_name_en}"
                    else:
                        doc.achieved_grade = g.grade_name_pl or g.grade_name_en
                    doc.achieved_grade_description = g.description_pl if lang == "pl" else g.description_en
                    break
"""
    if frappe.db.exists("Server Script", script_name):
        ss = frappe.get_doc("Server Script", script_name)
    else:
        ss = frappe.new_doc("Server Script")
        ss.name = script_name

    ss.script_type = "DocType Event"
    ss.reference_doctype = "Survey Response"
    ss.doctype_event = "Before Save"
    ss.disabled = 0
    ss.script = script_code.strip()
    ss.save(ignore_permissions=True)
    frappe.db.commit()


def build_web_form_fields(survey: dict, lang: str) -> list[dict]:
    fields = [
        {
            "fieldname": "survey",
            "label": "Ankieta" if lang == "pl" else "Survey",
            "fieldtype": "Link",
            "options": "Survey",
            "default": survey["slug"],
            "hidden": 1,
            "reqd": 1,
        },
        {
            "fieldname": "course_id",
            "label": "Identyfikator kursu / szkolenia" if lang == "pl" else "Course / Event ID",
            "fieldtype": "Data",
            "default": "general",
            "read_only": 1,
        },
        {
            "fieldname": "language",
            "label": "Język" if lang == "pl" else "Language",
            "fieldtype": "Data",
            "default": lang,
            "hidden": 1,
        },
        {
            "fieldname": "state",
            "label": "Status",
            "fieldtype": "Data",
            "default": "done",
            "hidden": 1,
        },
        {
            "fieldname": "scoring_total",
            "label": "Wynik punktowy" if lang == "pl" else "Total Score",
            "fieldtype": "Float",
            "default": "0",
            "hidden": 1,
        },
        {
            "fieldname": "scoring_percentage",
            "label": "Wynik (%)" if lang == "pl" else "Score (%)",
            "fieldtype": "Float",
            "default": "0",
            "hidden": 1,
        },
        {
            "fieldname": "achieved_grade",
            "label": "Poziom" if lang == "pl" else "Achieved Grade",
            "fieldtype": "Data",
            "hidden": 1,
        },
        {
            "fieldname": "achieved_grade_description",
            "label": "Opis wyniku" if lang == "pl" else "Grade Description",
            "fieldtype": "Text Editor",
            "hidden": 1,
        },
    ]

    last_section = None
    sec_counter = 0
    for q in survey["questions"]:
        sec = q["section_pl"] if lang == "pl" else q["section_en"]
        if sec and sec != last_section:
            sec_counter += 1
            fields.append({
                "fieldname": f"sec_break_{sec_counter}",
                "label": sec,
                "fieldtype": "Section Break",
            })
            last_section = sec

        q_label = q["question_pl"] if lang == "pl" else q["question_en"]
        q_type = q["question_type"]
        if q_type in ("simple_choice", "scale"):
            opts = q["options_pl"] if lang == "pl" else q["options_en"]
            fields.append({
                "fieldname": q["question_code"],
                "label": q_label,
                "fieldtype": "Select",
                "options": "\n".join(opts),
                "reqd": q.get("mandatory", 1),
            })
        else:
            fields.append({
                "fieldname": q["question_code"],
                "label": q_label,
                "fieldtype": "Small Text",
                "reqd": 0,
            })

    # Optional respondent info section at bottom
    fields.append({
        "fieldname": "sec_respondent_info",
        "label": "Dane kontaktowe (opcjonalnie)" if lang == "pl" else "Contact Details (optional)",
        "fieldtype": "Section Break",
    })
    fields.append({
        "fieldname": "respondent_name",
        "label": "Imię / Pseudonim (opcjonalnie)" if lang == "pl" else "Name / Nickname (optional)",
        "fieldtype": "Data",
        "reqd": 0,
    })
    fields.append({
        "fieldname": "respondent_email",
        "label": "Adres e-mail (opcjonalnie)" if lang == "pl" else "Email Address (optional)",
        "fieldtype": "Data",
        "reqd": 0,
    })

    return fields


def upsert_web_form(survey: dict, lang: str) -> str:
    slug = survey["slug"]
    wf_name = f"survey-{slug}-pl" if lang == "pl" else f"survey-{slug}-en"
    route = f"surveys/{slug}" if lang == "pl" else f"en/surveys/{slug}"
    title = survey["title_pl"] if lang == "pl" else survey["title_en"]
    intro = survey["description_pl"] if lang == "pl" else survey["description_en"]

    is_graded = survey["scoring_type"] == "grading_with_answers"
    if lang == "pl":
        btn_label = "Sprawdź swój wynik" if is_graded else "Wyślij odpowiedzi"
        success_title = "Twój wynik oceny higieny cyfrowej" if is_graded else "Dziękujemy za wypełnienie ankiety!"
        success_msg = (
            "Twoje odpowiedzi zostały zapisane. Poniżej znajduje się podsumowanie Twojego wyniku. "
            "Chcesz porozmawiać o higienie cyfrowej w swojej szkole lub firmie? Skontaktuj się z nami!"
            if is_graded
            else "Dziękujemy za poświęcony czas! Twoja opinia została zapisana i pomoże nam w dalszym doskonaleniu naszych szkoleń i webinarów."
        )
    else:
        btn_label = "Calculate My Score" if is_graded else "Submit Feedback"
        success_title = "Your Digital Hygiene Assessment Result" if is_graded else "Thank you for completing the survey!"
        success_msg = (
            "Your responses have been recorded. Below is your personalized digital hygiene summary. "
            "Interested in digital wellbeing workshops for your team or school? Contact us!"
            if is_graded
            else "Thank you for sharing your feedback! Your responses have been saved and help us improve our future workshops and webinars."
        )

    frappe.db.sql("DELETE FROM `tabWeb Form` WHERE route = %s AND name != %s", (route, wf_name))

    if frappe.db.exists("Web Form", wf_name):
        wf = frappe.get_doc("Web Form", wf_name)
    else:
        wf = frappe.new_doc("Web Form")
        wf.name = wf_name

    wf.title = title
    wf.route = route
    wf.doc_type = "Survey Response"
    wf.module = "Website"
    wf.is_standard = 0
    wf.published = 1
    wf.anonymous = 1
    wf.login_required = 0
    wf.allow_multiple = 1
    wf.allow_edit = 0
    wf.allow_delete = 0
    wf.allow_incomplete = 0
    wf.apply_document_permissions = 0
    wf.show_list = 0
    wf.hide_navbar = 0
    wf.hide_footer = 0
    wf.button_label = btn_label
    wf.introduction_text = intro
    wf.success_title = success_title
    wf.success_message = success_msg
    wf.success_url = f"/{route}"
    wf.custom_css = CUSTOM_CSS.strip()
    wf.client_script = build_client_script(survey, lang).strip()

    wf.set("web_form_fields", build_web_form_fields(survey, lang))
    wf.save(ignore_permissions=True)
    # Ensure explicit name matches wf_name
    if wf.name != wf_name:
        frappe.rename_doc("Web Form", wf.name, wf_name, force=True)
    return wf_name


def migrate_surveys_and_responses(data: dict):
    for s in data.get("surveys", []):
        slug = s["slug"]
        if frappe.db.exists("Survey", slug):
            survey_doc = frappe.get_doc("Survey", slug)
        else:
            survey_doc = frappe.new_doc("Survey")
            survey_doc.slug = slug

        survey_doc.title_pl = s["title_pl"]
        survey_doc.title_en = s["title_en"]
        survey_doc.scoring_type = s["scoring_type"]
        survey_doc.description_pl = s["description_pl"]
        survey_doc.description_en = s["description_en"]
        survey_doc.odoo_survey_id = s["odoo_survey_id"]
        survey_doc.odoo_access_token = s["access_token"]
        survey_doc.pl_route = f"/surveys/{slug}"
        survey_doc.en_route = f"/en/surveys/{slug}"
        survey_doc.total_responses = len(s.get("responses", []))

        survey_doc.set("questions", [])
        for q in s.get("questions", []):
            survey_doc.append("questions", {
                "question_code": q["question_code"],
                "section_pl": q["section_pl"],
                "section_en": q["section_en"],
                "question_pl": q["question_pl"],
                "question_en": q["question_en"],
                "question_type": q["question_type"],
                "mandatory": q.get("mandatory", 1),
                "options_pl": "\n".join(q.get("options_pl", [])),
                "options_en": "\n".join(q.get("options_en", [])),
                "score_map_json": json.dumps(q.get("score_map", {}), ensure_ascii=False),
                "odoo_question_id": q["odoo_question_id"],
            })

        survey_doc.set("grades", [])
        for g in s.get("grades", []):
            survey_doc.append("grades", {
                "grade_name_pl": g["grade_name_pl"],
                "grade_name_en": g["grade_name_en"],
                "min_score_percentage": g["min_score_percentage"],
                "max_score_percentage": g["max_score_percentage"],
                "description_pl": g["description_pl"],
                "description_en": g["description_en"],
                "odoo_grade_id": g["odoo_grade_id"],
            })

        survey_doc.save(ignore_permissions=True)

        # Create/Update bilingual Web Forms
        wf_pl = upsert_web_form(s, "pl")
        wf_en = upsert_web_form(s, "en")
        survey_doc.db_set("pl_web_form", wf_pl, update_modified=False)
        survey_doc.db_set("en_web_form", wf_en, update_modified=False)

        # Precompute max possible score and bilingual grade lookup for this survey
        max_possible = 0.0
        for q in s.get("questions", []):
            sm = q.get("score_map") or {}
            if sm:
                max_possible += max(float(v) for v in sm.values())

        grade_bilingual_map = {}
        for g in s.get("grades", []):
            g_pl = g.get("grade_name_pl") or ""
            g_en = g.get("grade_name_en") or ""
            bilingual_label = f"{g_pl} / {g_en}" if (g_pl and g_en and g_pl != g_en) else (g_pl or g_en)
            if g_pl:
                grade_bilingual_map[g_pl] = bilingual_label
            if g_en:
                grade_bilingual_map[g_en] = bilingual_label

        # Migrate historical responses
        for r in s.get("responses", []):
            odoo_input_id = r["odoo_input_id"]
            existing_name = frappe.db.get_value("Survey Response", {"odoo_input_id": odoo_input_id}, "name")
            if existing_name:
                sr = frappe.get_doc("Survey Response", existing_name)
            else:
                sr = frappe.new_doc("Survey Response")

            sr.survey = slug
            sr.course_id = (
                "endress-hauser"
                if slug == "digital-hygiene-assessment-endress-hauser"
                else (getattr(sr, "course_id", None) or "general")
            )
            sr.state = r["state"]
            sr.language = "pl"
            sr.submitted_at = (r.get("submitted_at") or "").replace("T", " ")[:19] or None

            raw_grade = r.get("achieved_grade") or ""
            sr.achieved_grade = grade_bilingual_map.get(raw_grade, raw_grade)
            sr.achieved_grade_description = r.get("achieved_grade_description") or ""
            sr.respondent_name = r.get("nickname") or ""
            sr.respondent_email = r.get("email") or ""
            sr.is_test_entry = r.get("is_test_entry", 0)
            sr.odoo_input_id = odoo_input_id
            sr.odoo_access_token = r.get("access_token") or ""

            for q_code, val_pl in (r.get("flat_answers_pl") or {}).items():
                sr.set(q_code, val_pl)

            sr.set("answers", [])
            computed_total = 0.0
            for ans in r.get("answers", []):
                sc = float(ans.get("answer_score") or 0.0)
                computed_total += sc
                sr.append("answers", {
                    "question_code": ans["question_code"],
                    "question_text": ans["question_pl"],
                    "answer_value": ans["answer_value_pl"],
                    "answer_score": sc,
                    "odoo_question_id": ans["odoo_question_id"],
                })

            if r.get("scoring_total") is not None and float(r.get("scoring_total") or 0.0) > 0:
                sr.scoring_total = float(r.get("scoring_total") or 0.0)
                sr.scoring_percentage = float(r.get("scoring_percentage") or 0.0)
            elif max_possible > 0 and computed_total > 0:
                sr.scoring_total = computed_total
                sr.scoring_percentage = round((computed_total / max_possible) * 100.0, 2)
            else:
                sr.scoring_total = 0.0
                sr.scoring_percentage = 0.0

            sr.save(ignore_permissions=True)

        # Update total_responses count
        total_cnt = frappe.db.count("Survey Response", {"survey": slug})
        survey_doc.db_set("total_responses", total_cnt, update_modified=False)

    frappe.db.commit()


def ensure_survey_catalog_pages_and_redirects(data: dict):
    # Create Web Template "Survey Catalog Section"
    wt_name = "Survey Catalog Section"
    wt_html = """
{% set is_en = (lang or '') == 'en' %}
{% set surveys = frappe.get_all('Survey', fields=['name', 'slug', 'title_pl', 'title_en', 'description_pl', 'description_en', 'scoring_type', 'total_responses', 'pl_route', 'en_route'], order_by='odoo_survey_id asc') %}
<section class="py-5" style="background: #f6f9fb;">
  <div class="container">
    <div class="text-center mb-5">
      <span class="badge rounded-pill px-3 py-2 mb-2" style="background:#e3eff6; color:#314559; font-weight:600;">
        {{ 'Testy Samooceny i Ankiety' if not is_en else 'Self-Assessments & Feedback Surveys' }}
      </span>
      <h2 class="fw-bold" style="color:#314559; font-size:2.2rem;">{{ heading or ('Ankiety i Testy Higieny Cyfrowej' if not is_en else 'Digital Hygiene Assessments & Surveys') }}</h2>
      <p class="text-muted mx-auto" style="max-width:700px; font-size:1.08rem;">
        {{ subtitle or ('Sprawdź swój poziom higieny cyfrowej w bezpłatnym teście online lub podziel się opinią po udziale w naszym webinarze bądź warsztacie.' if not is_en else 'Evaluate your digital habits with our interactive self-assessment or share your feedback after attending one of our webinars or workshops.') }}
      </p>
    </div>

    <div class="row g-4">
      {% for s in surveys %}
        {% set title = s.title_en if is_en else s.title_pl %}
        {% set desc = s.description_en if is_en else s.description_pl %}
        {% set url = s.en_route if is_en else s.pl_route %}
        {% set is_assessment = s.scoring_type == 'grading_with_answers' %}
        <div class="col-md-6 col-lg-4">
          <div class="card h-100 border-0 shadow-sm" style="border-radius:16px; overflow:hidden;">
            <div class="card-body p-4 d-flex flex-column">
              <div class="d-flex justify-content-between align-items-center mb-3">
                <span class="badge rounded-pill px-3 py-2" style="background:{{ '#314559' if is_assessment else '#6099b9' }}; color:#fff; font-size:0.78rem;">
                  {{ ('Test Samooceny' if not is_en else 'Self-Assessment') if is_assessment else ('Ankieta Opinii' if not is_en else 'Feedback Survey') }}
                </span>
                <small class="text-muted fw-semibold">
                  {{ s.total_responses }} {{ 'odpowiedzi' if not is_en else 'responses' }}
                </small>
              </div>
              <h3 class="h5 fw-bold mb-3" style="color:#314559;">{{ title }}</h3>
              <div class="text-muted mb-4 flex-grow-1" style="font-size:0.95rem;">
                {{ desc | safe }}
              </div>
              <a href="{{ url }}" class="btn w-100 fw-semibold py-2" style="background:#314559; color:#ffffff; border-radius:999px;">
                {{ ('Rozpocznij test →' if not is_en else 'Start Assessment →') if is_assessment else ('Wypełnij ankietę →' if not is_en else 'Fill Out Survey →') }}
              </a>
            </div>
          </div>
        </div>
      {% endfor %}
    </div>
  </div>
</section>
"""
    if frappe.db.exists("Web Template", wt_name):
        wt = frappe.get_doc("Web Template", wt_name)
    else:
        wt = frappe.new_doc("Web Template")
        wt.name = wt_name
    wt.type = "Section"
    wt.standard = 0
    wt.module = "Website"
    wt.template = wt_html.strip()
    wt.set("fields", [
        {"fieldname": "lang", "label": "Language (pl/en)", "fieldtype": "Data"},
        {"fieldname": "heading", "label": "Heading", "fieldtype": "Data"},
        {"fieldname": "subtitle", "label": "Subtitle", "fieldtype": "Small Text"},
    ])
    wt.save(ignore_permissions=True)

    # Create /surveys (PL) and /en/surveys (EN) Web Pages
    pages = [
        {
            "name": "surveys-pl",
            "title": "Ankiety i Testy Higieny Cyfrowej",
            "route": "surveys",
            "lang": "pl",
            "heading": "Ankiety i Testy Higieny Cyfrowej",
            "subtitle": "Sprawdź swój poziom higieny cyfrowej w bezpłatnym teście online lub podziel się opinią po udziale w naszym webinarze bądź warsztacie.",
        },
        {
            "name": "surveys-en",
            "title": "Digital Hygiene Surveys & Assessments",
            "route": "en/surveys",
            "lang": "en",
            "heading": "Digital Hygiene Surveys & Assessments",
            "subtitle": "Evaluate your digital habits with our interactive self-assessment or share your feedback after attending one of our webinars or workshops.",
        },
    ]
    for p in pages:
        existing_wp = frappe.db.get_value("Web Page", {"route": p["route"]}, "name")
        if existing_wp:
            wp = frappe.get_doc("Web Page", existing_wp)
        else:
            wp = frappe.new_doc("Web Page")
        wp.title = p["title"]
        wp.route = p["route"]
        wp.published = 1
        wp.content_type = "Page Builder"
        wp.full_width = 1
        wp.show_title = 0
        wp.set("page_blocks", [
            {
                "web_template": wt_name,
                "web_template_values": json.dumps({
                    "lang": p["lang"],
                    "heading": p["heading"],
                    "subtitle": p["subtitle"],
                }, ensure_ascii=False),
            }
        ])
        wp.save(ignore_permissions=True)

    # Add legacy Odoo survey token redirects + /ankiety redirects + query-forwarding /new redirects in Website Settings
    ws = frappe.get_single("Website Settings")
    existing_sources = {r.source.strip("/"): r for r in ws.route_redirects}
    redirects_to_add = [
        ("ankiety", "/surveys"),
        ("en/ankiety", "/en/surveys"),
        ("survey/5f1edd02-4201-4045-86aa-440e03582261", "/surveys/digital-hygiene-assessment/new"),
        ("surveys/([^/]+)", r"/surveys/\1/new"),
        ("en/surveys/([^/]+)", r"/en/surveys/\1/new"),
        ("surveys/([^/]+)/course/([^/]+)", r"/surveys/\1/new?course=\2"),
        ("en/surveys/([^/]+)/course/([^/]+)", r"/en/surveys/\1/new?course=\2"),
    ]
    for s in data.get("surveys", []):
        tok = s.get("access_token")
        slug = s.get("slug")
        if tok and slug:
            redirects_to_add.append((f"survey/start/{tok}", f"/surveys/{slug}/new"))

    for src, target in redirects_to_add:
        if src in existing_sources:
            existing_sources[src].target = target
            existing_sources[src].forward_query_parameters = 1
        else:
            ws.append("route_redirects", {
                "source": src,
                "target": target,
                "redirect_http_status": "301",
                "forward_query_parameters": 1,
            })

    # Add "Ankiety" -> "/surveys" under "Wiedza" in top_bar_items if not present
    has_surveys_nav = any((item.url or "").strip() == "/surveys" for item in ws.top_bar_items)
    if not has_surveys_nav:
        ws.append("top_bar_items", {
            "label": "Ankiety",
            "parent_label": "Wiedza",
            "url": "/surveys",
            "right": 0,
        })
    ws.save(ignore_permissions=True)

    # Ensure English Translation record for "Ankiety" -> "Surveys"
    if not frappe.db.exists("Translation", {"language": "en", "source_text": "Ankiety"}):
        tr = frappe.new_doc("Translation")
        tr.language = "en"
        tr.source_text = "Ankiety"
        tr.translated_text = "Surveys"
        tr.insert(ignore_permissions=True)

    frappe.db.commit()


def ensure_survey_analytics_dashboard_and_workspace():
    # 1. Native Script Reports with Survey & Course / Event ID (course_id) filters and built-in charts
    r1_name = "Survey Question Breakdown"
    r1 = frappe.get_doc("Report", r1_name) if frappe.db.exists("Report", r1_name) else frappe.new_doc("Report")
    r1.report_name = r1_name
    r1.ref_doctype = "Survey Response"
    r1.is_standard = "No"
    r1.module = "Website"
    r1.report_type = "Script Report"
    r1.disabled = 0
    r1.query = ""
    r1.set("filters", [
        {"fieldname": "survey", "label": "Survey", "fieldtype": "Link", "options": "Survey", "mandatory": 0},
        {"fieldname": "course_id", "label": "Course / Event ID", "fieldtype": "Data", "mandatory": 0},
    ])
    r1.report_script = """
conditions = ["sqi.question_type != 'text_box'"]
values = {}
if filters and filters.get("survey"):
    conditions.append("sr.survey = %(survey)s")
    values["survey"] = filters.get("survey")
if filters and filters.get("course_id"):
    conditions.append("sr.course_id = %(course_id)s")
    values["course_id"] = filters.get("course_id")

where_clause = "WHERE " + " AND ".join(conditions)

rows = frappe.db.sql(f'''
    SELECT
        sr.survey AS survey,
        sra.question_code AS question_code,
        CONCAT(sra.question_code, " - ", LEFT(COALESCE(sqi.question_pl, sra.question_text), 42)) AS question_label,
        COALESCE(sqi.question_pl, sra.question_text) AS full_question_pl,
        COALESCE(sqi.question_en, sra.question_text) AS full_question_en,
        COUNT(sra.name) AS responses,
        ROUND(AVG(sra.answer_score), 2) AS avg_score,
        ROUND(SUM(sra.answer_score), 1) AS total_points
    FROM `tabSurvey Response Answer` sra
    INNER JOIN `tabSurvey Response` sr ON sr.name = sra.parent
    LEFT JOIN `tabSurvey Question Item` sqi ON sqi.parent = sr.survey AND sqi.question_code = sra.question_code
    {where_clause}
    GROUP BY sr.survey, sra.question_code
    ORDER BY sr.survey ASC, sra.question_code ASC
''', values, as_dict=True)

columns = [
    {"fieldname": "survey", "label": "Survey", "fieldtype": "Link", "options": "Survey", "width": 190},
    {"fieldname": "question_code", "label": "Code", "fieldtype": "Data", "width": 70},
    {"fieldname": "question_label", "label": "Question Label", "fieldtype": "Data", "width": 250},
    {"fieldname": "full_question_pl", "label": "Question (PL)", "fieldtype": "Data", "width": 320},
    {"fieldname": "full_question_en", "label": "Question (EN)", "fieldtype": "Data", "width": 320},
    {"fieldname": "responses", "label": "Responses", "fieldtype": "Int", "width": 95},
    {"fieldname": "avg_score", "label": "Avg Score (pts)", "fieldtype": "Float", "width": 130},
    {"fieldname": "total_points", "label": "Total Points", "fieldtype": "Float", "width": 110},
]

chart = {
    "data": {
        "labels": [r["question_label"] for r in rows],
        "datasets": [
            {"name": "Avg Score (pts)", "values": [r["avg_score"] for r in rows]}
        ]
    },
    "type": "bar",
    "colors": ["#21409a"]
}

data = columns, rows, None, chart, None
""".strip()
    r1.roles = []
    for role in ["System Manager", "Website Manager"]:
        r1.append("roles", {"role": role})
    r1.save(ignore_permissions=True)

    r2_name = "Survey Answer Distribution"
    r2 = frappe.get_doc("Report", r2_name) if frappe.db.exists("Report", r2_name) else frappe.new_doc("Report")
    r2.report_name = r2_name
    r2.ref_doctype = "Survey Response"
    r2.is_standard = "No"
    r2.module = "Website"
    r2.report_type = "Script Report"
    r2.disabled = 0
    r2.query = ""
    r2.set("filters", [
        {"fieldname": "survey", "label": "Survey", "fieldtype": "Link", "options": "Survey", "mandatory": 0},
        {"fieldname": "course_id", "label": "Course / Event ID", "fieldtype": "Data", "mandatory": 0},
        {"fieldname": "question_code", "label": "Question Code (e.g. q_01)", "fieldtype": "Data", "mandatory": 0},
    ])
    r2.report_script = """
conditions = ["sqi.question_type != 'text_box'"]
values = {}
if filters and filters.get("survey"):
    conditions.append("sr.survey = %(survey)s")
    values["survey"] = filters.get("survey")
if filters and filters.get("course_id"):
    conditions.append("sr.course_id = %(course_id)s")
    values["course_id"] = filters.get("course_id")
if filters and filters.get("question_code"):
    conditions.append("sra.question_code = %(question_code)s")
    values["question_code"] = filters.get("question_code")

where_clause = "WHERE " + " AND ".join(conditions)

rows = frappe.db.sql(f'''
    SELECT
        sr.survey AS survey,
        sra.question_code AS question_code,
        COALESCE(sqi.question_pl, sra.question_text) AS question_pl,
        sra.answer_value AS answer_value,
        CONCAT(sra.question_code, ": ", LEFT(sra.answer_value, 28)) AS option_label,
        COUNT(sra.name) AS count,
        ROUND(AVG(sra.answer_score), 2) AS points
    FROM `tabSurvey Response Answer` sra
    INNER JOIN `tabSurvey Response` sr ON sr.name = sra.parent
    LEFT JOIN `tabSurvey Question Item` sqi ON sqi.parent = sr.survey AND sqi.question_code = sra.question_code
    {where_clause}
    GROUP BY sr.survey, sra.question_code, sra.answer_value
    ORDER BY sr.survey ASC, sra.question_code ASC, COUNT(sra.name) DESC
''', values, as_dict=True)

columns = [
    {"fieldname": "survey", "label": "Survey", "fieldtype": "Link", "options": "Survey", "width": 190},
    {"fieldname": "question_code", "label": "Code", "fieldtype": "Data", "width": 70},
    {"fieldname": "question_pl", "label": "Question (PL)", "fieldtype": "Data", "width": 320},
    {"fieldname": "answer_value", "label": "Answer / Option", "fieldtype": "Data", "width": 240},
    {"fieldname": "count", "label": "Count", "fieldtype": "Int", "width": 95},
    {"fieldname": "points", "label": "Points", "fieldtype": "Float", "width": 90},
]

chart = {
    "data": {
        "labels": [r["option_label"] for r in rows[:30]],
        "datasets": [
            {"name": "Responses", "values": [r["count"] for r in rows[:30]]}
        ]
    },
    "type": "bar",
    "colors": ["#3b82f6"]
}

data = columns, rows, None, chart, None
""".strip()
    r2.roles = []
    for role in ["System Manager", "Website Manager"]:
        r2.append("roles", {"role": role})
    r2.save(ignore_permissions=True)

    r3_name = "Survey Open Text Answers"
    r3 = frappe.get_doc("Report", r3_name) if frappe.db.exists("Report", r3_name) else frappe.new_doc("Report")
    r3.report_name = r3_name
    r3.ref_doctype = "Survey Response"
    r3.is_standard = "No"
    r3.module = "Website"
    r3.report_type = "Script Report"
    r3.disabled = 0
    r3.query = ""
    r3.set("filters", [
        {"fieldname": "survey", "label": "Survey", "fieldtype": "Link", "options": "Survey", "mandatory": 0},
        {"fieldname": "course_id", "label": "Course / Event ID", "fieldtype": "Data", "mandatory": 0},
    ])
    r3.report_script = """
conditions = ["sqi.question_type = 'text_box'", "IFNULL(sra.answer_value, '') != ''"]
values = {}
if filters and filters.get("survey"):
    conditions.append("sr.survey = %(survey)s")
    values["survey"] = filters.get("survey")
if filters and filters.get("course_id"):
    conditions.append("sr.course_id = %(course_id)s")
    values["course_id"] = filters.get("course_id")

where_clause = "WHERE " + " AND ".join(conditions)

rows = frappe.db.sql(f'''
    SELECT
        sr.name AS response_id,
        sr.survey AS survey,
        sr.course_id AS course_id,
        sr.submitted_at AS submitted_at,
        sra.question_code AS question_code,
        COALESCE(sqi.question_pl, sra.question_text) AS question_text,
        sra.answer_value AS answer_value
    FROM `tabSurvey Response Answer` sra
    INNER JOIN `tabSurvey Response` sr ON sr.name = sra.parent
    INNER JOIN `tabSurvey Question Item` sqi ON sqi.parent = sr.survey AND sqi.question_code = sra.question_code
    {where_clause}
    ORDER BY sr.submitted_at DESC, sr.name DESC, sra.question_code ASC
''', values, as_dict=True)

columns = [
    {"fieldname": "response_id", "label": "Response", "fieldtype": "Link", "options": "Survey Response", "width": 160},
    {"fieldname": "survey", "label": "Survey", "fieldtype": "Link", "options": "Survey", "width": 190},
    {"fieldname": "course_id", "label": "Course / Event ID", "fieldtype": "Data", "width": 140},
    {"fieldname": "submitted_at", "label": "Submitted At", "fieldtype": "Datetime", "width": 155},
    {"fieldname": "question_code", "label": "Code", "fieldtype": "Data", "width": 70},
    {"fieldname": "question_text", "label": "Question", "fieldtype": "Data", "width": 300},
    {"fieldname": "answer_value", "label": "Open-Ended Answer / Feedback", "fieldtype": "Data", "width": 440},
]

data = columns, rows, None, None, None
""".strip()
    r3.roles = []
    for role in ["System Manager", "Website Manager"]:
        r3.append("roles", {"role": role})
    r3.save(ignore_permissions=True)

    # Helper to upsert a Number Card (Number Card autoname sets name = label on insert)
    def upsert_number_card(spec: dict):
        nc = frappe.get_doc("Number Card", spec["name"]) if frappe.db.exists("Number Card", spec["name"]) else frappe.new_doc("Number Card")
        nc.label = spec["name"]
        nc.type = "Document Type"
        nc.document_type = "Survey Response"
        nc.function = spec["function"]
        nc.aggregate_function_based_on = spec.get("aggregate_function_based_on")
        nc.filters_json = spec["filters_json"]
        nc.is_public = 1
        nc.is_standard = 0
        nc.module = "Website"
        nc.color = spec["color"]
        nc.show_percentage_stats = 1
        nc.stats_time_interval = "Monthly"
        nc.save(ignore_permissions=True)

    # Helper to upsert a Dashboard Chart
    def upsert_dashboard_chart(spec: dict):
        dc = frappe.get_doc("Dashboard Chart", spec["name"]) if frappe.db.exists("Dashboard Chart", spec["name"]) else frappe.new_doc("Dashboard Chart")
        dc.chart_name = spec["name"]
        dc.chart_type = spec["chart_type"]
        dc.document_type = spec.get("document_type")
        dc.group_by_type = spec.get("group_by_type")
        dc.group_by_based_on = spec.get("group_by_based_on")
        dc.aggregate_function_based_on = spec.get("aggregate_function_based_on")
        dc.based_on = spec.get("based_on")
        dc.timeseries = spec.get("timeseries", 0)
        dc.timespan = spec.get("timespan")
        dc.time_interval = spec.get("time_interval")
        dc.report_name = spec.get("report_name")
        dc.use_report_chart = spec.get("use_report_chart", 0)
        dc.x_field = spec.get("x_field")
        dc.type = spec["type"]
        dc.filters_json = spec["filters_json"]
        dc.color = spec.get("color")
        dc.is_public = 1
        dc.is_standard = 0
        dc.module = "Website"
        dc.show_values_over_chart = 1
        dc.y_axis = []
        for y in spec.get("y_axis", []):
            dc.append("y_axis", y)
        dc.save(ignore_permissions=True)

    # Helper to upsert a Dashboard
    def upsert_dashboard(dash_name: str, card_names: list[str], chart_specs: list[dict]):
        dash = frappe.get_doc("Dashboard", dash_name) if frappe.db.exists("Dashboard", dash_name) else frappe.new_doc("Dashboard")
        dash.dashboard_name = dash_name
        dash.module = "Website"
        dash.is_standard = 0
        dash.is_default = 0
        dash.cards = []
        for cname in card_names:
            dash.append("cards", {"card": cname})
        dash.charts = []
        for cspec in chart_specs:
            dash.append("charts", {"chart": cspec["name"], "width": cspec.get("width", "Half")})
        dash.save(ignore_permissions=True)

    at_risk_grades = [
        "W grupie ryzyka / At Risk",
        "Niezdrowy / Unhealthy",
        "Zagrożenie uzależnieniem / Addiction Risk",
        "W grupie ryzyka",
        "At Risk",
        "Niezdrowy",
        "Unhealthy",
        "Zagrożenie uzależnieniem",
        "Addiction Risk",
    ]
    healthy_grades = [
        "Zrównoważony / Balanced",
        "Pod kontrolą / Controlled",
        "Zrównoważony",
        "Balanced",
        "Pod kontrolą",
        "Controlled",
    ]

    # 2. Cross-Survey Overview Dashboard ("Survey Analytics")
    overview_cards = [
        {
            "name": "Total Survey Responses",
            "label": "Total Survey Responses",
            "function": "Count",
            "filters_json": "[]",
            "color": "#21409a",
        },
        {
            "name": "Digital Hygiene Assessments",
            "label": "Digital Hygiene Assessments",
            "function": "Count",
            "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment"]]),
            "color": "#3b82f6",
        },
        {
            "name": "Average Hygiene Score (%)",
            "label": "Average Hygiene Score (%)",
            "function": "Average",
            "aggregate_function_based_on": "scoring_percentage",
            "filters_json": json.dumps([["Survey Response", "survey", "in", ["digital-hygiene-assessment", "digital-hygiene-assessment-endress-hauser"]]]),
            "color": "#10b981",
        },
        {
            "name": "Respondents At Risk",
            "label": "Respondents At Risk",
            "function": "Count",
            "filters_json": json.dumps([["Survey Response", "achieved_grade", "in", at_risk_grades]]),
            "color": "#ef4444",
        },
        {
            "name": "Satisfaction Survey Responses",
            "label": "Satisfaction Survey Responses",
            "function": "Count",
            "filters_json": json.dumps([["Survey Response", "survey", "in", ["workshop-satisfaction-survey", "webinar-satisfaction-survey", "training-satisfaction-survey"]]]),
            "color": "#8b5cf6",
        },
    ]
    for c in overview_cards:
        upsert_number_card(c)

    overview_charts = [
        {
            "name": "Survey Responses by Survey",
            "chart_type": "Group By",
            "document_type": "Survey Response",
            "group_by_type": "Count",
            "group_by_based_on": "survey",
            "type": "Bar",
            "filters_json": "[]",
            "color": "#21409a",
            "width": "Half",
        },
        {
            "name": "Digital Hygiene Grade Distribution",
            "chart_type": "Group By",
            "document_type": "Survey Response",
            "group_by_type": "Count",
            "group_by_based_on": "achieved_grade",
            "type": "Donut",
            "filters_json": json.dumps([["Survey Response", "achieved_grade", "is", "set"]]),
            "color": "#10b981",
            "width": "Half",
        },
        {
            "name": "Average Score (%) by Survey",
            "chart_type": "Group By",
            "document_type": "Survey Response",
            "group_by_type": "Average",
            "group_by_based_on": "survey",
            "aggregate_function_based_on": "scoring_percentage",
            "type": "Bar",
            "filters_json": json.dumps([["Survey Response", "scoring_percentage", ">", 0]]),
            "color": "#3b82f6",
            "width": "Half",
        },
        {
            "name": "Survey Submissions Over Time",
            "chart_type": "Count",
            "document_type": "Survey Response",
            "based_on": "submitted_at",
            "timeseries": 1,
            "timespan": "Last Year",
            "time_interval": "Monthly",
            "type": "Line",
            "filters_json": "[]",
            "color": "#8b5cf6",
            "width": "Half",
        },
        {
            "name": "Survey Question Average Scores",
            "chart_type": "Report",
            "report_name": "Survey Question Breakdown",
            "use_report_chart": 1,
            "type": "Bar",
            "filters_json": json.dumps({"survey": "digital-hygiene-assessment"}),
            "width": "Full",
        },
    ]
    for ch in overview_charts:
        upsert_dashboard_chart(ch)
    upsert_dashboard("Survey Analytics", [c["name"] for c in overview_cards], overview_charts)

    # 3. Six Dedicated Per-Survey Dashboards (1 per Survey)
    per_survey_dashboards = [
        # 3.1 Digital Hygiene Assessment
        {
            "dashboard_name": "Survey: Digital Hygiene Assessment",
            "slug": "digital-hygiene-assessment",
            "cards": [
                {
                    "name": "DHA: Total Responses",
                    "label": "Total Responses",
                    "function": "Count",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment"]]),
                    "color": "#21409a",
                },
                {
                    "name": "DHA: Average Score (%)",
                    "label": "Average Hygiene Score (%)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_percentage",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment"]]),
                    "color": "#10b981",
                },
                {
                    "name": "DHA: Balanced / Controlled",
                    "label": "Balanced / Controlled",
                    "function": "Count",
                    "filters_json": json.dumps([
                        ["Survey Response", "survey", "=", "digital-hygiene-assessment"],
                        ["Survey Response", "achieved_grade", "in", healthy_grades],
                    ]),
                    "color": "#3b82f6",
                },
                {
                    "name": "DHA: At Risk / Unhealthy",
                    "label": "At Risk / Unhealthy",
                    "function": "Count",
                    "filters_json": json.dumps([
                        ["Survey Response", "survey", "=", "digital-hygiene-assessment"],
                        ["Survey Response", "achieved_grade", "in", at_risk_grades],
                    ]),
                    "color": "#ef4444",
                },
            ],
            "charts": [
                {
                    "name": "DHA: Grade Distribution",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "achieved_grade",
                    "type": "Donut",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment"]]),
                    "color": "#10b981",
                    "width": "Half",
                },
                {
                    "name": "DHA: Responses by Course / Cohort",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "course_id",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment"]]),
                    "color": "#3b82f6",
                    "width": "Half",
                },
                {
                    "name": "DHA: Question Average Scores (Q1-Q20)",
                    "chart_type": "Report",
                    "report_name": "Survey Question Breakdown",
                    "use_report_chart": 1,
                    "type": "Bar",
                    "filters_json": json.dumps({"survey": "digital-hygiene-assessment"}),
                    "width": "Full",
                },
                {
                    "name": "DHA: Submissions Over Time",
                    "chart_type": "Count",
                    "document_type": "Survey Response",
                    "based_on": "submitted_at",
                    "timeseries": 1,
                    "timespan": "Last Year",
                    "time_interval": "Monthly",
                    "type": "Line",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment"]]),
                    "color": "#8b5cf6",
                    "width": "Half",
                },
                {
                    "name": "DHA: Avg Score (%) by Course / Cohort",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Average",
                    "group_by_based_on": "course_id",
                    "aggregate_function_based_on": "scoring_percentage",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment"]]),
                    "color": "#21409a",
                    "width": "Half",
                },
            ],
        },
        # 3.2 Digital Hygiene (Endress+Hauser)
        {
            "dashboard_name": "Survey: Digital Hygiene (Endress+Hauser)",
            "slug": "digital-hygiene-assessment-endress-hauser",
            "cards": [
                {
                    "name": "E+H: Total Responses",
                    "label": "Total Responses (E+H)",
                    "function": "Count",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment-endress-hauser"]]),
                    "color": "#21409a",
                },
                {
                    "name": "E+H: Average Score (%)",
                    "label": "Average Hygiene Score (%)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_percentage",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment-endress-hauser"]]),
                    "color": "#10b981",
                },
                {
                    "name": "E+H: Balanced / Controlled",
                    "label": "Balanced / Controlled",
                    "function": "Count",
                    "filters_json": json.dumps([
                        ["Survey Response", "survey", "=", "digital-hygiene-assessment-endress-hauser"],
                        ["Survey Response", "achieved_grade", "in", healthy_grades],
                    ]),
                    "color": "#3b82f6",
                },
                {
                    "name": "E+H: At Risk / Unhealthy",
                    "label": "At Risk / Unhealthy",
                    "function": "Count",
                    "filters_json": json.dumps([
                        ["Survey Response", "survey", "=", "digital-hygiene-assessment-endress-hauser"],
                        ["Survey Response", "achieved_grade", "in", at_risk_grades],
                    ]),
                    "color": "#ef4444",
                },
            ],
            "charts": [
                {
                    "name": "E+H: Grade Distribution",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "achieved_grade",
                    "type": "Donut",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment-endress-hauser"]]),
                    "color": "#10b981",
                    "width": "Half",
                },
                {
                    "name": "E+H: Responses by Course / Cohort",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "course_id",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment-endress-hauser"]]),
                    "color": "#3b82f6",
                    "width": "Half",
                },
                {
                    "name": "E+H: Question Average Scores (Q1-Q20)",
                    "chart_type": "Report",
                    "report_name": "Survey Question Breakdown",
                    "use_report_chart": 1,
                    "type": "Bar",
                    "filters_json": json.dumps({"survey": "digital-hygiene-assessment-endress-hauser"}),
                    "width": "Full",
                },
                {
                    "name": "E+H: Submissions Over Time",
                    "chart_type": "Count",
                    "document_type": "Survey Response",
                    "based_on": "submitted_at",
                    "timeseries": 1,
                    "timespan": "Last Year",
                    "time_interval": "Monthly",
                    "type": "Line",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-hygiene-assessment-endress-hauser"]]),
                    "color": "#8b5cf6",
                    "width": "Full",
                },
            ],
        },
        # 3.3 Digital Risk Assessment (Archive)
        {
            "dashboard_name": "Survey: Digital Risk Assessment (Archive)",
            "slug": "digital-risk-assessment-archive",
            "cards": [
                {
                    "name": "DRA: Total Responses",
                    "label": "Total Responses",
                    "function": "Count",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-risk-assessment-archive"]]),
                    "color": "#21409a",
                },
                {
                    "name": "DRA: Average Score (%)",
                    "label": "Average Risk Score (%)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_percentage",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-risk-assessment-archive"]]),
                    "color": "#f59e0b",
                },
                {
                    "name": "DRA: Addiction Risk Count",
                    "label": "Addiction Risk Respondents",
                    "function": "Count",
                    "filters_json": json.dumps([
                        ["Survey Response", "survey", "=", "digital-risk-assessment-archive"],
                        ["Survey Response", "achieved_grade", "in", at_risk_grades],
                    ]),
                    "color": "#ef4444",
                },
            ],
            "charts": [
                {
                    "name": "DRA: Grade Distribution",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "achieved_grade",
                    "type": "Donut",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-risk-assessment-archive"]]),
                    "color": "#ef4444",
                    "width": "Half",
                },
                {
                    "name": "DRA: Responses by Course / Cohort",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "course_id",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "digital-risk-assessment-archive"]]),
                    "color": "#3b82f6",
                    "width": "Half",
                },
                {
                    "name": "DRA: Question Average Scores (Q1-Q12)",
                    "chart_type": "Report",
                    "report_name": "Survey Question Breakdown",
                    "use_report_chart": 1,
                    "type": "Bar",
                    "filters_json": json.dumps({"survey": "digital-risk-assessment-archive"}),
                    "width": "Full",
                },
            ],
        },
        # 3.4 Workshop Satisfaction Survey
        {
            "dashboard_name": "Survey: Workshop Satisfaction",
            "slug": "workshop-satisfaction-survey",
            "cards": [
                {
                    "name": "Workshop: Total Responses",
                    "label": "Workshop Responses",
                    "function": "Count",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#21409a",
                },
                {
                    "name": "Workshop: Overall Satisfaction (%)",
                    "label": "Avg Satisfaction Score (%)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_percentage",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#10b981",
                },
                {
                    "name": "Workshop: Avg Total Points (max 25)",
                    "label": "Avg Total Points (out of 25)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_total",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#3b82f6",
                },
                {
                    "name": "Workshop: Top Recommendation (5/5)",
                    "label": "Top Recommendation (5/5 on Q6)",
                    "function": "Count",
                    "filters_json": json.dumps([
                        ["Survey Response", "survey", "=", "workshop-satisfaction-survey"],
                        ["Survey Response", "q_06", "like", "5%"],
                    ]),
                    "color": "#8b5cf6",
                },
            ],
            "charts": [
                {
                    "name": "Workshop: Responses by Course ID",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "course_id",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#21409a",
                    "width": "Half",
                },
                {
                    "name": "Workshop: Avg Satisfaction (%) by Course ID",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Average",
                    "group_by_based_on": "course_id",
                    "aggregate_function_based_on": "scoring_percentage",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#10b981",
                    "width": "Half",
                },
                {
                    "name": "Workshop: Question Average Scores (1-5)",
                    "chart_type": "Report",
                    "report_name": "Survey Question Breakdown",
                    "use_report_chart": 1,
                    "type": "Bar",
                    "filters_json": json.dumps({"survey": "workshop-satisfaction-survey"}),
                    "width": "Full",
                },
                {
                    "name": "Workshop Q1: Expectations Met (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_01",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#3b82f6",
                    "width": "Half",
                },
                {
                    "name": "Workshop Q2: Knowledge Useful (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_02",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#6099b9",
                    "width": "Half",
                },
                {
                    "name": "Workshop Q3: Materials Helpful (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_03",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#10b981",
                    "width": "Half",
                },
                {
                    "name": "Workshop Q4: Questions Answered (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_04",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#8b5cf6",
                    "width": "Half",
                },
                {
                    "name": "Workshop Q6: Would Recommend (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_06",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#f59e0b",
                    "width": "Half",
                },
                {
                    "name": "Workshop: Submissions Over Time",
                    "chart_type": "Count",
                    "document_type": "Survey Response",
                    "based_on": "submitted_at",
                    "timeseries": 1,
                    "timespan": "Last Year",
                    "time_interval": "Monthly",
                    "type": "Line",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "workshop-satisfaction-survey"]]),
                    "color": "#21409a",
                    "width": "Half",
                },
            ],
        },
        # 3.5 Training Satisfaction Survey
        {
            "dashboard_name": "Survey: Training Satisfaction",
            "slug": "training-satisfaction-survey",
            "cards": [
                {
                    "name": "Training: Total Responses",
                    "label": "Training Responses",
                    "function": "Count",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#21409a",
                },
                {
                    "name": "Training: Overall Satisfaction (%)",
                    "label": "Avg Satisfaction Score (%)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_percentage",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#10b981",
                },
                {
                    "name": "Training: Avg Total Points (max 50)",
                    "label": "Avg Total Points (out of 50)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_total",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#3b82f6",
                },
                {
                    "name": "Training: Promoters (9-10 on Q5)",
                    "label": "Promoters (9-10 on Q5)",
                    "function": "Count",
                    "filters_json": json.dumps([
                        ["Survey Response", "survey", "=", "training-satisfaction-survey"],
                        ["Survey Response", "q_05", "in", ["9", "10"]],
                    ]),
                    "color": "#8b5cf6",
                },
            ],
            "charts": [
                {
                    "name": "Training: Responses by Course ID",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "course_id",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#21409a",
                    "width": "Half",
                },
                {
                    "name": "Training: Avg Satisfaction (%) by Course ID",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Average",
                    "group_by_based_on": "course_id",
                    "aggregate_function_based_on": "scoring_percentage",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#10b981",
                    "width": "Half",
                },
                {
                    "name": "Training: Question Average Scores (0-10)",
                    "chart_type": "Report",
                    "report_name": "Survey Question Breakdown",
                    "use_report_chart": 1,
                    "type": "Bar",
                    "filters_json": json.dumps({"survey": "training-satisfaction-survey"}),
                    "width": "Full",
                },
                {
                    "name": "Training Q1: Overall Rating (0-10)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_01",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#3b82f6",
                    "width": "Half",
                },
                {
                    "name": "Training Q2: Practical Usefulness (0-10)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_02",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#6099b9",
                    "width": "Half",
                },
                {
                    "name": "Training Q3: Group Engagement (0-10)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_03",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#10b981",
                    "width": "Half",
                },
                {
                    "name": "Training Q4: Instructor Attitude (0-10)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_04",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#8b5cf6",
                    "width": "Half",
                },
                {
                    "name": "Training Q5: Would Recommend (0-10)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_05",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#f59e0b",
                    "width": "Half",
                },
                {
                    "name": "Training: Submissions Over Time",
                    "chart_type": "Count",
                    "document_type": "Survey Response",
                    "based_on": "submitted_at",
                    "timeseries": 1,
                    "timespan": "Last Year",
                    "time_interval": "Monthly",
                    "type": "Line",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "training-satisfaction-survey"]]),
                    "color": "#21409a",
                    "width": "Half",
                },
            ],
        },
        # 3.6 Webinar Satisfaction Survey
        {
            "dashboard_name": "Survey: Webinar Satisfaction",
            "slug": "webinar-satisfaction-survey",
            "cards": [
                {
                    "name": "Webinar: Total Responses",
                    "label": "Webinar Responses",
                    "function": "Count",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#21409a",
                },
                {
                    "name": "Webinar: Overall Satisfaction (%)",
                    "label": "Avg Satisfaction Score (%)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_percentage",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#10b981",
                },
                {
                    "name": "Webinar: Avg Total Points (max 25)",
                    "label": "Avg Total Points (out of 25)",
                    "function": "Average",
                    "aggregate_function_based_on": "scoring_total",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#3b82f6",
                },
                {
                    "name": "Webinar: Top Recommendation (5/5)",
                    "label": "Top Recommendation (5/5 on Q6)",
                    "function": "Count",
                    "filters_json": json.dumps([
                        ["Survey Response", "survey", "=", "webinar-satisfaction-survey"],
                        ["Survey Response", "q_06", "like", "5%"],
                    ]),
                    "color": "#8b5cf6",
                },
            ],
            "charts": [
                {
                    "name": "Webinar: Responses by Course ID",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "course_id",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#21409a",
                    "width": "Half",
                },
                {
                    "name": "Webinar: Avg Satisfaction (%) by Course ID",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Average",
                    "group_by_based_on": "course_id",
                    "aggregate_function_based_on": "scoring_percentage",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#10b981",
                    "width": "Half",
                },
                {
                    "name": "Webinar: Question Average Scores (1-5)",
                    "chart_type": "Report",
                    "report_name": "Survey Question Breakdown",
                    "use_report_chart": 1,
                    "type": "Bar",
                    "filters_json": json.dumps({"survey": "webinar-satisfaction-survey"}),
                    "width": "Full",
                },
                {
                    "name": "Webinar Q1: Expectations Met (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_01",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#3b82f6",
                    "width": "Half",
                },
                {
                    "name": "Webinar Q2: Knowledge Useful (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_02",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#6099b9",
                    "width": "Half",
                },
                {
                    "name": "Webinar Q3: Materials Helpful (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_03",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#10b981",
                    "width": "Half",
                },
                {
                    "name": "Webinar Q4: Questions Answered (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_04",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#8b5cf6",
                    "width": "Half",
                },
                {
                    "name": "Webinar Q6: Would Recommend (1-5)",
                    "chart_type": "Group By",
                    "document_type": "Survey Response",
                    "group_by_type": "Count",
                    "group_by_based_on": "q_06",
                    "type": "Bar",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#f59e0b",
                    "width": "Half",
                },
                {
                    "name": "Webinar: Submissions Over Time",
                    "chart_type": "Count",
                    "document_type": "Survey Response",
                    "based_on": "submitted_at",
                    "timeseries": 1,
                    "timespan": "Last Year",
                    "time_interval": "Monthly",
                    "type": "Line",
                    "filters_json": json.dumps([["Survey Response", "survey", "=", "webinar-satisfaction-survey"]]),
                    "color": "#21409a",
                    "width": "Half",
                },
            ],
        },
    ]

    for ps in per_survey_dashboards:
        for c in ps["cards"]:
            upsert_number_card(c)
        for ch in ps["charts"]:
            upsert_dashboard_chart(ch)
        upsert_dashboard(ps["dashboard_name"], [c["name"] for c in ps["cards"]], ps["charts"])

    # 4. Native Workspace: Surveys (/app/surveys) with links to all 6 per-survey Dashboards + Overview + Reports
    ws_name = "Surveys"
    ws = frappe.get_doc("Workspace", ws_name) if frappe.db.exists("Workspace", ws_name) else frappe.new_doc("Workspace")
    ws.name = ws_name
    ws.title = "Surveys"
    ws.label = "Surveys"
    ws.module = "Website"
    ws.public = 1
    ws.is_hidden = 0
    ws.icon = "check-square"
    ws.shortcuts = []
    shortcuts_spec = [
        {"label": "Overview: All Surveys Dashboard", "type": "Dashboard", "link_to": "Survey Analytics", "color": "Blue"},
        {"label": "Digital Hygiene Assessment", "type": "Dashboard", "link_to": "Survey: Digital Hygiene Assessment", "color": "Blue"},
        {"label": "Digital Hygiene (Endress+Hauser)", "type": "Dashboard", "link_to": "Survey: Digital Hygiene (Endress+Hauser)", "color": "Blue"},
        {"label": "Digital Risk Assessment (Archive)", "type": "Dashboard", "link_to": "Survey: Digital Risk Assessment (Archive)", "color": "Orange"},
        {"label": "Workshop Satisfaction Dashboard", "type": "Dashboard", "link_to": "Survey: Workshop Satisfaction", "color": "Green"},
        {"label": "Training Satisfaction Dashboard", "type": "Dashboard", "link_to": "Survey: Training Satisfaction", "color": "Green"},
        {"label": "Webinar Satisfaction Dashboard", "type": "Dashboard", "link_to": "Survey: Webinar Satisfaction", "color": "Green"},
        {"label": "Survey Responses", "type": "DocType", "link_to": "Survey Response", "doc_view": "List", "color": "Grey"},
        {"label": "Surveys", "type": "DocType", "link_to": "Survey", "doc_view": "List", "color": "Grey"},
        {"label": "Question Breakdown Report", "type": "Report", "link_to": "Survey Question Breakdown", "is_query_report": 1, "color": "Purple"},
        {"label": "Answer Distribution Report", "type": "Report", "link_to": "Survey Answer Distribution", "is_query_report": 1, "color": "Purple"},
        {"label": "Open Text Answers Report", "type": "Report", "link_to": "Survey Open Text Answers", "is_query_report": 1, "color": "Purple"},
    ]
    for sc in shortcuts_spec:
        ws.append("shortcuts", sc)
    ws.number_cards = []
    for spec in overview_cards:
        ws.append("number_cards", {"number_card_name": spec["name"], "label": spec["name"]})
    ws.charts = []
    for spec in overview_charts:
        ws.append("charts", {"chart_name": spec["name"], "label": spec["name"]})
    ws.content = json.dumps([
        {"id": "hdr_per_survey", "type": "header", "data": {"text": "<span class=\"h4\"><b>Per-Survey Deep-Dive Dashboards</b></span>", "col": 12}},
        {"id": "sc_dh_1", "type": "shortcut", "data": {"shortcut_name": "Digital Hygiene Assessment", "col": 4}},
        {"id": "sc_dh_2", "type": "shortcut", "data": {"shortcut_name": "Digital Hygiene (Endress+Hauser)", "col": 4}},
        {"id": "sc_dh_3", "type": "shortcut", "data": {"shortcut_name": "Digital Risk Assessment (Archive)", "col": 4}},
        {"id": "sc_sat_1", "type": "shortcut", "data": {"shortcut_name": "Workshop Satisfaction Dashboard", "col": 4}},
        {"id": "sc_sat_2", "type": "shortcut", "data": {"shortcut_name": "Training Satisfaction Dashboard", "col": 4}},
        {"id": "sc_sat_3", "type": "shortcut", "data": {"shortcut_name": "Webinar Satisfaction Dashboard", "col": 4}},
        {"id": "hdr_shortcuts", "type": "header", "data": {"text": "<span class=\"h4\"><b>Records & Filterable Reports (by Survey & Course ID)</b></span>", "col": 12}},
        {"id": "sc_ov", "type": "shortcut", "data": {"shortcut_name": "Overview: All Surveys Dashboard", "col": 4}},
        {"id": "sc_resp", "type": "shortcut", "data": {"shortcut_name": "Survey Responses", "col": 4}},
        {"id": "sc_surv", "type": "shortcut", "data": {"shortcut_name": "Surveys", "col": 4}},
        {"id": "sc_rep1", "type": "shortcut", "data": {"shortcut_name": "Question Breakdown Report", "col": 4}},
        {"id": "sc_rep2", "type": "shortcut", "data": {"shortcut_name": "Answer Distribution Report", "col": 4}},
        {"id": "sc_rep3", "type": "shortcut", "data": {"shortcut_name": "Open Text Answers Report", "col": 4}},
        {"id": "hdr_kpis", "type": "header", "data": {"text": "<span class=\"h4\"><b>Cross-Survey Key Metrics</b></span>", "col": 12}},
        {"id": "nc_1", "type": "number_card", "data": {"number_card_name": "Total Survey Responses", "col": 4}},
        {"id": "nc_2", "type": "number_card", "data": {"number_card_name": "Digital Hygiene Assessments", "col": 4}},
        {"id": "nc_3", "type": "number_card", "data": {"number_card_name": "Average Hygiene Score (%)", "col": 4}},
        {"id": "nc_4", "type": "number_card", "data": {"number_card_name": "Respondents At Risk", "col": 4}},
        {"id": "nc_5", "type": "number_card", "data": {"number_card_name": "Satisfaction Survey Responses", "col": 4}},
        {"id": "hdr_charts", "type": "header", "data": {"text": "<span class=\"h4\"><b>Cross-Survey Overview Charts</b></span>", "col": 12}},
        {"id": "ch_1", "type": "chart", "data": {"chart_name": "Survey Responses by Survey", "col": 6}},
        {"id": "ch_2", "type": "chart", "data": {"chart_name": "Digital Hygiene Grade Distribution", "col": 6}},
        {"id": "ch_3", "type": "chart", "data": {"chart_name": "Average Score (%) by Survey", "col": 6}},
        {"id": "ch_4", "type": "chart", "data": {"chart_name": "Survey Submissions Over Time", "col": 6}},
        {"id": "ch_5", "type": "chart", "data": {"chart_name": "Survey Question Average Scores", "col": 12}},
    ])
    ws.save(ignore_permissions=True)
    frappe.db.commit()


def main():
    parser = argparse.ArgumentParser(description="Migrate Odoo surveys and responses to ERPNext.")
    parser.add_argument("--site", default="frontend")
    parser.add_argument("--input", default="/tmp/odoo_surveys_data.json")
    args = parser.parse_args()

    frappe.init(site=args.site, sites_path="/home/frappe/frappe-bench/sites")
    frappe.connect()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("1. Creating/updating Custom DocTypes (Survey, Survey Response, child tables)...")
    ensure_custom_doctypes()

    print("2. Creating/updating Server Script for Survey Response scoring & answer table population...")
    ensure_server_script()

    print("3. Migrating Surveys, bilingual Web Forms, and historical Survey Responses...")
    migrate_surveys_and_responses(data)

    print("4. Creating bilingual /surveys and /en/surveys Catalog Web Pages & legacy redirects...")
    ensure_survey_catalog_pages_and_redirects(data)

    print("5. Creating native Frappe Survey Analytics Dashboard, Reports, and Surveys Workspace...")
    ensure_survey_analytics_dashboard_and_workspace()

    frappe.clear_cache()
    print(f"Done! Survey count: {frappe.db.count('Survey')} | Survey Response count: {frappe.db.count('Survey Response')} | Survey Web Forms: {frappe.db.count('Web Form', {'doc_type': 'Survey Response'})}")


if __name__ == "__main__":
    main()
