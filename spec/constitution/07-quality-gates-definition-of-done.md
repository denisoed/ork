# Quality gates and Definition of Done

## Rules

- MUST define "done" as meeting the criteria in `tasks.md` Definition of Done.
- MUST NOT mark tasks as complete without running the required checks (tests, linters, manual scenarios) stated in the task.
- MUST record verification output under `spec/features/{FEATURE}/verify-report.md` when the workflow requires it.
- **MANDATORY:** MUST have `spec/features/{FEATURE}/trace.json` with requirement traceability: all requirements from `spec.md` must be present, and all requirements must have status `pass` or `fail` (no `unknown` statuses).
- **BLOCKING RULE:** Feature cannot be marked as DONE if any requirement in `trace.json` has status `unknown`. This is verified during `verify.md` execution and must block archiving decision.
- SHOULD prefer automated checks and keep manual steps explicit and repeatable.

## How to verify

- Completed checkboxes have corresponding evidence (test output, report, or documented manual steps).
- Verification report exists when required and reflects the real state.
- Requirement traceability is verified: `trace.json` exists, all requirement IDs from `spec.md` are present, and all requirements have status `pass` or `fail` (verified during `verify.md` execution).

## Exceptions

- If checks cannot run (environment limits), MUST document the reason and the alternative evidence required.


