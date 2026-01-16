import os
import re
from typing import Optional, Tuple, List, Dict
from orchestrator.state import SharedState, add_evidence, update_evidence_status
from orchestrator.tools.shell_tools import run_shell_command
from orchestrator.tools.fs_tools import WORKSPACE_DIR
from orchestrator.nodes.worker_node import get_current_task_id

# Validation patterns for common errors
SYNTAX_ERROR_PATTERNS = [
    r"SyntaxError",
    r"Unexpected token",
    r"Parse error",
    r"IndentationError",
]

# Patterns to extract deployment URLs from worker output
VERCEL_URL_PATTERNS = [
    r'https://[a-zA-Z0-9-]+\.vercel\.app',
    r'https://[a-zA-Z0-9-]+\.[a-zA-Z0-9-]+\.vercel\.app',
    r'deployment_url["\s:]+["\'](https://[^\s"\']+)["\']',
    r'preview_url["\s:]+["\'](https://[^\s"\']+)["\']',
]

SUPABASE_URL_PATTERNS = [
    r'https://[a-zA-Z0-9-]+\.supabase\.co',
    r'project_url["\s:]+["\'](https://[^\s"\']+)["\']',
    r'function_url["\s:]+["\'](https://[^\s"\']+)["\']',
]


def _check_file_exists(filepath: str) -> bool:
    """Check if a file was created in workspace."""
    full_path = os.path.join(WORKSPACE_DIR, filepath.lstrip('/'))
    return os.path.exists(full_path)

def _check_file_not_empty(filepath: str) -> bool:
    """Check if file has content."""
    full_path = os.path.join(WORKSPACE_DIR, filepath.lstrip('/'))
    if os.path.exists(full_path):
        return os.path.getsize(full_path) > 0
    return False

def _validate_syntax(filepath: str) -> Tuple[bool, str]:
    """Basic syntax validation based on file type."""
    full_path = os.path.join(WORKSPACE_DIR, filepath.lstrip('/'))
    
    if not os.path.exists(full_path):
        return True, ""  # File doesn't exist, skip validation
    
    ext = os.path.splitext(filepath)[1].lower()
    
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Python syntax check
        if ext == '.py':
            try:
                compile(content, filepath, 'exec')
                return True, ""
            except SyntaxError as e:
                return False, f"Python syntax error in {filepath}: {e}"
        
        # JavaScript/TypeScript basic checks
        if ext in ['.js', '.jsx', '.ts', '.tsx']:
            # Check for unclosed brackets/braces
            if content.count('{') != content.count('}'):
                return False, f"Mismatched braces in {filepath}"
            if content.count('(') != content.count(')'):
                return False, f"Mismatched parentheses in {filepath}"
            if content.count('[') != content.count(']'):
                return False, f"Mismatched brackets in {filepath}"
        
        # SQL basic checks
        if ext == '.sql':
            # Check for common SQL syntax issues
            if 'CREATE TABLE' in content.upper():
                if content.count('(') != content.count(')'):
                    return False, f"Mismatched parentheses in SQL file {filepath}"
        
        return True, ""
        
    except Exception as e:
        return False, f"Error reading {filepath}: {e}"

def _validate_js_build() -> Tuple[bool, str]:
    """Run npm/node validation if package.json exists."""
    package_json = os.path.join(WORKSPACE_DIR, 'package.json')
    
    if not os.path.exists(package_json):
        return True, ""  # No package.json, skip npm validation
    
    # Try to run syntax check
    result = run_shell_command("npx eslint . --ext .js,.jsx,.ts,.tsx")
    
    if "error" in result.lower() and "command not found" not in result.lower():
        return False, f"ESLint errors: {result[:500]}"
    
    return True, ""

def _get_changed_files(state: SharedState) -> List[str]:
    """Get list of files that were potentially changed."""
    snapshot = state.get('files_snapshot', {})
    return list(snapshot.keys())


