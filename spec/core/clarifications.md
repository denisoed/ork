<!-- spec-feature: clarifications -->

Template collects all clarifying questions for a feature in the **spec-feature** process.

**Parameters**

- **FEATURE** — name of the folder where the clarifications will be saved. Taken from the value between the first two `#` symbols (e.g., `#payments#` → `payments`).
- **CONTEXT** — main context that triggered the questions. Consider everything after the second `#` in the parameter line; context can span multiple lines.

**General rules**

- Before doing anything, read and follow `spec/constitution/*`.
- Work only with specification files within `/spec` directory: automatically create necessary directories and files.
- Do not generate application code, configuration snippets, scripts, or patches while preparing clarifications.
- All clarifying questions MUST be written to `spec/features/{FEATURE}/clarifications.md` (this file) and MUST NOT be embedded in `spec.md`, `plan.md`, `tasks.md`, or chat messages.
- Prefer 1–2 high-impact questions over a long questionnaire; provide options/defaults when possible.
- If the missing information blocks correct planning/specification, create/update this file and stop. Do not proceed to generate/update `spec.md`, `plan.md`, or `tasks.md` until answers are provided.

**Steps**

1. Create the directory structure `spec/features/{FEATURE}/` if it doesn't exist.
2. Create/update the file `spec/features/{FEATURE}/clarifications.md` using the template below:
   - Add new questions at the end.
   - Keep previously answered questions and do not overwrite user answers.
3. Ensure the document is valid Markdown and contains no placeholders.

**Result template**

```md
# Clarifications — {FEATURE}

**Context:** {CONTEXT}

## Open questions

### 1. <question>
- **Options / suggested default:** <options or default>
- **User answer:** <fill in>

## Resolved decisions

### 1. <decision>
- **Rationale:** <why>
- **Source question:** #1
```

Write strictly in Markdown and automatically create/update the clarifications file. **Goal** — create/update file `/spec/features/{FEATURE}/clarifications.md` to capture all clarifying questions and user answers for this feature.
