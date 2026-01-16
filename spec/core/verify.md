<!-- spec-feature: task verification -->

Template helps format the results of automatic task execution verification and make a decision about feature archiving in the **spec-feature** process.

**Parameters**

- **FEATURE** — name of the folder where the verification report will be saved. Taken from the value between the first two `#` symbols (e.g., `#payments#` → `payments`).
- **CONTEXT** — main context and verification purpose. Consider everything after the second `#` in the parameter line; context can span multiple lines and include additional clarifications.

**General rules**

- Before doing anything, read and follow `spec/constitution/*`.
- If information is missing, write `No data — needs clarification: <what exactly>` and do not guess.
- Work only with specification files: do not create code and new directories.
- Do not generate application code, configuration snippets, scripts, or patches during verification.
- **REQUIRED:** Always create `spec/features/{FEATURE}/verify-report.md` file as the main output of verification process.
- Use `spec/features/{FEATURE}/spec.md`, `plan.md`, and `tasks.md` as source data for verification.
- Check tasks sequentially: after successful verification, mark the corresponding checkbox in `spec/features/{FEATURE}/tasks.md` as `[x]`; when discrepancies are found, leave `[ ]` and record details in the report file.
- Save discrepancy logs in `spec/features/{FEATURE}/verify-report.md`, adding new entries with timestamps and brief problem descriptions.
- If there are no discrepancies, explicitly add an entry "No discrepancies detected" in the appropriate section.
- Ensure the report is complete and properly formatted.

**What needs to be revealed in the verification document**

- `## Task verification results` — list of verified tasks with final status and links to supporting artifacts/proofs.
- `## Discrepancy log` — brief summary of new entries added to `verify-report.md`, with steps to resolve problems.
- `## Archiving decision` — final status of verify launch: moving feature to `spec/archived/{FEATURE}` or list of actions for re-verification.
- Constitution compliance — verify that `tasks.md` includes the Constitution checkbox, and that its status matches the changes introduced by the feature. If it should be updated but was not, record a discrepancy.

**Steps**

1. **MANDATORY:** Create the verification report file `spec/features/{FEATURE}/verify-report.md` using the template below.
2. Add a comment at the beginning of the result to specify the save path:
   ```md
   <!-- SAVE_AS: spec/features/{FEATURE}/verify-report.md -->
   ```
3. Go through tasks in `spec/features/{FEATURE}/tasks.md` in order and update checkboxes according to actual execution status.
4. Record results in `spec/features/{FEATURE}/verify-report.md` with logs for all tasks (completed and uncompleted).
5. Check that Markdown is formatted correctly and contains no unfilled placeholders.
6. Ensure the report is complete and ready for archiving decision.

**verify-report.md template**

```md
# Verify Report - {FEATURE}

**Date:** YYYY-MM-DD  
**Context:** {CONTEXT}

## Discrepancy log

### YYYY-MM-DD - [General status description]

#### 1. [Problem name]

**Problem:** [Problem description]  
**Status:** [Criticality: critical/not critical/low priority]  
**Action:** [What needs to be done]

#### 2. [Next problem]

...

### YYYY-MM-DD - Positive results

#### Fully implemented components:

- ✅ [Component 1 (file path)]
- ✅ [Component 2 (file path)]
- ❌ [Uncompleted component (reason)]
- ⚠️ [Partially completed component (what remains)]

```

**Log entry structure:**

- **Date and general status** — grouping by verification time
- **Problems** — numbered list with problem indication, criticality status, and required actions
- **Positive results** — list of completed tasks with emoji statuses:
  - ✅ — fully completed
  - ❌ — not completed
  - ⚠️ — partially completed

Write strictly in Markdown and add nothing outside the document. **Goal** — verify all tasks in `spec/features/{FEATURE}/tasks.md`, mark completed ones in the task file, create a detailed report `verify-report.md` with logs of all tasks and their statuses, or recommend moving the feature to `spec/archived/{FEATURE}` if all tasks passed.
