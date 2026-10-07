---
name: "Kav-FastwebAgent 展示網站"
description: "A reusable-query itinerary foldout, grounded in the implemented Astro website."
colors:
  forest: "#184f43"
  forest-dark: "#123d34"
  lime: "#ddf391"
  paper: "#f5f7f2"
  ink: "#192d28"
  muted: "#53685f"
  line: "#d5ded6"
  white: "#fff"
  error: "#9d291b"
  sage-surface: "#e7edde"
  focus: "#c56b21"
  lime-hover: "#efffc0"
  dark-hover: "#265f50"
typography:
  display:
    fontFamily: "Manrope Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "clamp(40px, 4.6vw, 68px)"
    fontWeight: 650
    lineHeight: 1.35
    letterSpacing: "-.035em"
  headline:
    fontFamily: "Manrope Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "clamp(30px, 3.1vw, 44px)"
    fontWeight: 650
    lineHeight: 1.35
    letterSpacing: "-.025em"
  title:
    fontFamily: "Manrope Variable, Noto Sans TC Variable, sans-serif"
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.35
    letterSpacing: "-.02em"
  body:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.8
  prose:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.95
  label:
    fontFamily: "Noto Sans TC Variable, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.8
rounded:
  square: "0"
  tag: "3px"
  circle: "50%"
spacing:
  page-gutter: "clamp(24px, 5vw, 80px)"
  page-gutter-mobile: "24px"
  section: "104px"
  section-mobile: "65px"
  content: "24px"
components:
  button-lime:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.forest-dark}"
    rounded: "{rounded.square}"
    padding: "14px 23px"
  button-lime-hover:
    backgroundColor: "{colors.lime-hover}"
  button-dark:
    backgroundColor: "{colors.forest-dark}"
    textColor: "{colors.lime}"
    rounded: "{rounded.square}"
    padding: "14px 23px"
  button-dark-hover:
    backgroundColor: "{colors.dark-hover}"
  route-select:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    width: "100%"
  demo-tag:
    rounded: "{rounded.tag}"
    padding: "1px 7px"
  foldout:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
  callout:
    backgroundColor: "{colors.sage-surface}"
    padding: "22px"
  button-mark:
    backgroundColor: "transparent"
    textColor: "{colors.forest}"
    rounded: "{rounded.square}"
    padding: "10px 14px"
  button-finish:
    backgroundColor: "{colors.forest}"
    textColor: "{colors.paper}"
    rounded: "{rounded.square}"
    padding: "10px 14px"
---

# Design System: Kav-FastwebAgent 展示網站

## Overview

**Creative North Star: "The Everyday Itinerary Foldout"**

Kav’s implemented website presents reusable queries as an orderly paper itinerary: strong forest fields surround pale working surfaces, and lime connects actions with the foldout edge. Traditional Chinese reading comes first, with clear conditions, numbered progress, and aligned results.

This is a scan of the finished Astro implementation, not a claim of user-selected visual identity. The user approved Astro and code-first work; the itinerary metaphor, descriptive color names, and palette remain provisional implementation decisions. The source of truth is website/src/styles/global.css, supported by Layout.astro, FlowDemo.astro, RecordingDemo.astro, Mechanism.astro, and the implemented pages. The surface-specific direction remains in .impeccable/surfaces/website-src-pages-index-astro.md.

**Key Characteristics:**
- Large forest fields and lime action surfaces.
- Square paper panels, fine rules, and tabular results.
- Self-hosted Traditional Chinese and Latin variable typography.
- Responsive reading layouts with explicit demonstration and evidence labels.

## Colors

The palette combines forest ink, citrus paper accents, and quiet gray-green reading surfaces. Normative values are in the frontmatter; names describe the implementation rather than confirmed user preferences. The sidecar’s eight-step OKLCH ramps are synthesized panel previews, not additional shipped color tokens.

### Primary
- **Forest:** major brand fields, progress, and execution controls; **Forest Dark:** closing actions and footer.
- **Lime:** primary actions, the foldout heading, and selected headline emphasis. The hover variants brighten lime or lift dark forest.

### Neutral
- **Paper:** page and itinerary surface. **Ink:** primary reading text. **Muted:** explanations and secondary labels.
- **Line:** table rules and section dividers. **Sage Surface:** documentation headings, code, callouts, and supporting bands. **White:** text on execution controls.
- **Error:** validation feedback. **Focus:** the keyboard outline; these are functional colors, not additional brand accents.

**The Legible Pairing Rule.** Keep lime actions paired with dark forest text, and forest fields paired with pale text; a pale accent is not body text on paper.

## Typography

**Display Font:** self-hosted Manrope Variable, falling back to Noto Sans TC Variable and sans-serif.
**Body Font:** self-hosted Noto Sans TC Variable, falling back to sans-serif.

Manrope provides compact Latin and numeric forms while Noto Sans TC carries Chinese reading. Headings balance lines and tighten tracking; body paragraphs stay open. The frontmatter records the base hierarchy rather than claiming a mathematical type scale.

### Hierarchy
- **Display:** primary page statements; home changes to 70px above the wide breakpoint and clamp(39px, 8vw, 59px) on mobile. Documentation headings use clamp(36px, 4vw, 54px).
- **Headline:** section statements; documentation section headings are 30px, reducing to 27px on mobile.
- **Title:** base subheading; reading-page subheadings use 20px.
- **Body / Prose:** base site reading and denser long-form reading respectively; general paragraphs cap at 70ch and documentation content at 800px.
- **Label:** compact supporting text. Local captions and demo labels range from 11px to 12px; these small sizes describe the existing information density, not a requirement for new explanatory copy.

