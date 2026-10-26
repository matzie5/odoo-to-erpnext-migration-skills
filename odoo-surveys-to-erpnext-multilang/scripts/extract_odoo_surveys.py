#!/usr/bin/env python3
"""
Extract active (non-draft) Odoo surveys and their non-draft responses (> 2 answers)
with full bilingual (PL | EN) support for migration to ERPNext.
"""
import argparse
import json
import re
import subprocess
import sys


SLUG_MAP = {
    2: "digital-risk-assessment-archive",
    4: "digital-hygiene-assessment",
    5: "digital-hygiene-assessment-endress-hauser",
    6: "webinar-satisfaction-survey",
    7: "training-satisfaction-survey",
    8: "workshop-satisfaction-survey",
}

SECTION_PL_MAP = {
    "Daily habits": "Codzienne nawyki",
    "Interactions with others": "Relacje z innymi",
    "Life impact": "Wpływ na życie",
}

SURVEY_TITLE_OVERRIDES = {
    2: {
        "pl": "Ocena Ryzyka Cyfrowego - Archiwum",
        "en": "Digital Risk Assessment - Archive",
    },
    7: {
        "pl": "Ankieta satysfakcji ze szkolenia",
        "en": "Training Satisfaction Survey",
    },
}

SURVEY_DESC_OVERRIDES = {
    2: {
        "pl": "<p>Odpowiedz na 18 pytań dotyczących codziennych nawyków cyfrowych, relacji z innymi oraz wpływu technologii na Twoje życie, aby ocenić poziom ryzyka cyfrowego.</p>",
        "en": "<p>Answer 18 questions about your daily digital habits, interactions with others, and life impact to evaluate your digital risk level.</p>",
    },
    4: {
        "pl": "<p>Odpowiedz na 20 pytań i sprawdź swój obecny stan higieny cyfrowej. Po wypełnieniu testu od razu otrzymasz wynik wraz z interpretacją.</p>",
        "en": "<p>Answer 20 questions to assess your current digital hygiene. Upon submitting the assessment, you will immediately receive your score and personalized feedback.</p>",
    },
    5: {
        "pl": "<p>Samoocena higieny cyfrowej przygotowana dla uczestników programu Endress+Hauser. Odpowiedz na 20 pytań, aby poznać swój wynik.</p>",
        "en": "<p>Digital hygiene self-assessment prepared for Endress+Hauser program participants. Answer 20 questions to see your result.</p>",
    },
    7: {
        "pl": "<p>Dziękujemy za udział w warsztatach dotyczących higieny cyfrowej! Państwa opinia pomoże nam dalej doskonalić nasze szkolenia.</p>",
        "en": "<p>Thank you for participating in our digital hygiene training workshop! Your feedback helps us continuously improve our programs.</p>",
    },
}

SURVEY_7_QUESTION_EN_MAP = {
    80: "How would you rate the overall value of the digital hygiene workshop?",
    81: "Did the training content match your expectations?",
    82: "Was the information presented in an understandable and engaging way?",
    83: "How would you rate the students' engagement in the session?",
    84: "How would you rate the substantive preparation and effectiveness of the trainer?",
    85: "Do you have any additional comments or suggestions?",
}

DEFAULT_GRADES_PL = {
    "Balanced": (
        "Zrównoważony",
        "<p>Twoje cyfrowe nawyki są prawdopodobnie zdrowe i zrównoważone. Masz dobrą świadomość korzystania z technologii i jej potencjalnego wpływu.</p>",
    ),
    "Controlled": (
        "Pod kontrolą",
        "<p>Choć masz kontrolę nad swoim używaniem technologii, możesz doświadczać pewnych negatywnych konsekwencji z tego wynikających. Warto rozważyć strategie, które pomogą Ci ograniczyć czas przed ekranem i poprawić samopoczucie.</p>",
    ),
    "At Risk": (
        "W grupie ryzyka",
        "<p>Twoje korzystanie z technologii może wpływać na Twoje zdrowie psychiczne i fizyczne. Ważne jest, aby podjąć kroki w celu rozwiązania tych problemów i stworzenia zdrowszej relacji z technologią.</p>",
    ),
    "Unhealthy": (
        "Niezdrowy",
        "<p>Twoje korzystanie z technologii może wskazywać na e-uzależnienie. Kluczowe jest, aby poszukać profesjonalnej pomocy w zarządzaniu swoimi cyfrowymi nawykami i poprawie ogólnego samopoczucia.</p>",
    ),
}


