import os
import json
import time
from typing import List, Dict, Any, Optional, Tuple
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from orchestrator.state import SharedState, Task, can_enter_node, is_valid_transition
from orchestrator.tools.fs_tools import read_file, WORKSPACE_DIR
from orchestrator.tools.spec_feature_tools import (
    read_spec_file,
    read_all_constitution_files,
)
from orchestrator.nodes.worker_node import get_current_task_id

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

# Configure on module load
try:
    _ensure_api_configured()
except ValueError as e:
    print(f"Warning: {e}")

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

def _get_changed_files(state: SharedState) -> List[str]:
    """Get list of files that were potentially changed."""
    snapshot = state.get('files_snapshot', {})
    return list(snapshot.keys())

def _get_file_contents(filepaths: List[str], max_size: int = 5000) -> str:
    """Read contents of changed files for analysis."""
    contents = []
    for filepath in filepaths[:10]:  # Limit to 10 files to avoid token overflow
        try:
            full_path = os.path.join(WORKSPACE_DIR, filepath.lstrip('/'))
            if os.path.exists(full_path) and os.path.isfile(full_path):
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Truncate if too large
                    if len(content) > max_size:
                        content = content[:max_size] + "\n... (truncated)"
                    contents.append(f"=== {filepath} ===\n{content}\n")
        except Exception as e:
            contents.append(f"=== {filepath} ===\nError reading file: {e}\n")
    return "\n".join(contents)

def _create_corrective_tasks(original_task: Task, issues: List[str], role: str) -> List[Task]:
    """Create corrective tasks based on review issues."""
    corrective_tasks = []
    
    for idx, issue in enumerate(issues[:5]):  # Limit to 5 corrective tasks
        task_id = f"corrective_{original_task['id']}_{idx + 1}"
        corrective_task: Task = {
            "id": task_id,
            "description": f"Fix: {issue[:200]}",  # Truncate issue description
            "assigned_role": role,
            "status": "pending",
            "dependencies": [original_task['id']],
            "retry_count": 0,
            "feedback": None
        }
        corrective_tasks.append(corrective_task)
    
    return corrective_tasks

