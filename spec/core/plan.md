<!-- spec-feature: implementation plan -->

Template helps format the feature implementation plan in the **spec-feature** process.

**Parameters**

- **FEATURE** — name of the folder where the plan will be saved. Taken from the value between the first two `#` symbols (e.g., `#payments#` → `payments`).
- **CONTEXT** — main context for preparing the plan. Consider everything after the second `#` in the parameter line; context can span multiple lines and include additional clarifications.

**General rules**

- Before doing anything, read and follow `spec/constitution/*`.
- If information is missing:
  - add a clarifying question to `spec/features/{FEATURE}/clarifications.md` (use `spec/core/clarifications.md` as a template),
  - in this document, write `No data — needs clarification (see clarifications.md: #<n>)`,
  - do not guess.
- Work only with specification files within `/spec` directory: automatically create necessary directories and files.
- Do not generate application code, configuration snippets, scripts, or patches while preparing the implementation plan.
- Use `spec/core/spec.md` as the specification source on which the plan is formed.
- Use `spec/features/{FEATURE}/spec.md` and `spec/features/{FEATURE}/clarifications.md` (resolved answers/decisions) as additional context. If files are unavailable, continue working based on **CONTEXT**.
- Substitute specific values instead of placeholders (`{FEATURE}`, `{CONTEXT}`, etc.). If a section is not applicable — explicitly write `Not required — reason: <explanation>`.
- Form meaningful paragraphs or lists: do not leave empty headers, hint comments, and `...` markers.
- Follow basic software development principles: KISS, DRY, and YAGNI, so solutions remain simple, without duplication and unnecessary logic.
- Ensure all sections are complete and properly formatted.

**What needs to be revealed in the plan**

- `## Data sources / schemas` — storage, migrations, indexes, data handling, and external sources.
- `## Contracts and interfaces` — public APIs, events, queues, UI/CLI, error formats, and validation expectations.
- `## Architecture / Components` — services, modules, integrations, constraints, and chosen stack (DB, API, UI, queues, background processes, etc.).
- `## Risks` — potential problems and mitigation methods.
- `## Assumptions` — explicit assumptions and open dependencies. Do not embed clarifying questions here; link to `clarifications.md` if any.

**Steps**

1. Create the directory structure `spec/features/{FEATURE}/` if it doesn't exist.
2. If any clarifying questions are needed, create/update `spec/features/{FEATURE}/clarifications.md` using `spec/core/clarifications.md` and stop if unanswered questions block correct planning.
3. Form the plan according to the sections above, based on **CONTEXT** and available additional context. For each section, fix what exactly needs to be done, not just list components.
4. Create/update the file `spec/features/{FEATURE}/plan.md` with the complete plan content.
5. Check that the document contains no unfilled placeholders and that the output is formatted in valid Markdown.
6. Ensure the document is complete and ready for implementation.

**Result template**

```md
# Implementation Plan

**Plan:** {CONTEXT}

## Data sources / schemas

## Contracts and interfaces

## Architecture / Components

## Risks

## Assumptions

```

Write strictly in Markdown and automatically create/update the plan file. **Goal** — create/update file `/spec/features/{FEATURE}/plan.md` describing HOW we implement the feature based on **CONTEXT**.