def slugify(text: str) -> str:
    s = (text or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "survey"


def run_psql_json(container: str, db_name: str, db_user: str, sql: str):
    cmd = [
        "sudo",
        "docker",
        "exec",
        container,
        "psql",
        "-U",
        db_user,
        "-d",
        db_name,
        "-t",
        "-A",
        "-c",
        sql,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out = res.stdout.strip()
    return json.loads(out) if out else []


def get_lang(val, lang: str, fallback: str = "") -> str:
    if not val:
        return fallback
    if isinstance(val, dict):
        return (val.get(lang) or val.get("en_US") or val.get("pl_PL") or fallback).strip()
    return str(val).strip()


def build_scale_options(q: dict, lang: str) -> list[str]:
    s_min = int(q.get("scale_min") if q.get("scale_min") is not None else 1)
    s_max = int(q.get("scale_max") if q.get("scale_max") is not None else 5)
    min_lbl = get_lang(q.get("scale_min_label"), lang)
    mid_lbl = get_lang(q.get("scale_mid_label"), lang)
    max_lbl = get_lang(q.get("scale_max_label"), lang)

    # Fix known Odoo translation typos on presenter effectiveness & webinar satisfaction
    q_id = q.get("id")
    if q_id in (76, 89) and lang == "pl_PL":
        min_lbl = "Bardzo nieskuteczny(-a)"
        mid_lbl = "Neutralnie"
        max_lbl = "Bardzo skuteczny(-a)"
    elif q_id == 73 and lang == "en_US":
        max_lbl = "Very Satisfied"
    elif q_id in (78, 86, 89, 91) and lang == "pl_PL" and not mid_lbl:
        mid_lbl = "Neutralnie"
    elif q_id == 86 and lang == "pl_PL" and max_lbl == "Very satisfied":
        max_lbl = "Bardzo zadowolony(-a)"

    mid_val = (s_min + s_max) // 2 if (s_max - s_min) == 4 else None
    options = []
    for v in range(s_min, s_max + 1):
        if v == s_min and min_lbl:
            options.append(f"{v} - {min_lbl}")
        elif mid_val is not None and v == mid_val and mid_lbl:
            options.append(f"{v} - {mid_lbl}")
        elif v == s_max and max_lbl:
            options.append(f"{v} - {max_lbl}")
        else:
            options.append(str(v))
    return options


def main():
    parser = argparse.ArgumentParser(description="Extract non-draft Odoo surveys and responses (> 2 answers).")
    parser.add_argument("--db-container", default="20261022-db-1")
    parser.add_argument("--db-name", default="digitaldetox")
    parser.add_argument("--db-user", default="odoo")
    parser.add_argument("--min-answers", type=int, default=2)
    parser.add_argument("--output", default="/tmp/odoo_surveys_data.json")
    args = parser.parse_args()

    sql = f"""
    WITH valid_inputs AS (
        SELECT
            ui.id,
            ui.survey_id,
            ui.state,
            ui.access_token,
            COALESCE(ui.test_entry, false) AS test_entry,
            ui.email,
            ui.nickname,
            ui.scoring_total,
            ui.scoring_percentage,
            ui.achieved_grade_name,
            ui.achieved_grade_description,
            COALESCE(ui.end_datetime, ui.start_datetime, ui.create_date) AS submitted_at,
            COUNT(uil.id) FILTER (WHERE uil.skipped = false) AS answered_count
        FROM survey_user_input ui
        JOIN survey_user_input_line uil ON uil.user_input_id = ui.id
        WHERE ui.state != 'new'
        GROUP BY ui.id
        HAVING COUNT(uil.id) FILTER (WHERE uil.skipped = false) > {args.min_answers}
    ),
    valid_surveys AS (
        SELECT
            s.id,
            s.title,
            s.description,
            s.description_done,
            s.scoring_type,
            s.access_token,
            COUNT(vi.id) AS valid_response_count
        FROM survey_survey s
        JOIN valid_inputs vi ON vi.survey_id = s.id
        WHERE s.active = true
        GROUP BY s.id
        HAVING COUNT(vi.id) > {args.min_answers}
    )
    SELECT COALESCE(json_agg(row_to_json(t) ORDER BY t.id), '[]'::json)
    FROM (
        SELECT
            vs.id,
            vs.title,
            vs.description,
            vs.description_done,
            vs.scoring_type,
            vs.access_token,
            vs.valid_response_count,
            COALESCE((
                SELECT json_agg(row_to_json(q_row) ORDER BY q_row.sequence, q_row.id)
                FROM (
                    SELECT
                        q.id,
                        q.sequence,
                        q.is_page,
                        q.question_type,
                        q.title,
                        q.description,
                        q.constr_mandatory,
                        q.scale_min,
                        q.scale_max,
                        q.scale_min_label,
                        q.scale_mid_label,
                        q.scale_max_label,
                        COALESCE((
                            SELECT json_agg(row_to_json(a_row) ORDER BY a_row.sequence, a_row.id)
                            FROM (
                                SELECT qa.id, qa.sequence, qa.value, qa.answer_score, qa.is_correct
                                FROM survey_question_answer qa
                                WHERE qa.question_id = q.id
                            ) a_row
                        ), '[]'::json) AS suggested_answers
                    FROM survey_question q
                    WHERE q.survey_id = vs.id
                ) q_row
            ), '[]'::json) AS questions,
            COALESCE((
                SELECT json_agg(row_to_json(g_row) ORDER BY g_row.min_score_percentage, g_row.id)
                FROM (
                    SELECT
                        g.id,
                        g.grade_name,
                        g.grade_description,
                        g.min_score_percentage,
                        g.max_score_percentage
                    FROM survey_grade g
                    WHERE g.survey_id = vs.id
                ) g_row
            ), '[]'::json) AS grades,
            COALESCE((
                SELECT json_agg(row_to_json(r_row) ORDER BY r_row.id)
                FROM (
                    SELECT
                        vi.id,
                        vi.state,
                        vi.access_token,
                        vi.test_entry,
                        vi.email,
                        vi.nickname,
                        vi.scoring_total,
                        vi.scoring_percentage,
                        vi.achieved_grade_name,
                        vi.achieved_grade_description,
                        vi.submitted_at,
                        vi.answered_count,
                        COALESCE((
                            SELECT json_agg(row_to_json(l_row) ORDER BY l_row.question_sequence, l_row.id)
                            FROM (
                                SELECT
                                    uil.id,
                                    uil.question_id,
                                    uil.question_sequence,
                                    uil.answer_type,
                                    uil.suggested_answer_id,
                                    uil.value_scale,
                                    uil.value_char_box,
                                    uil.value_text_box,
                                    uil.value_numerical_box,
                                    uil.answer_score,
                                    qa.value AS suggested_answer_value
                                FROM survey_user_input_line uil
                                LEFT JOIN survey_question_answer qa ON qa.id = uil.suggested_answer_id
                                WHERE uil.user_input_id = vi.id AND uil.skipped = false
                            ) l_row
                        ), '[]'::json) AS lines
                    FROM valid_inputs vi
                    WHERE vi.survey_id = vs.id
                ) r_row
            ), '[]'::json) AS responses
        FROM valid_surveys vs
    ) t;
    """

    raw_surveys = run_psql_json(args.db_container, args.db_name, args.db_user, sql)
    processed_surveys = []

    for s in raw_surveys:
        s_id = s["id"]
        slug = SLUG_MAP.get(s_id) or slugify(get_lang(s.get("title"), "en_US"))

        title_pl = SURVEY_TITLE_OVERRIDES.get(s_id, {}).get("pl") or get_lang(s.get("title"), "pl_PL")
        title_en = SURVEY_TITLE_OVERRIDES.get(s_id, {}).get("en") or get_lang(s.get("title"), "en_US")

        desc_pl = SURVEY_DESC_OVERRIDES.get(s_id, {}).get("pl") or get_lang(s.get("description"), "pl_PL")
        desc_en = SURVEY_DESC_OVERRIDES.get(s_id, {}).get("en") or get_lang(s.get("description"), "en_US")

        # Process grades
        grades = []
        for g in s.get("grades", []):
            g_en = get_lang(g.get("grade_name"), "en_US")
            g_pl = (g.get("grade_name") or {}).get("pl_PL")
            d_en = get_lang(g.get("grade_description"), "en_US")
            d_pl = (g.get("grade_description") or {}).get("pl_PL")
            if not g_pl and g_en in DEFAULT_GRADES_PL:
                g_pl = DEFAULT_GRADES_PL[g_en][0]
            if not d_pl and g_en in DEFAULT_GRADES_PL:
                d_pl = DEFAULT_GRADES_PL[g_en][1]
            grades.append({
                "odoo_grade_id": g["id"],
                "grade_name_pl": g_pl or g_en,
                "grade_name_en": g_en or g_pl,
                "min_score_percentage": float(g.get("min_score_percentage") or 0),
                "max_score_percentage": float(g.get("max_score_percentage") or 100),
                "description_pl": d_pl or d_en,
                "description_en": d_en or d_pl,
            })

        # Process questions and sections
        questions = []
        q_by_odoo_id = {}
        current_section_en = ""
        current_section_pl = ""
        q_idx = 0

        for q in s.get("questions", []):
            if q.get("is_page"):
                current_section_en = get_lang(q.get("title"), "en_US")
                current_section_pl = (
                    (q.get("title") or {}).get("pl_PL")
                    or SECTION_PL_MAP.get(current_section_en)
                    or current_section_en
                )
                continue

            q_idx += 1
            q_code = f"q_{q_idx:02d}"
            q_id = q["id"]
            q_type = q.get("question_type") or "simple_choice"

            if s_id == 7:
                q_pl = get_lang(q.get("title"), "en_US")
                q_en = SURVEY_7_QUESTION_EN_MAP.get(q_id, q_pl)
            else:
                q_pl = get_lang(q.get("title"), "pl_PL")
                q_en = get_lang(q.get("title"), "en_US")

            options_pl = []
            options_en = []
            score_map = {}
            answer_id_map = {}

            if q_type == "simple_choice":
                for idx_a, a in enumerate(q.get("suggested_answers", []), start=1):
                    opt_pl = get_lang(a.get("value"), "pl_PL")
                    opt_en = get_lang(a.get("value"), "en_US")
                    score = float(a.get("answer_score") or 0)
                    options_pl.append(opt_pl)
                    options_en.append(opt_en)
                    score_map[opt_pl] = score
                    score_map[opt_en] = score
                    score_map[str(idx_a)] = score
                    answer_id_map[a["id"]] = {
                        "pl": opt_pl,
                        "en": opt_en,
                        "score": score,
                        "index": idx_a,
                    }
            elif q_type == "scale":
                options_pl = build_scale_options(q, "pl_PL")
                options_en = build_scale_options(q, "en_US")
                s_min = int(q.get("scale_min") if q.get("scale_min") is not None else 1)
                for offset, (opt_pl, opt_en) in enumerate(zip(options_pl, options_en)):
                    val_num = s_min + offset
                    score_map[opt_pl] = float(val_num)
                    score_map[opt_en] = float(val_num)
                    score_map[str(val_num)] = float(val_num)

            q_obj = {
                "question_code": q_code,
                "odoo_question_id": q_id,
                "sequence": q.get("sequence") or q_idx,
                "section_pl": current_section_pl,
                "section_en": current_section_en,
                "question_pl": q_pl,
                "question_en": q_en,
                "question_type": q_type,
                "mandatory": 1 if q.get("constr_mandatory", True) else 0,
                "scale_min": q.get("scale_min"),
                "scale_max": q.get("scale_max"),
                "options_pl": options_pl,
                "options_en": options_en,
                "score_map": score_map,
                "_answer_id_map": answer_id_map,
            }
            questions.append(q_obj)
            q_by_odoo_id[q_id] = q_obj

        max_possible_score = len(questions) * 5.0 if s.get("scoring_type") == "grading_with_answers" else 0.0

        # Process responses
        responses = []
        for r in s.get("responses", []):
            ans_list = []
            flat_answers_pl = {}
            flat_answers_en = {}
            computed_score = 0.0

            for line in r.get("lines", []):
                q_obj = q_by_odoo_id.get(line["question_id"])
                if not q_obj:
                    continue
                q_code = q_obj["question_code"]
                a_type = line.get("answer_type")
                val_pl = ""
                val_en = ""
                a_score = float(line.get("answer_score") or 0.0)

                if a_type == "suggestion":
                    sug_id = line.get("suggested_answer_id")
                    mapped = q_obj["_answer_id_map"].get(sug_id)
                    if mapped:
                        val_pl = mapped["pl"]
                        val_en = mapped["en"]
                        if not a_score:
                            a_score = mapped["score"]
                    else:
                        val_pl = get_lang(line.get("suggested_answer_value"), "pl_PL")
                        val_en = get_lang(line.get("suggested_answer_value"), "en_US")
                elif a_type == "scale":
                    v_scale = line.get("value_scale")
                    if v_scale is not None:
                        v_int = int(v_scale)
                        if q_obj["question_type"] == "simple_choice":
                            # Early Survey 2 responses recorded on 1..5 scale before conversion to simple_choice
                            idx0 = max(0, min(len(q_obj["options_pl"]) - 1, v_int - 1))
                            val_pl = q_obj["options_pl"][idx0] if q_obj["options_pl"] else str(v_int)
                            val_en = q_obj["options_en"][idx0] if q_obj["options_en"] else str(v_int)
                            if not a_score:
                                a_score = float(v_int)
                        else:
                            s_min = int(q_obj["scale_min"] if q_obj["scale_min"] is not None else 1)
                            idx0 = v_int - s_min
                            val_pl = (
                                q_obj["options_pl"][idx0]
                                if 0 <= idx0 < len(q_obj["options_pl"])
                                else str(v_int)
                            )
                            val_en = (
                                q_obj["options_en"][idx0]
                                if 0 <= idx0 < len(q_obj["options_en"])
                                else str(v_int)
                            )
                            a_score = float(v_int)
                elif a_type in ("text_box", "char_box"):
                    txt = (line.get("value_text_box") or line.get("value_char_box") or "").strip()
                    val_pl = txt
                    val_en = txt
                elif a_type == "numerical_box":
                    num = str(line.get("value_numerical_box") or "")
                    val_pl = num
                    val_en = num

                computed_score += a_score
                flat_answers_pl[q_code] = val_pl
                flat_answers_en[q_code] = val_en
                ans_list.append({
                    "question_code": q_code,
                    "odoo_question_id": line["question_id"],
                    "question_pl": q_obj["question_pl"],
                    "question_en": q_obj["question_en"],
                    "answer_value_pl": val_pl,
                    "answer_value_en": val_en,
                    "answer_score": a_score,
                })

            scoring_total = float(r.get("scoring_total") or 0.0)
            scoring_pct = float(r.get("scoring_percentage") or 0.0)
            if s.get("scoring_type") == "grading_with_answers":
                if scoring_total <= 0 and computed_score > 0:
                    scoring_total = computed_score
                if scoring_pct <= 0 and max_possible_score > 0 and scoring_total > 0:
                    scoring_pct = round((scoring_total / max_possible_score) * 100.0, 1)

            achieved_grade = (r.get("achieved_grade_name") or "").strip()
            achieved_desc = (r.get("achieved_grade_description") or "").strip()
            if s.get("scoring_type") == "grading_with_answers" and grades and scoring_pct > 0 and not achieved_grade:
                for g in grades:
                    if g["min_score_percentage"] <= round(scoring_pct) <= g["max_score_percentage"]:
                        achieved_grade = g["grade_name_pl"]
                        achieved_desc = g["description_pl"]
                        break

            responses.append({
                "odoo_input_id": r["id"],
                "access_token": r["access_token"],
                "state": r["state"],
                "is_test_entry": 1 if r.get("test_entry") else 0,
                "email": (r.get("email") or "").strip(),
                "nickname": (r.get("nickname") or "").strip(),
                "submitted_at": r.get("submitted_at"),
                "scoring_total": scoring_total,
                "scoring_percentage": round(scoring_pct, 2),
                "achieved_grade": achieved_grade,
                "achieved_grade_description": achieved_desc,
                "flat_answers_pl": flat_answers_pl,
                "flat_answers_en": flat_answers_en,
                "answers": ans_list,
            })

        # Strip internal helper map before serializing
        for q_obj in questions:
            q_obj.pop("_answer_id_map", None)

        processed_surveys.append({
            "odoo_survey_id": s_id,
            "slug": slug,
            "access_token": s.get("access_token"),
            "scoring_type": s.get("scoring_type") or "no_scoring",
            "title_pl": title_pl,
            "title_en": title_en,
            "description_pl": desc_pl,
            "description_en": desc_en,
            "questions": questions,
            "grades": grades,
            "responses": responses,
        })

    output_payload = {
        "min_answers_filter": args.min_answers,
        "survey_count": len(processed_surveys),
        "total_response_count": sum(len(s["responses"]) for s in processed_surveys),
        "surveys": processed_surveys,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    print(f"Extracted {output_payload['survey_count']} active surveys and {output_payload['total_response_count']} valid responses (> {args.min_answers} answers) -> {args.output}")
    for s in processed_surveys:
        print(f"  - [Odoo #{s['odoo_survey_id']}] {s['slug']}: PL='{s['title_pl']}' | EN='{s['title_en']}' | Questions={len(s['questions'])} | Grades={len(s['grades'])} | Responses={len(s['responses'])}")


if __name__ == "__main__":
    main()
