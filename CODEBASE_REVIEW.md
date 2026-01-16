# Codebase Review

Scope: Dockerfile, README, orchestrator/, workspace/, scripts, and requirements.txt.

## Findings

### High
- H1: Path traversal in workspace file tools. `get_safe_path` uses a prefix check, so a path like `../workspace2/...` can escape the workspace. `orchestrator/tools/fs_tools.py:19`, `orchestrator/tools/fs_tools.py:22`.
- H2: Shell execution is effectively unrestricted. `run_shell_command` relies on a blacklist and does not enforce workspace-only paths, so arbitrary commands can run with `shell=True`. This conflicts with the "safe tools" claim. `orchestrator/tools/shell_tools.py:50`, `orchestrator/tools/shell_tools.py:107`.
- H3: Command injection risk in deploy tools. Commands are built via string interpolation while `shell=True` is enabled, so `project_ref`, `function_name`, or `project_name` can inject shell metacharacters. `orchestrator/tools/deploy_tools.py:33`, `orchestrator/tools/deploy_tools.py:196`, `orchestrator/tools/deploy_tools.py:329`.

### Medium
- M1: `.env` is loaded after modules cache `GOOGLE_API_KEY`. Users following the README (not exporting env) will hit missing key errors. `orchestrator/main.py:14`, `orchestrator/nodes/supervisor_node.py:12`, `orchestrator/nodes/worker_node.py:22`.
- M2: Recursion limit is global and incremented per validation, so flows with more than 15 tasks can terminate early. `orchestrator/nodes/supervisor_node.py:221`, `orchestrator/nodes/validator_node.py:346`.
- M3: Supervisor replanning uses the last message regardless of type; worker output can be treated as the user request. `orchestrator/nodes/supervisor_node.py:137`, `orchestrator/nodes/worker_node.py:265`.
- M4: Worker failures during API configuration omit `task_id`, so the validator may not associate the error and could mark the task completed. `orchestrator/nodes/worker_node.py:166`, `orchestrator/nodes/validator_node.py:285`.
- M5: Vercel token is appended to the command line, exposing it in process lists/logs. `orchestrator/tools/deploy_tools.py:256`.

### Low
- L1: `deploy_supabase_migration` ignores the `migration_file` argument, which does not match the docstring. `orchestrator/tools/deploy_tools.py:109`, `orchestrator/tools/deploy_tools.py:137`.
- L2: Deployment URL key name mismatch between comments and implementation (`supabase_functions` vs `supabase_function`). `orchestrator/state.py:98`, `orchestrator/nodes/validator_node.py:151`.
- L3: Supabase schema lacks RLS/policies; if deployed, table access can be overly permissive. `workspace/database/schemas.sql:1`.

## Notes
- Tests were not executed.
