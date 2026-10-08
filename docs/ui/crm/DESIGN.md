---
name: Mercator's Hoard — CRM extension
description: Scoped record of the inherited customer and opportunity workspace.
colors:
  primary: "var(--mint)"
  accent-ink: "var(--hoard-accent-ink)"
  surface-control: "var(--panel)"
  surface-hover: "var(--hoard-elevated)"
  text-primary: "var(--bright)"
  text-secondary: "var(--quiet)"
  border: "var(--line)"
rounded:
  control: "var(--hoard-radius)"
spacing:
  grid: "1rem"
  actions: ".7rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    padding: ".65rem .8rem"
  button-neutral:
    backgroundColor: "{colors.surface-control}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.control}"
    padding: ".65rem .8rem"
  button-neutral-hover:
    backgroundColor: "{colors.surface-hover}"
  input-text:
    backgroundColor: "{colors.surface-control}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.control}"
    padding: ".65rem .8rem"
  select-stage:
    backgroundColor: "{colors.surface-control}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.control}"
    padding: ".65rem .8rem"
---

# Design System: Mercator's Hoard — CRM extension

## Overview

**Creative North Star: "Mercator's inherited quiet instrument panel"**

This record covers the customer and opportunity section, its inline editor,
and interaction history. The [root DESIGN.md](../../../DESIGN.md) retains
project-wide authority and [PRODUCT.md](../../../PRODUCT.md) retains product
context. Neither is rewritten by this narrow extension.

Ground truth is `static/index.html`, `static/crm.css`, `static/crm.js`, and
the existing `static/style.css` cascade. The CRM adopts its live inherited
variables and Hoard type stacks without reconciling incidental drift in
older root prose. Its [sidecar](.impeccable/design.json) is surface-scoped.

**Key Characteristics:**
- Quiet inherited surfaces and an existing accent for save and focus.
- Exact opportunities in a table, with project filters and currency context.
- Persistent company, opportunity and interaction records in an inline editor.

## Colors

The CRM uses the existing Mercator aliases and shared Hoard variables.
Frontmatter references the live cascade rather than freezing an older
palette description or duplicating the family theme.

### Primary

- **Mercator accent:** existing `--mint` alias for filled save, caret and
  keyboard focus; its inherited variable name is not a new color decision.
- **Accent ink:** the existing ink paired with the filled save control.

### Neutral

- **Control surface:** distinguishes native fields and neutral actions.
- **Hover surface:** softly lifts a button within the existing palette.
- **Primary and secondary text:** names and entered values contrast with
  labels, counts, explanatory notes and interaction dates.
- **Border:** divides summaries, table rows and the inline editor.

**The Inherited Palette Rule.** Bind controls to the existing Mercator/Hoard
variables; this section does not define a separate CRM theme.

## Typography

Section and editor headings reuse the Hoard serif stack; native fields and
buttons inherit the Hoard sans stack. The CRM adds no hero or display scale.
Its section h2 inherits the established responsive section heading; editor
h3 uses the existing serif face at 1.5rem. Labels use .88rem; interaction
dates use .85rem. Summary and money cells use tabular numerals. History
detail text wraps and uses the sans face at .88rem.

## Layout

Filters use four equal zero-minimum columns with 1rem gaps, then two
columns below 900px and one below 600px. The filter submission is an explicit
action. Action rows wrap with .7rem gaps. The editor is inline beneath the
listing, separated by a border rather than a modal or new panel world.

The editor has two columns, a maximum width of 900px, and full-row notes and
document-reference fields. Below 600px all fields stack. Controls have a
minimum height of 44px and stay within their container. Textareas resize
vertically, beginning at 6rem.

The opportunity table retains five columns and a minimum width of 700px.
Its overflow belongs to a focusable, labeled horizontal scroll region;
mobile does not force the page itself wider. Keyboard focus visibly
identifies that region before arrow-key scrolling. Summary and history
prose use a 75ch bound; table annotations use a 32ch bound and wrap long data.

**The Exact Record Rule.** Keep opportunity, project, stage, estimate and
next action available together; preserve the accessible scroll region at
narrow widths instead of hiding columns.

## Elevation & Depth

The CRM uses inherited tonal surfaces and one-pixel dividers. It introduces
no shadow, overlay, blur, chart, or animated pipeline layer.

## Shapes

Native controls reuse the existing Hoard control radius. Summary, table and
history remain flat records separated by rules. No opportunity-card shape
or new corner vocabulary is added.

## Components

### Buttons

Neutral actions share field material and readable text. Hover uses the
inherited elevated surface and stronger border. The save control uses the
existing accent with paired accent ink. Busy operations disable buttons;
pagination also disables unavailable directions. Focus has a two-pixel
accent outline with a three-pixel offset.

### Inputs / Fields

Visible labels identify project, owner, stage and search. The native stage
select uses explicit Spanish stage names. Company and opportunity fields
retain notes, source references and People contact references; opportunities
also retain document references, currency, probability and follow-up action.
Opening the editor focuses its first native field. Operation results and
errors use a polite live status region.

### Opportunity table and summary

The caption reports opportunities and companies in the active filter.
Row buttons open their opportunity; company names and follow-up dates
appear as subordinate text. Summary amounts remain separate per currency,
with a visible note that estimates and won amounts do not mean collected
revenue. Pagination is bounded to 50 records per page.

### History and export

Real interaction notes keep their date and source. Recorded changes use
native details disclosure, with wrapped content. JSON and CSV export use
the active filters. History shows the latest 200 activities and explicitly
directs users to JSON for the complete record when that bound is reached.
AI services and 3D commissions are project values, not separate UI themes.

## Do's and Don'ts

### Do:
- **Do** reuse Mercator's existing type, surfaces, accent and control radius.
- **Do** preserve the labeled, keyboard-scrollable opportunity region.
- **Do** keep currency and estimate meaning visible with commercial amounts.
- **Do** retain saved references, notes and interaction dates in the editor.

### Don't:
- **Don't** restyle the surrounding project, analytics, sales or catalog sections.
- **Don't** treat QA companies, opportunities or interactions as live customers.
- **Don't** turn this local table composition into a project-wide layout rule.

<!-- Verification: D:/LocalAI/_hoard_research_20261004/qa-crm-specialists/report.json;
     crm-1440.png and crm-390.png. Real local HTTP UI and stdio with isolated
     synthetic records: company/opportunity creation, project filtering,
     stage editing, history, JSON/CSV export, table keyboard scrolling and
     visible focus passed. No browser errors. -->
