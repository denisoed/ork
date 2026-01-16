import os
import time
import hashlib
from typing import Optional, Any, Dict
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from orchestrator.state import SharedState, Task, add_evidence
from orchestrator.tools.fs_tools import read_file, write_file, list_files, WORKSPACE_DIR
from orchestrator.tools.shell_tools import run_shell_command
from orchestrator.tools.deploy_tools import (
    deploy_supabase_migration,
    deploy_supabase_function,
    deploy_to_vercel,
    link_vercel_project,
    link_supabase_project,
    init_supabase_project,
    get_deployment_status
)

# Configuration
MODEL_NAME = "gemini-2.5-flash-lite"

def _ensure_api_configured() -> bool:
    """Ensures API is configured. Returns True if successful."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY environment variable is not set. "
            "Please set it in your .env file or environment."
        )
    genai.configure(api_key=api_key)
    return True

def _call_api_with_retry(chat, prompt: str, max_retries: int = 3) -> Optional[Any]:
    """Calls API with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            response = chat.send_message(prompt)
            return response
        except google_exceptions.ResourceExhausted as e:
            wait_time = 2 ** attempt
            print(f"Rate limit hit. Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        except google_exceptions.ServiceUnavailable as e:
            wait_time = 2 ** attempt
            print(f"Service unavailable. Retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait_time)
        except Exception as e:
            print(f"API Error: {e}")
            raise
    raise Exception(f"API call failed after {max_retries} retries")

def _get_file_hash(filepath: str) -> str:
    """Returns MD5 hash of file content."""
    try:
        full_path = os.path.join(WORKSPACE_DIR, filepath.lstrip('/'))
        if os.path.exists(full_path):
            with open(full_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
    except Exception:
        pass
    return ""

def _scan_workspace_files() -> Dict[str, str]:
    """Scans workspace and returns file hashes."""
    snapshot = {}
    if os.path.exists(WORKSPACE_DIR):
        for root, _, files in os.walk(WORKSPACE_DIR):
            for filename in files:
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, WORKSPACE_DIR)
                snapshot[rel_path] = _get_file_hash(rel_path)
    return snapshot

WORKER_PROMPT_TEMPLATE = """
Role: {role}
Goal: Execute the assigned task with precision.

Task ID: {task_id}
Task: {description}
Feedback from previous attempt (if any): {feedback}

Current Files in Workspace:
{files_list}

Tools Available:
- read_file(path): Read content of a file
- write_file(path, content): Write content to a file
- list_files(path): List files in a directory
- run_shell_command(command): Execute shell commands (npm, git, etc.)

Instructions:
1. Understand the goal.
2. Use tools to inspect existing files if needed.
3. Write/Modify code to fulfill the task.
4. Use run_shell_command for npm install, build commands, etc.
5. Output a brief summary of what you did.
6. Ensure code is complete and functional.
"""

DEPLOY_AGENT_PROMPT = """
Role: Deployment Specialist
Goal: Deploy applications and services to production platforms (Vercel, Supabase).

Task ID: {task_id}
Task: {description}
Feedback from previous attempt (if any): {feedback}

Current Files in Workspace:
{files_list}

Deployment Status:
{deployment_status}

Tools Available:
- deploy_to_vercel(project_dir, production): Deploy to Vercel. 
  * production=False for preview (default), production=True for production.
  * Returns: {{"success": bool, "deployment_url": str, "preview_url": str}}

- deploy_supabase_migration(migration_file): Deploy SQL migrations to Supabase.
  * Returns: {{"success": bool, "migration_id": str, "project_url": str}}

- deploy_supabase_function(function_name, function_dir): Deploy Edge Function to Supabase.
  * Returns: {{"success": bool, "function_url": str}}

- link_vercel_project(project_name): Link workspace to Vercel project.
- link_supabase_project(project_ref): Link workspace to Supabase project.
- init_supabase_project(): Initialize Supabase in workspace.
- get_deployment_status(): Check deployment credentials and status.

- read_file(path): Read content of a file
- write_file(path, content): Write content to a file  
- list_files(path): List files in a directory
- run_shell_command(command): Execute shell commands

Instructions:
1. First, check deployment status with get_deployment_status() if needed.
2. For Vercel deployment:
   - Use deploy_to_vercel(project_dir=".", production=False) for PREVIEW deployment.
   - Only use production=True if explicitly requested.
   - The returned "deployment_url" or "preview_url" is the live URL.
3. For Supabase migrations:
   - Use deploy_supabase_migration() to push database changes.
4. For Supabase Edge Functions:
   - Use deploy_supabase_function(function_name, function_dir).
5. Output the deployment URLs clearly in your response.
6. If deployment fails, report the error details.

CRITICAL: Always report the deployment URL in your output for the validator to extract.
"""

# Store current task ID for validator to use
_current_task_id: Dict[str, str] = {}

def get_current_task_id(role: str) -> Optional[str]:
    """Returns the current task ID being processed by a role."""
    return _current_task_id.get(role)

def worker_node(state: SharedState, role: str) -> SharedState:
    """
    Generic worker node. 
    Finds the pending task for 'role', executes it.
    """
    global _current_task_id
    
    tasks = state.get('tasks_queue', [])
    
    # Find a running task for this role first (parallel dispatch)
    target_task = None
    running_tasks = [t for t in tasks if t['status'] == 'running']

    if running_tasks:
        for t in tasks:
            if t['assigned_role'] == role and t['status'] == 'running':
                target_task = t
                break
    else:
        # Fallback to pending tasks if no running tasks exist
        completed_ids = {t['id'] for t in tasks if t['status'] == 'completed'}
        for t in tasks:
            if t['assigned_role'] == role and t['status'] == 'pending':
                if all(d in completed_ids for d in t['dependencies']):
                    target_task = t
                    break
    
    if not target_task:
        return {}

    # Store current task ID for validator
    _current_task_id[role] = target_task['id']
    print(f"[{role}] Starting task: {target_task['id']} - {target_task['description']}")

    # Ensure API is configured
    try:
        _ensure_api_configured()
    except ValueError as e:
        target_task['feedback'] = str(e)
        return {
            "error_logs": [{"node": f"worker_{role}", "task_id": target_task['id'], "error": str(e)}],
            "tasks_queue": [target_task]
        }

    # Get current files list
    files_snapshot = state.get('files_snapshot', {})
    if not files_snapshot:
        files_snapshot = _scan_workspace_files()
    
    files_list = "\n".join(f"- {f}" for f in files_snapshot.keys()) if files_snapshot else "No files yet"

    # Select prompt and tools based on role
    if role == "deploy_agent":
        # Get deployment status for context
        deploy_status = get_deployment_status()
        deployment_status_str = (
            f"Supabase: {'Ready' if deploy_status['supabase']['ready'] else 'Missing: ' + ', '.join(deploy_status['supabase']['missing'])}\n"
            f"Vercel: {'Ready' if deploy_status['vercel']['ready'] else 'Missing: ' + ', '.join(deploy_status['vercel']['missing'])}"
        )
        
        prompt = DEPLOY_AGENT_PROMPT.format(
            task_id=target_task['id'],
            description=target_task['description'],
            feedback=target_task.get('feedback', 'None'),
            files_list=files_list,
            deployment_status=deployment_status_str
        )
        
        # Deploy agent has access to all deployment tools
        tools = [
            read_file, 
            write_file, 
            list_files, 
            run_shell_command,
            deploy_supabase_migration,
            deploy_supabase_function,
            deploy_to_vercel,
            link_vercel_project,
            link_supabase_project,
            init_supabase_project,
            get_deployment_status
        ]
    else:
        # Standard worker prompt with shell access
        prompt = WORKER_PROMPT_TEMPLATE.format(
            role=role,
            task_id=target_task['id'],
            description=target_task['description'],
            feedback=target_task.get('feedback', 'None'),
            files_list=files_list
        )
        
        # Standard tools including shell command
        tools = [read_file, write_file, list_files, run_shell_command]
    
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        tools=tools
    )
    chat = model.start_chat(enable_automatic_function_calling=True)
    
    try:
        response = _call_api_with_retry(chat, prompt)
        result_text = response.text
        
        # Update files snapshot after work is done
        new_snapshot = _scan_workspace_files()
        
        # Extract usage
        usage = response.usage_metadata
        token_update = {
            "input_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
        
        print(f"[{role}] Completed task: {target_task['id']}")
        
        # Add evidence for this task
        evidence_list = state.get('evidence', []).copy()
        add_evidence(
            evidence_list,
            evidence_type="task_execution",
            requirement_id=target_task.get('id'),
            command=None,  # Could extract from result_text if needed
            output_path=None,
            status="pending"  # Will be validated by validator
        )
        
        return {
            "messages": [f"Worker {role} finished task {target_task['id']}: {result_text}"],
            "token_usage": token_update,
            "files_snapshot": new_snapshot,
            "evidence": evidence_list
        }
        
    except Exception as e:
        print(f"[{role}] Error in task {target_task['id']}: {e}")
        # Update task with error feedback for retry
        target_task['feedback'] = str(e)
        return {
            "error_logs": [{"node": f"worker_{role}", "task_id": target_task['id'], "error": str(e)}],
            "tasks_queue": [target_task]
        }
