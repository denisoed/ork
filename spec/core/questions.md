<!-- spec-feature: questions -->

Template collects all blocking questions for a feature in the **spec-feature** process.

**Parameters**

- **FEATURE** — name of the folder where the questions will be saved. Taken from the value between the first two `#` symbols (e.g., `#payments#` → `payments`).
- **CONTEXT** — main context that triggered the questions. Consider everything after the second `#` in the parameter line; context can span multiple lines.

**General rules**

- Before doing anything, read and follow `spec/constitution/*`.
- Work only with specification files within `/spec` directory: automatically create necessary directories and files.
- Do not generate application code, configuration snippets, scripts, or patches while preparing questions.
- All blocking questions MUST be written to `spec/features/{FEATURE}/questions.md` (this file) and MUST NOT be embedded in `spec.md`, `plan.md`, `tasks.md`, or chat messages.
- Each question must clearly indicate which parts of the spec depend on the answer (Dependencies field).
- Questions are blocking: if information is missing, create/update this file and stop. Do not proceed to generate/update `spec.md`, `plan.md`, or `tasks.md` until answers are provided.

**Steps**

1. Create the directory structure `spec/features/{FEATURE}/` if it doesn't exist.
2. Create/update the file `spec/features/{FEATURE}/questions.md` using the template below:
   - Add new questions at the end.
   - Keep previously answered questions and do not overwrite user answers.
3. Ensure the document is valid Markdown and contains no placeholders.

**Result template**

```md
# Questions — {FEATURE}

**Context:** {CONTEXT}

## Question 1: {текст вопроса}

- **Dependencies**: {какие пункты спеки зависят от ответа, например: "spec.md §3.2, plan.md §2.1"}
- **Options**: {если есть допустимые варианты, перечислите их здесь}
- **Status**: {open|answered}
- **Answer**: {ответ пользователя, заполняется после парсинга}

## Question 2: {текст вопроса}

- **Dependencies**: {какие пункты спеки зависят от ответа}
- **Options**: {если есть допустимые варианты}
- **Status**: {open|answered}
- **Answer**: {ответ пользователя, заполняется после парсинга}
```

Write strictly in Markdown and automatically create/update the questions file. **Goal** — create/update file `/spec/features/{FEATURE}/questions.md` to capture all blocking questions and user answers for this feature.