def impl_review_node(state: SharedState, role: str) -> SharedState:
    """
    Implementation Review Node - analyzes changed files for architecture, security, style, and edge cases.
    Performs code review before runtime validation.
    """
    tasks = state.get('tasks_queue', [])
    
    # Get the task ID from worker
    current_task_id = get_current_task_id(role)
    
    # Find the task that was just worked on
    target_task = None
    completed_ids = {t['id'] for t in tasks if t['status'] == 'completed'}
    running_tasks = [t for t in tasks if t['status'] == 'running'] if tasks else []

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
    
    print(f"[Impl Review:{role}] Reviewing task: {target_task['id']}")
    
    _ensure_api_configured()
    
    # Check if we can enter this node from current phase
    current_phase = state.get('phase', 'INTAKE')
    # impl_review nodes can be entered from EXECUTING phase
    if not can_enter_node("impl_review", current_phase):
        return {
            "error_logs": [{"node": f"impl_review_{role}", "error": f"Cannot enter impl_review from phase {current_phase}"}],
            "phase": "FAILED"
        }
    
    # Set phase to IMPL_REVIEW when starting review
    if current_phase != "IMPL_REVIEW":
        print(f"[Impl Review:{role}] Starting review (phase: {current_phase} -> IMPL_REVIEW)")
    
    # Get changed files
    changed_files = _get_changed_files(state)
    
    # Read specification files if available
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    
    plan_content = ""
    constitution_content = ""
    
    if feature_name:
        try:
            plan_content = read_spec_file(feature_name, 'plan', spec_path)
            constitution_content = read_all_constitution_files(spec_path)
        except Exception as e:
            print(f"Warning: Could not read spec files: {e}")
    
    # Read changed files content
    changed_files_content = _get_file_contents(changed_files)
    
    # Build review prompt
    prompt = f"""You are an Implementation Reviewer. Your task is to review code changes for architecture, security, edge cases, and style compliance.

TASK BEING REVIEWED:
- Task ID: {target_task['id']}
- Description: {target_task['description']}
- Role: {role}

CONSTITUTION (project rules - MUST comply):
{constitution_content[:2000] if constitution_content else "No constitution files found"}

IMPLEMENTATION PLAN (plan.md):
{plan_content[:2000] if plan_content else "No plan.md found"}

CHANGED FILES:
{', '.join(changed_files) if changed_files else "No files changed"}

FILE CONTENTS:
{changed_files_content[:8000] if changed_files_content else "No file contents available"}

REVIEW CRITERIA:
1. Architecture: Does the implementation follow plan.md? Are patterns and structures correct?
2. Security: Check for common vulnerabilities:
   - SQL injection risks
   - XSS vulnerabilities
   - Path traversal issues
   - Unsafe command execution
   - Exposed secrets/credentials
   - Missing input validation
3. Edge Cases: Are null checks, error handling, and boundary conditions properly handled?
4. Style & Conventions: Does code follow project conventions from constitution?
   - Code style consistency
   - Naming conventions
   - File structure organization
   - Documentation/comments

Output JSON format:
{{
  "status": "pass" or "issues",
  "issues": ["list of specific issues found, empty if pass"],
  "summary": "brief summary of review"
}}

If status is "pass", proceed to runtime validation.
If status is "issues", provide specific actionable issues that need to be fixed.
"""
    
    # Create model and chat
    model = genai.GenerativeModel(model_name=MODEL_NAME)
    chat = model.start_chat()
    
    try:
        response = _call_api_with_retry(chat, prompt)
        response_text = response.text
        
        # Extract JSON from response
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        review_result = json.loads(response_text.strip())
        
        status = review_result.get("status", "issues")
        issues = review_result.get("issues", [])
        summary = review_result.get("summary", "")
        
        print(f"[Impl Review:{role}] Status: {status}")
        if issues:
            print(f"[Impl Review:{role}] Issues found: {len(issues)}")
            for issue in issues[:3]:  # Show first 3 issues
                print(f"  - {issue[:100]}")
        else:
            print(f"[Impl Review:{role}] Review passed: {summary}")
        
        # Extract usage
        usage = response.usage_metadata
        token_update = {
            "input_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
        
        # Get existing tasks queue
        existing_tasks = state.get('tasks_queue', []).copy()
        
        if status == "pass":
            # Pass - proceed to validation
            # Set phase to VALIDATING (will be handled by validator_node)
            # Mark task as ready for validation (keep status as 'running' for now)
            print(f"[Impl Review:{role}] Review passed. Proceeding to runtime validation.")
            
            return {
                "token_usage": token_update,
                "phase": "VALIDATING"
            }
        else:
            # Issues found - create corrective tasks
            corrective_tasks = _create_corrective_tasks(target_task, issues, role)
            
            # Add corrective tasks to tasks queue
            for corrective_task in corrective_tasks:
                existing_tasks.append(corrective_task)
            
            # Mark original task as pending (needs correction)
            target_task['status'] = 'pending'
            target_task['feedback'] = f"Impl review found {len(issues)} issue(s): {summary[:200]}"
            
            # Update original task in queue
            for idx, t in enumerate(existing_tasks):
                if t['id'] == target_task['id']:
                    existing_tasks[idx] = target_task
                    break
            
            print(f"[Impl Review:{role}] Created {len(corrective_tasks)} corrective task(s). Returning to EXECUTING.")
            
            return {
                "tasks_queue": existing_tasks,
                "token_usage": token_update,
                "phase": "EXECUTING",
                "error_logs": [{
                    "node": f"impl_review_{role}",
                    "task_id": target_task['id'],
                    "errors": issues
                }]
            }
        
    except json.JSONDecodeError as e:
        print(f"[Impl Review:{role}] JSON Parse Error: {e}")
        # On JSON error, proceed to validation (fail-safe)
        return {
            "error_logs": [{"node": f"impl_review_{role}", "error": f"Invalid JSON response: {e}"}],
            "phase": "VALIDATING"
        }
    except Exception as e:
        print(f"[Impl Review:{role}] Error: {e}")
        # On error, proceed to validation (fail-safe)
        return {
            "error_logs": [{"node": f"impl_review_{role}", "error": str(e)}],
            "phase": "VALIDATING"
        }

def impl_review_router(state: SharedState, role: str) -> str:
    """
    Router for impl_review nodes - determines next step based on review result.
    
    Args:
        state: Current shared state
        role: Role that was reviewed (for logging)
        
    Returns:
        Next node name: "supervisor" if issues found (EXECUTING phase),
                       "val_{role}" if review passed (VALIDATING phase)
    """
    current_phase = state.get('phase', 'INTAKE')
    
    # If phase is EXECUTING, it means issues were found and corrective tasks were created
    # Return to supervisor to handle corrective tasks
    if current_phase == "EXECUTING":
        print(f"[Impl Review Router:{role}] Issues found. Returning to supervisor for corrective tasks.")
        return "supervisor"
    
    # If phase is VALIDATING, proceed to validator_node (review passed)
    if current_phase == "VALIDATING":
        # Map role to validator node name
        validator_node_map = {
            "ui_agent": "val_ui",
            "db_agent": "val_db",
            "logic_agent": "val_logic",
            "deploy_agent": "val_deploy"
        }
        validator_node = validator_node_map.get(role, "val_ui")
        print(f"[Impl Review Router:{role}] Review passed. Proceeding to {validator_node}.")
        return validator_node
    
    # Fallback: if phase is IMPL_REVIEW or unclear, default to validator (fail-safe)
    validator_node_map = {
        "ui_agent": "val_ui",
        "db_agent": "val_db",
        "logic_agent": "val_logic",
        "deploy_agent": "val_deploy"
    }
    validator_node = validator_node_map.get(role, "val_ui")
    print(f"[Impl Review Router:{role}] Unexpected phase {current_phase}. Defaulting to {validator_node}.")
    return validator_node