**The Reading First Rule.** Use the Chinese-capable body stack for explanations and labels; use the display stack for headings and aligned numeric results.

## Layout

The centered page container caps at 1400px including its fluid gutters. Major homepage sections use the section spacing tokens; pairs are composed with CSS grids, not a universal card grid. The hero pairs equal columns, while the featured case pairs a smaller explanation with larger evidence. Supporting sections use full-width tonal bands and fine separators. Recording pairs numbered instructions with a bordered paper demonstration in a 1:1.1 grid; the acceleration explanation uses a dark field and three numbered columns. Both collapse to one column at 760px, with 55px section padding.

Documentation uses a 200px sticky contents column, a 65px gap, and a flexible reading column. At 1050px the contents column becomes 155px and the gap 38px. Navigation wraps to a visible second row at 1050px to preserve the full Kav-FastwebAgent wordmark. At 760px paired sections stack, page gutters become the mobile token, and the contents list becomes static and wraps above the article. The wordmark is 28px on desktop, 26px on tablet, and 20px in the mobile header; the mobile footer uses 24px. The foldout loses its rotation and stays within 520px. Tables retain their field relationships inside horizontal overflow containers. At 1500px and above, the hero gains vertical space and its foldout caps at 545px.

## Elevation & Depth

Most depth comes from contrasting surface colors and one-pixel rules. Only the interactive paper foldout carries a diffuse ambient shadow (0 20px 45px #0c322a40) and a one-degree rotation on desktop. These are material cues rather than a site-wide card treatment.

**The Foldout Depth Rule.** Reserve the ambient shadow and slight rotation for the interactive itinerary; supporting sections and reading surfaces use rules and tonal fields.

## Shapes

Buttons, selects, paper panels, callouts, and code containers are square. The small demonstration tag alone uses the tag radius; numbered progress marks are circular. The itinerary’s dashed horizontal divider separates its editable conditions from results, while straight table rules preserve row comparison. Navigation and text links use underlines and rules rather than enclosing pills.

## Components

### Buttons

Solid, direct controls use the lime and dark variants in the frontmatter with a 56px minimum height, 28px content gap, and 15px semibold type. Hover changes color over .18s. Execution and copy controls are smaller forest-filled controls with a 44px minimum height. Disabled execution dims to .72 opacity and uses a wait cursor. Keyboard focus uses a 3px focus-color outline offset by 5px.

### Inputs / Fields

Native selects sit on the paper surface with transparent backgrounds, square edges, and a bottom rule. Route values are 29px semibold; date and time are 14px. Labels remain above fields. Running the demonstration disables its controls; equal departure and destination reveal adjacent error text and focus the destination. No independent text-input component ships.

### Navigation

The desktop wordmark, four text links, and underlined action share one row. Hover and the current-page state underline links. On mobile the links stay visible on their own row. Reading pages use a sticky contents list on desktop and a wrapped inline list on mobile. The skip link becomes visible on focus.

### Tags / Containers

The outlined demonstration tag conveys status rather than acting as a filter. Supporting callouts and code panels use sage surfaces without shadows. Evidence images use pale framing and captions; they remain source material, not decorative card covers.

### Itinerary Foldout

A lime heading leads into editable conditions, a generated request, a full-width play control, numbered steps, and a ruled result table. Active and completed steps fill forest; numeric cells use tabular figures. Condition changes clear previous results. Completion reveals the table with a .55s cubic-bezier(.16,1,.3,1) clip-path unfold; the demonstration advances in 420ms steps. Reduced motion removes CSS transitions and animation and reduces step delays to 30ms. Status and non-live disclosures remain visible.

### Recording Selection

The recording panel uses a lime toolbar over a bordered, flat paper surface. Marking results changes a thin outline into a two-pixel forest outline with a pale green fill; a check icon and text confirm selection. The outlined marking button toggles its pressed state, and the forest completion button stays disabled until selection. Completion reveals the next steps and moves focus to reset; reset restores the initial state. Its purpose is explicitly a marking demonstration, not a live recorder. The panel uses 22px content padding, reducing to 18px on mobile, and its actions wrap.

### Acceleration Explanation

A dark forest band uses pale reading text and lime section emphasis. Fine rules separate the ordinary browsing explanation, the three-step saved-flow sequence, and its qualification. Numbered steps remain open columns rather than cards, stacking on mobile. This is an explanatory layout; it introduces no new animation or elevation treatment.

### Reading Components

Code blocks wrap long lines; copy feedback uses an adjacent status region. Comparison tables use sage header cells and ruled rows. Native details elements use ruled boundaries, clear summary text, and visible keyboard focus.

## Do's and Don'ts

### Do:
- Do preserve the forest, lime, and paper role relationships.
- Do keep form labels, result captions, and evidence limitations visible beside the material they explain.
- Do stack paired content and move the table of contents into normal flow on narrow screens.
- Do preserve keyboard focus outlines and the reduced-motion behavior.

### Don't:
- Don't make every content group inherit the foldout shadow or rotation.
- Don't style demonstration results so that their non-live status disappears.
- Don't replace aligned result tables with decorative cards that obscure field relationships.