def _extract_deployment_urls(messages: List, task_description: str) -> Dict[str, str]:
    """
    Extract deployment URLs from worker messages.
    
    Args:
        messages: List of messages from the state
        task_description: Description of the task to determine URL type
        
    Returns:
        Dict of extracted URLs with keys like 'vercel_preview', 'supabase_project'
    """
    urls = {}
    
    # Convert messages to text for searching
    text_to_search = ""
    for msg in messages:
        if hasattr(msg, 'content'):
            text_to_search += str(msg.content) + "\n"
        else:
            text_to_search += str(msg) + "\n"
    
    # Determine what type of URLs to look for based on task description
    task_lower = task_description.lower()
    
    # Extract Vercel URLs
    if 'vercel' in task_lower or 'deploy' in task_lower:
        for pattern in VERCEL_URL_PATTERNS:
            matches = re.findall(pattern, text_to_search, re.IGNORECASE)
            if matches:
                url = matches[-1] if isinstance(matches[-1], str) else matches[-1][0]
                # Determine if it's preview or production
                if 'prod' in task_lower or 'production' in task_lower:
                    urls['vercel_production'] = url
                else:
                    urls['vercel_preview'] = url
                break
    
    # Extract Supabase URLs
    if 'supabase' in task_lower or 'migration' in task_lower or 'function' in task_lower:
        for pattern in SUPABASE_URL_PATTERNS:
            matches = re.findall(pattern, text_to_search, re.IGNORECASE)
            if matches:
                url = matches[-1] if isinstance(matches[-1], str) else matches[-1][0]
                if 'function' in task_lower:
                    urls['supabase_function'] = url
                else:
                    urls['supabase_project'] = url
                break
    
    return urls


def _validate_deployment(state: SharedState, task: Dict) -> Tuple[bool, List[str], Dict[str, str]]:
    """
    Validate deployment task results.
    
    Args:
        state: Current shared state
        task: The deployment task being validated
        
    Returns:
        Tuple of (success, error_messages, extracted_urls)
    """
    error_messages = []
    extracted_urls = {}
    
    task_description = task.get('description', '').lower()
    messages = state.get('messages', [])
    
    # Get the last few messages (likely from deploy_agent)
    recent_messages = messages[-5:] if len(messages) >= 5 else messages
    
    # Convert to text for analysis
    output_text = ""
    for msg in recent_messages:
        if hasattr(msg, 'content'):
            output_text += str(msg.content) + "\n"
        else:
            output_text += str(msg) + "\n"
    
    # Check for deployment errors in output
    error_indicators = [
        'deployment failed',
        'deploy failed',
        'error deploying',
        'Error:',
        'missing credentials',
        'authentication failed',
        'permission denied',
    ]
    
    has_errors = any(indicator.lower() in output_text.lower() for indicator in error_indicators)
    
    # Check for success indicators
    success_indicators = [
        'deployed successfully',
        'deployment successful',
        'deployment_url',
        'preview_url',
        'vercel.app',
        'supabase.co',
        'success": true',
        '"success": true',
    ]
    
    has_success = any(indicator.lower() in output_text.lower() for indicator in success_indicators)
    
    # Extract URLs from output
    extracted_urls = _extract_deployment_urls(recent_messages, task_description)
    
    # Validate based on deployment type
    if 'vercel' in task_description:
        if not extracted_urls.get('vercel_preview') and not extracted_urls.get('vercel_production'):
            if not has_success:
                error_messages.append("Vercel deployment did not return a deployment URL")
        else:
            print(f"[Validator:deploy_agent] Extracted Vercel URL: {extracted_urls}")
    
    if 'supabase' in task_description:
        if 'migration' in task_description:
            # Migrations don't always return URLs, just check for success
            if has_errors and not has_success:
                error_messages.append("Supabase migration may have failed")
        elif 'function' in task_description:
            if not extracted_urls.get('supabase_function') and not has_success:
                error_messages.append("Supabase function deployment did not return function URL")
    
    # If we found success indicators and no critical errors, consider it passed
    validation_passed = (has_success or bool(extracted_urls)) and not has_errors
    
    if has_errors and not has_success:
        validation_passed = False
        if not error_messages:
            error_messages.append("Deployment reported errors in output")
    
    return validation_passed, error_messages, extracted_urls


