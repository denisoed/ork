<!-- spec-feature: feature hotfix -->

Template automates feature maintenance after release: records hotfixes and synchronously updates **spec-feature** artifacts (spec, plan, and tasks).

**Parameters**

- **FEATURE** — name of the folder with feature artifacts. Determined by the value between the first two `#` symbols (e.g., `#billing#` → `billing`).
- **CONTEXT** — essence of the hotfix and expected result. This is everything passed after the second `#`; multi-line descriptions with links to incidents or PRs are allowed.

**General rules**

- Before doing anything, read and follow `spec/constitution/*`.
- If information is missing, write `No data — needs clarification: <what exactly>` and do not guess.
- Work only in the `spec/features/{FEATURE}/` directory: allowed to edit `spec.md`, `plan.md`, and `tasks.md`.
- Do not create new files in the feature folder (including `hotfix.md` and verification reports).
- Do not generate application code, configuration snippets, scripts, or patches while documenting the hotfix.
- Preserve the structure of existing documents: do not delete sections, do not leave empty headers and hints from templates.
- All changes should consider requirements from specification and plan, maintaining consistency of terms and references.
- Actual task state must be reflected in `tasks.md`: do not allow desynchronization between checkboxes and actual state.
- Ensure all modified documents are complete and properly formatted.

**Automatic update logic**

- `spec.md` — update sections affected by the hotfix: clarify user scenarios, rules, or non-functional requirements, add new Assumptions when open questions arise.
- `plan.md` — adjust technical solutions: data sources, contracts, architectural constraints, and risks, so the plan reflects the current feature structure.
- `clarifications.md` — if `spec/features/{FEATURE}/clarifications.md` already exists and the hotfix introduces new open questions, append them there (do not overwrite user answers). If it does not exist, record open questions as assumptions in `spec.md` (this template forbids creating new files).
- `tasks.md` —
  - Add new checkboxes for work required by the hotfix, group them in appropriate sections. Names should start with prefix `hotfix_<date>` in `YYYY-MM-DD` format.
  - Update statuses of existing tasks (`[ ]`/`[x]`), considering actual execution and hotfix results.
  - For each task, specify necessary checks: tests, manual scenarios, documentation updates.

**Steps**

1. Read `spec.md`, `plan.md`, and `tasks.md` to understand the current feature state.
2. Form a list of changes that the hotfix should introduce and reflect them in corresponding documents. Maintain unified terms and component references.
3. Update `tasks.md`: add or adjust tasks, set checkboxes based on actual execution, supplement with verification requirements.
4. Ensure all modified documents are complete and ready for implementation.

Write strictly in Markdown. Goal — automatically bring all feature artifacts up to date under the hotfix and synchronize checklists with actual state.
