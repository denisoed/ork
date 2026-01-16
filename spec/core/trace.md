<!-- spec-feature: requirement traceability -->

Template helps create and maintain requirement traceability artifact (`trace.json`) for a feature in the **spec-feature** process.

**Parameters**

- **FEATURE** — name of the folder where the traceability artifact will be saved. Taken from the value between the first two `#` symbols (e.g., `#payments#` → `payments`).
- **CONTEXT** — main context for creating the traceability artifact. Consider everything after the second `#` in the parameter line; context can span multiple lines.

**General rules**

- Before doing anything, read and follow `spec/constitution/*`.
- Work only with specification files within `/spec` directory: automatically create necessary directories and files.
- Do not generate application code, configuration snippets, scripts, or patches while preparing the traceability artifact.
- **MANDATORY:** Create `spec/features/{FEATURE}/trace.json` file with traceability information for all requirements from `spec.md`.
- Each requirement with ID (REQ-001, REQ-002, etc.) from `spec/features/{FEATURE}/spec.md` must have a corresponding entry in `trace.json`.
- Update `trace.json` throughout the implementation process as requirements are implemented, verified, and evidence is collected.
- Initial `trace.json` should be created after `spec.md` is completed, with all requirements listed and status set to `unknown` until implementation and verification.

**What needs to be included in trace.json**

- Array of traceability records, one per requirement
- Each record must contain:
  - `req_id`: requirement identifier (REQ-001, REQ-002, etc.) matching the ID from `spec.md`
  - `implementation`: array of file paths/modules implementing this requirement (empty array if not yet implemented)
  - `verification`: description of test/command/scenario used to verify this requirement (empty string if not yet verified)
  - `evidence`: path to log/output/proof demonstrating verification (empty string if no evidence available)
  - `status`: one of `pass`, `fail`, or `unknown`

**Steps**

1. Extract all requirement IDs (REQ-XXX) from `spec/features/{FEATURE}/spec.md`.
2. Create `spec/features/{FEATURE}/trace.json` with initial structure:
   - One entry per requirement ID found in `spec.md`
   - All entries start with `status: "unknown"`
   - `implementation`, `verification`, and `evidence` fields start empty
3. Update `trace.json` during implementation:
   - Set `implementation` when code implementing the requirement is written
   - Set `verification` and `evidence` when requirement is tested/verified
   - Update `status` to `pass` or `fail` based on verification results
4. Ensure `trace.json` is valid JSON and all requirement IDs from `spec.md` are present.

**trace.json structure template**

```json
[
  {
    "req_id": "REQ-001",
    "implementation": ["src/feature/api.py", "src/feature/models.py"],
    "verification": "pytest tests/test_feature.py::test_req_001",
    "evidence": "tests/output/test_req_001.log",
    "status": "pass"
  },
  {
    "req_id": "REQ-002",
    "implementation": [],
    "verification": "",
    "evidence": "",
    "status": "unknown"
  }
]
```

**Field descriptions**

- **req_id** (string, required): Unique requirement identifier in format REQ-XXX (REQ-001, REQ-002, etc.). Must match exactly the ID used in `spec.md`.
- **implementation** (array of strings, required): List of file paths, module names, or other identifiers pointing to code/files implementing this requirement. Use relative paths from repository root. Empty array `[]` if requirement is not yet implemented.
- **verification** (string, required): Description of how this requirement is verified. Can be a test command (e.g., `pytest tests/test_feature.py::test_req_001`), manual test scenario, or other verification method. Empty string `""` if requirement is not yet verified.
- **evidence** (string, required): Path to proof/evidence demonstrating that verification was performed and passed/failed. Can be test output log, screenshot, manual test record, or other artifact. Use relative path from repository root. Empty string `""` if no evidence is available yet.
- **status** (string, required): Current verification status. Must be one of:
  - `"unknown"`: requirement not yet verified (default for newly created entries)
  - `"pass"`: requirement verified and meets criteria
  - `"fail"`: requirement verified but does not meet criteria or verification failed

**Integration with workflow**

- `trace.json` is created as part of feature specification process (after `spec.md` is completed)
- `trace.json` is updated during implementation as requirements are addressed
- `trace.json` is checked during verification (`verify.md`) to ensure all requirements are traced and no `unknown` statuses remain before marking feature as DONE
- Feature cannot be marked as DONE if any requirement in `trace.json` has `status: "unknown"`

**Quality requirements**

- All requirement IDs from `spec.md` must be present in `trace.json`
- All entries must have valid JSON structure with all required fields
- Status values must be one of the allowed values (`pass`, `fail`, `unknown`)
- File paths in `implementation` and `evidence` should be relative to repository root
- JSON file must be valid and parseable

Write strictly valid JSON and automatically create/update the traceability file. **Goal** — create/update file `/spec/features/{FEATURE}/trace.json` tracking the relationship between requirements, their implementation, verification, and evidence.

