# Odoo Surveys (`survey`) to ERPNext (`Survey`, `Survey Response`, `Web Form`) Mapping Reference

## 1. Filtering Criteria ("Non-Draft with > 2 Answers")

| Level | Odoo Table | Filter Condition | Explanation |
|---|---|---|---|
| **Participant Response** | `survey_user_input` + `survey_user_input_line` | `ui.state != 'new'` AND `COUNT(uil.id) FILTER (WHERE uil.skipped = false) > 2` | Excludes draft/unstarted sessions (`state = 'new'`) and abandoned clicks with 2 or fewer answered questions. Includes completed (`done`) and partially completed (`in_progress`) responses with at least 3 answered questions. |
| **Survey** | `survey_survey` | `s.active = true` AND `COUNT(valid_responses) > 2` | Excludes archived/inactive surveys and test/draft surveys that have 2 or fewer valid responses. |

---

## 2. Survey Definition Mapping (`survey_survey` $\rightarrow$ `Survey` & `Web Form`)

| Odoo Field (`survey_survey`) | ERPNext Field (`Survey`) | ERPNext `Web Form` Mapping |
|---|---|---|
| `id` | `odoo_survey_id` (`Int`) | — |
| `access_token` | `odoo_access_token` (`Data`) | Added to `Website Settings.route_redirects`: `/survey/start/<access_token>` $\rightarrow$ `/surveys/<slug>` |
| `title->>'pl_PL'` | `title_pl` (`Data`) | Polish `Web Form.title` (`route = surveys/<slug>`) |
| `title->>'en_US'` | `title_en` (`Data`) | English `Web Form.title` (`route = en/surveys/<slug>`) |
| `description->>'pl_PL'` | `description_pl` (`Text Editor`) | Polish `Web Form.introduction_text` |
| `description->>'en_US'` | `description_en` (`Text Editor`) | English `Web Form.introduction_text` |
| `scoring_type` (`grading_with_answers`, `scoring_with_answers`, `no_scoring`) | `scoring_type` (`Select`) | Controls whether client-side & server-side scoring/grading is active |

---

## 3. Question & Answer Choice Mapping (`survey_question` + `survey_question_answer` $\rightarrow$ `Survey Question Item` & `Web Form Field`)

| Odoo Field | ERPNext `Survey Question Item` | ERPNext `Web Form Field` |
|---|---|---|
| Sequential question index (`1..20`) | `question_code` (`q_01`..`q_20`) | `fieldname = "q_01"`..`"q_20"` |
| Preceding `is_page = true` `title` | `section_pl` / `section_en` | Preceded by a `Section Break` field in `Web Form` when the section changes |
| `title->>'pl_PL'` / `title->>'en_US'` | `question_pl` / `question_en` | `label` on Polish / English `Web Form Field` |
| `question_type = 'simple_choice'` | `question_type = "simple_choice"` | `fieldtype = "Select"`, `options` = newline-separated choices from `survey_question_answer` (rendered as interactive radio buttons via `client_script`) |
| `question_type = 'scale'` (`scale_min`..`scale_max`) | `question_type = "scale"` | `fieldtype = "Select"`, `options` = scale values `min..max` with min/mid/max labels (rendered as interactive scale buttons via `client_script`) |
| `question_type = 'text_box'` / `'char_box'` | `question_type = "text_box"` | `fieldtype = "Small Text"` |
| `survey_question_answer.answer_score` | `score_map_json` (JSON mapping option value/index $\rightarrow$ score) | Used by `Server Script` and `Web Form` `client_script` to calculate `scoring_total` and `scoring_percentage` |

---

## 4. Grading Mapping (`survey_grade` $\rightarrow$ `Survey Grade Item`)

From the custom Odoo `survey_grading` module (`survey_grade` table):

| Odoo Field (`survey_grade`) | ERPNext `Survey Grade Item` |
|---|---|
| `grade_name->>'pl_PL'` | `grade_name_pl` (`Data`) |
| `grade_name->>'en_US'` | `grade_name_en` (`Data`) |
| `min_score_percentage` | `min_score_percentage` (`Float`) |
| `max_score_percentage` | `max_score_percentage` (`Float`) |
| `grade_description->>'pl_PL'` | `description_pl` (`Small Text`) |
| `grade_description->>'en_US'` | `description_en` (`Small Text`) |

---

## 5. Historical & New Responses Mapping (`survey_user_input` + `survey_user_input_line` $\rightarrow$ `Survey Response` + `Survey Response Answer`)

| Odoo Field (`survey_user_input`) | ERPNext Field (`Survey Response`) |
|---|---|
| `id` | `odoo_input_id` (`Int`, unique index for idempotency) |
| `access_token` | `odoo_access_token` (`Data`) |
| `survey_id` | `survey` (`Link` $\rightarrow$ `Survey`) |
| `state` (`done`, `in_progress`) | `state` (`Select`: `done`, `in_progress`) |
| `create_date` / `end_datetime` | `submitted_at` (`Datetime`) |
| `email` | `respondent_email` (`Data`) |
| `nickname` | `respondent_name` (`Data`) |
| `test_entry` | `is_test_entry` (`Check`) |
| `scoring_total` | `scoring_total` (`Float`) |
| `scoring_percentage` | `scoring_percentage` (`Float`) |
| `achieved_grade_name` | `achieved_grade` (`Data`) |
| `achieved_grade_description` | `achieved_grade_description` (`Text Editor`) |
| `survey_user_input_line` rows | Stored both in `q_01`..`q_20` fields AND in the `answers` (`Survey Response Answer`) child table (`question_code`, `question_text`, `answer_value`, `answer_score`, `odoo_question_id`) |