def validator_node(state: SharedState, role: str) -> SharedState:
    """
    Validates work done by the worker of the given role.
    Performs actual validation checks based on the task type.
    """
    tasks = state.get('tasks_queue', [])
    
    # Get the task ID from worker
    current_task_id = get_current_task_id(role)
    
    # Find the task that was just worked on
    target_task = None
    completed_ids = {t['id'] for t in tasks if t['status'] == 'completed'}
    running_tasks = [t for t in tasks if t['status'] == 'running']

    # First try to find running task by current_task_id
    if current_task_id:
        for t in tasks:
            if t['id'] == current_task_id and t['status'] == 'running':
                target_task = t
                break
    
    # Fallback: find running task for this role
    if not target_task and running_tasks:
        for t in tasks:
            if t['assigned_role'] == role and t['status'] == 'running':
                target_task = t
                break
    
    # Final fallback: find pending task for this role (sequential mode)
    if not target_task and not running_tasks:
        for t in tasks:
            if t['assigned_role'] == role and t['status'] == 'pending':
                if all(d in completed_ids for d in t['dependencies']):
                    target_task = t
                    break
    
    if not target_task:
        return {}

    print(f"[Validator:{role}] Validating task: {target_task['id']}")
    
    validation_passed = True
    error_messages = []
    deployment_urls = {}
    
    # Check error logs for this task
    error_logs = state.get('error_logs', [])
    task_errors = [e for e in error_logs if e.get('task_id') == target_task['id']]
    if task_errors:
        validation_passed = False
        error_messages.append(f"Worker reported errors: {task_errors[-1].get('error', 'Unknown')}")
    
    # Role-specific validation
    if role == 'deploy_agent':
        # Special validation for deployment tasks
        deploy_passed, deploy_errors, extracted_urls = _validate_deployment(state, target_task)
        
        if not deploy_passed:
            validation_passed = False
            error_messages.extend(deploy_errors)
        
        deployment_urls = extracted_urls
        
    else:
        # Standard validation for other roles
        changed_files = _get_changed_files(state)
        for filepath in changed_files:
            is_valid, error = _validate_syntax(filepath)
            if not is_valid:
                validation_passed = False
                error_messages.append(error)
        
        if role == 'logic_agent':
            # Check Python files syntax
            py_files = [f for f in changed_files if f.endswith('.py')]
            for py_file in py_files:
                is_valid, error = _validate_syntax(py_file)
                if not is_valid:
                    validation_passed = False
                    error_messages.append(error)
        
        elif role == 'ui_agent':
            # Check JS/JSX/TSX files
            js_files = [f for f in changed_files if f.endswith(('.js', '.jsx', '.ts', '.tsx'))]
            for js_file in js_files:
                is_valid, error = _validate_syntax(js_file)
                if not is_valid:
                    validation_passed = False
                    error_messages.append(error)
        
        elif role == 'db_agent':
            # Check SQL files
            sql_files = [f for f in changed_files if f.endswith('.sql')]
            for sql_file in sql_files:
                is_valid, error = _validate_syntax(sql_file)
                if not is_valid:
                    validation_passed = False
                    error_messages.append(error)

    # Get evidence list
    evidence_list = state.get('evidence', []).copy()
    
    # Update task status based on validation
    if validation_passed:
        target_task['status'] = 'completed'
        target_task['feedback'] = "Validation passed"
        print(f"[Validator:{role}] Task {target_task['id']} PASSED validation")
        
        # Add evidence for validation
        add_evidence(
            evidence_list,
            evidence_type="validation_result",
            requirement_id=target_task.get('id'),
            command=None,
            output_path=None,
            status="passed"
        )
        
        # Update evidence for task execution (if exists)
        for ev in evidence_list:
            if ev.get("requirement_id") == target_task['id'] and ev.get("type") == "task_execution":
                update_evidence_status(evidence_list, ev.get("id"), "validated")
                break
        
        result = {
            "tasks_queue": [target_task],
            "recursion_depth": state.get("recursion_depth", 0) + 1,
            "evidence": evidence_list,
            "phase": "IMPL_REVIEW"  # Set phase after validation
        }
        
        # Add deployment URLs if extracted
        if deployment_urls:
            result["deployment_urls"] = deployment_urls
            print(f"[Validator:{role}] Extracted deployment URLs: {deployment_urls}")
        
        return result
    else:
        target_task['retry_count'] += 1
        error_summary = "; ".join(error_messages[:3])  # Limit error message length
        target_task['feedback'] = f"Validation failed (attempt {target_task['retry_count']}): {error_summary}"
        
        print(f"[Validator:{role}] Task {target_task['id']} FAILED validation: {error_summary}")
        
        if target_task['retry_count'] >= 3:
            target_task['status'] = 'failed'
            print(f"[Validator:{role}] Task {target_task['id']} marked as FAILED after 3 attempts")
        else:
            target_task['status'] = 'pending'
             
        # Add evidence for failed validation
        add_evidence(
            evidence_list,
            evidence_type="validation_result",
            requirement_id=target_task.get('id'),
            command=None,
            output_path=None,
            status="failed"
        )
        
        return {
            "tasks_queue": [target_task],
            "recursion_depth": state.get("recursion_depth", 0) + 1,
            "error_logs": [{"node": f"validator_{role}", "task_id": target_task['id'], "errors": error_messages}],
            "evidence": evidence_list
        }
