# Odoo Snippet to ERPNext Web Template Mapping Reference

This reference documents how Odoo 16/17/18 `<section data-snippet="...">` building blocks map to ERPNext's built-in **Page Builder** `Web Template`s and reusable custom `Web Template`s.

---

## 1. Built-in ERPNext `Web Template` Schemas

### `Hero`
- **Use for**: `s_title`, `s_text_block` (page header / H1 + lead paragraph + optional CTA buttons), `s_cover` (centered text hero).
- **Fields (`web_template_values`)**:
  - `title` (`Data`, reqd): Main heading text
  - `subtitle` (`Text`): Lead / subtitle text
  - `primary_action_label` (`Data`), `primary_action` (`Data`): Primary button text & URL
  - `secondary_action_label` (`Data`), `secondary_action` (`Data`): Secondary button text & URL
  - `align` (`Select`: `Left` | `Center`, default `Center`)

### `Hero with Right Image`
- **Use for**: `s_banner`, `s_text_cover` (when hero has text on the left and a prominent illustration/photo on the right).
- **Fields (`web_template_values`)**:
  - `title` (`Data`, reqd)
  - `subtitle` (`Text`)
  - `primary_action_label` (`Data`), `primary_action` (`Data`)
  - `secondary_action_label` (`Data`), `secondary_action` (`Data`)
  - `image` (`Attach Image`): Right-side hero image or colorized SVG shape
  - `contain_image` (`Check`: `1` for SVG illustrations/logos so they aren't cropped, `0` for cover photos)

### `Split Section with Image`
- **Use for**: `s_text_image`, `s_image_text`, `s_image_text_box`, `s_text_cover` (split layout), `s_donation` (with side image).
- **Fields (`web_template_values`)**:
  - `title` (`Data`, reqd)
  - `content` (`Markdown Editor`, reqd): Supports HTML/text inside the split section body
  - `image` (`Attach Image`, reqd)
  - `image_on_right` (`Check`: `1` for `s_text_image`, `0` for `s_image_text` / `s_image_text_box`)
  - `split` (`Select`: `'4 columns - 8 columns'`, `'5 columns - 7 columns'`, `'6 columns - 6 columns'`, `'7 columns - 5 columns'`, `'8 columns - 4 columns'` — note that the Jinja template splits on `' - '` and strips `'columns'`)
  - `vertical_align` (`Select`: `'Top'` | `'Middle'`, default `'Top'` — pass `'Middle'` for bio/team split sections so Frappe does not add `mt-8` top margin on `.split-section-content`)
  - `url_label` & `link_label` (`Data`), `url` & `link_url` (`Data`): Optional CTA link/button below content (populate both pairs so both the Page Builder UI and the Jinja template render the link)
- **Layout & Mobile Ordering Note**:
  - In Frappe's `split_section_with_image.html`, when `image_on_right = 1`, `.split-section-content` comes first in the DOM and the image `<div class="col-12 col-sm-...">` comes second, causing right-aligned images to render **below** the text on mobile while left-aligned images render **above** the text.
  - In `Website Theme.custom_scss`, add a `@media (max-width: 767.98px)` rule on `.split-section-with-image` setting `> div { flex: 0 0 100% !important; max-width: 100% !important; order: 1 !important; }` and `> div.split-section-content { order: 2 !important; margin-top: 1.5rem !important; }` so images consistently appear above text on mobile regardless of `image_on_right`.
  - When stacking multiple consecutive `Split Section with Image` blocks (e.g. team/coach bios), set `add_top_padding = 0` on the 2nd+ blocks and normalize `.section-padding-top` / `.section-padding-bottom` from Frappe's default `8rem` down to `3.5rem` (desktop) / `2.5rem` (mobile).

### `Section with Cards`
- **Use for**: `s_cards_grid`, `s_three_columns`, `s_company_team`, `s_images_mosaic`, `s_references` (up to 9 items).
- **Fields (`web_template_values`)**:
  - `title` (`Data`)
  - `subtitle` (`Data`)
  - `card_size` (`Select`: `Small` | `Medium` | `Large`, default `Small`)
    - `Small`: Up to 4 cards per row (good for team members, reference logos)
    - `Medium`: 3 cards per row (good for service cards, media screenshots, blog previews)
    - `Large`: 2 cards per row
  - `card_1_title`..`card_9_title` (`Data`)
  - `card_1_content`..`card_9_content` (`Small Text`)
  - `card_1_image`..`card_9_image` (`Attach Image`)
  - `card_1_url`..`card_9_url` (`Data`)

### `Section with Features`
- **Use for**: `s_key_benefits`, `s_faq_list` (multi-column feature/benefit grids), `s_showcase` (feature items).
- **Fields (`web_template_values`)**:
  - `title` (`Data`)
  - `subtitle` (`Data`)
  - `columns` (`Select`: `2` | `3` | `4`, default `3`)
  - `features` (`Table Break` -> JSON array of objects):
    - `idx` (`int`): 1-based index
    - `title` (`Data`, reqd)
    - `content` (`Markdown Editor`, reqd)
    - `icon` (`Attach Image`, optional)
    - `url` (`Data`, optional)
- **Header Overlap Quirk & Fix**:
  - Frappe's built-in `section_with_features.html` outputs an inline `<div class="section-features" ... {% if not subtitle %}style="margin-top: -1.5rem"{% endif %}>`. When `subtitle` is empty, that inline negative margin overrides `.section-title + .section-features { margin-top: 3rem }` and pulls white `.section-feature` cards directly over the `<h2 class="section-title">`.
  - Always add `.section-with-features .section-features { margin-top: 2.25rem !important; gap: 2rem !important; }` in `Website Theme.custom_scss`.

### `Section with Collapsible Content`
- **Use for**: `s_accordion_image`, `s_faq_collapse`.
- **Fields (`web_template_values`)**:
  - `title` (`Data`)
  - `subtitle` (`Data`)
  - `align` (`Select`: `Left` | `Center`, default `Left`)
  - `items` (`Table Break` -> JSON array of objects):
    - `idx` (`int`): 1-based index
    - `title` (`Data`, reqd): Accordion header / FAQ question
    - `content` (`Markdown Editor`, reqd): Accordion body / FAQ answer

### `Section with CTA`
- **Use for**: `s_cta_box` (boxed/card CTA sitting inside a section).
- **Fields (`web_template_values`)**:
  - `title` (`Data`, reqd)
  - `subtitle` (`Text`)
  - `cta_label` (`Data`, reqd)
  - `cta_url` (`Data`, reqd)
  - `show_confetti` (`Check`: `0`)
- **Layout & Theme Note**:
  - Frappe's base CSS styles `.section-cta` (inside `.section-cta-container`) with `background-color: #ededed; padding: 5rem 3rem;`.
  - In `Website Theme.custom_scss`, reset `.section-cta-container` to `background: transparent !important; padding: 0 !important;` and style `.section-cta` directly with the primary card background (`var(--primary)`), white text (`#FFFFFF`), `border-radius: 0.75rem`, and compact padding (`2.25rem 2rem`).
  - Keep the outer `Web Page Block` neutral (`css_class = "o-cc1"`, `add_top_padding = 0`) so the colored card sits cleanly on a white background just like Odoo's `s_cta_box`.

### `Section with Small CTA`
- **Use for**: `s_call_to_action` (horizontal 2-column CTA banner with left-aligned text and right-aligned button, e.g. on dark `o_cc5` background).
- **Fields (`web_template_values`)**:
  - `title` (`Data`, reqd)
  - `subtitle` (`Small Text`)
  - `cta_label` (`Data`, reqd)
  - `cta_url` (`Data`, reqd)
- **Layout & Theme Note**:
  - Set `css_class = "o-cc5"` on the `Web Page Block` for dark full-width CTA banners, and style `.o-cc5 .section-small-cta` with `background-color: transparent !important; box-shadow: none !important; padding: 0.5rem 0 !important;` so the left-aligned white text and right-aligned primary CTA button sit directly inside the dark section.

### `Section with Testimonials`
- **Use for**: `s_quotes_carousel`, `s_blockquote`.
- **Fields (`web_template_values`)**:
  - `title` (`Data`)
  - `subtitle` (`Data`)
  - `testimonials` (`Table Break` -> JSON array of objects):
    - `idx` (`int`): 1-based index
    - `content` (`Markdown Editor`): Quote text
    - `sender_name` & `full_name` (`Data`): Author name
    - `sender_Role` & `designation` (`Data`): Author title/organization
    - `sender_avatar` & `image` (`Attach Image`): Author photo

### `Section with Image Grid`
- **Use for**: `s_image_gallery` (up to 4 images).
- **Fields (`web_template_values`)**:
  - `title` (`Data`)
  - `subtitle` (`Data`)
  - `image_1`..`image_4` (`Attach Image`)

### `Section with Embed`
- **Use for**: `s_embed_code` (iframes, interactive widgets, embedded apps).
- **Fields (`web_template_values`)**:
  - `title` (`Data`)
  - `subtitle` (`Data`)
  - `embed_html` (`Text`): Raw embed/iframe HTML

### `Markdown`
- **Use for**: `s_text_block` (long-form prose, legal policies, multi-paragraph narrative sections).
- **Fields (`web_template_values`)**:
  - `content` (`Markdown Editor`, reqd)

---

## 2. Reusable Custom `Web Template`s (`standard = 0`)

Create these reusable `Web Template`s when migrating sites that use dynamic blog grids, >9 partner logos, showcase layouts with central illustration, or embedded interactive forms:

1. **`Showcase with Central Image`**:
   - **Maps from**: `s_showcase` (2x2 feature grid flanking or accompanied by a central illustration + optional CTA).
   - **Fields**: `title`, `subtitle`, `image`, `cta_label`, `cta_url`, `features` (Table: `title`, `content`, `url`).
2. **`Logo Marquee Grid`**:
   - **Maps from**: `s_product_list` / `s_references` when there are more than 9 partner logos or animated marquee styling.
   - **Fields**: `title`, `subtitle`, `logos` (Table: `title`, `image`, `url`).
3. **`Dynamic Blog Posts Grid`**:
   - **Maps from**: `s_blog_posts`.
   - **Fields**: `title`, `subtitle`, `blog_prefix` (default `blog`), `cards` (Table: `title`, `subtitle`, `image`, `url`, `published_date`).
4. **`Contact and Inquiry Form`** (`type = "Section"`):
   - **Maps from**: `s_website_form` (Contact Us form, school workshop inquiry form, waitlist form).
   - **Fields**: `title`, `subtitle`, `intro_markdown`, `form_type` (`contact` | `school_workshop` | `waitlist`), `submit_label`, `show_contact_sidebar` (`Check`), `organization_name`, `phone`, `email`.
5. **`Headline Footer`** (`type = "Footer"`):
   - **Maps from**: `website.template_footer_headline` (`o_footer o_cc5` dark footer with headline row, 3-column links/contact/logo row, and copyright bar).
   - **Linked via**: `Website Settings.footer_template = "Headline Footer"` and `Website Settings.footer_template_values` (JSON).
   - **Fields**: `headline_title` (`Data`), `headline_lead` (`Small Text`), `phone` (`Data`), `email` (`Data`). Also consumes standard `Website Settings` context variables (`footer_items`, `footer_address`, `footer_logo`, `copyright`, `footer_powered`).
   - **Important Notes**:
     - Use `json.loads(...)` (never `frappe.parse_json(...)`) if reading `footer_template_values` directly in Jinja so `Guest` users don't hit `render_safe_globals()` restrictions.
     - Override Frappe's base `.web-footer { min-height: 140px }` and `body { height: 100%; display: flex; flex-direction: column }` with `html, body { min-height: 100vh; height: auto !important; }` and `.web-footer { flex-shrink: 0 !important; height: auto !important; min-height: fit-content !important; }` so the footer container never overflows below `<footer>`.

---

## 3. Color Combinations (`o_cc1`..`o_cc5`) Mapping

In Odoo, `<section class="... o_cc o_cc2">` applies one of 5 theme color combinations.
In ERPNext:
- Set `Web Page Block.css_class` to `o-cc1`, `o-cc2`, `o-cc3`, `o-cc4`, or `o-cc5`.
- For `o_cc2` (light shade), also set `Web Page Block.add_shade = 1`.
- Define `.o-cc1`..`.o-cc5` in `Website Theme.custom_scss` using the website's 5 extracted colors so background, heading, text, and button colors automatically match Odoo.
