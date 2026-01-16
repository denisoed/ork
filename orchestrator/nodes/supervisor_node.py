import json
import os
import time
from typing import List, Dict, Any, Optional
from orchestrator.state import SharedState, Task, can_enter_node, is_valid_transition
from orchestrator.utils.caching import get_cached_content
from orchestrator.tools.spec_feature_tools import (
    read_spec_file,
    read_all_constitution_files,
)
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

# Configuration
MODEL_NAME = "gemini-2.5-flash-lite"
MAX_RECURSION_DEPTH = int(os.getenv("MAX_RECURSION_DEPTH", "100"))

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

SUPERVISOR_PROMPT = """
Role: System Architect & Orchestrator
Goal: Break down complex development requests into atomic, dependency-aware tasks.

Context: You are managing a team of specialized coders (UI, DB, Logic, Deploy). 
You have access to the file system snapshot.

Instructions:
1. Review the User Request and current State.
2. Create or Update the JSON plan of tasks.
3. Assign tasks to the most suitable agent:
   - ui_agent: React, Tailwind, Components, Pages, Next.js setup, frontend code.
   - db_agent: Supabase, SQL, Schema, RLS policies, Migrations creation.
   - logic_agent: TypeScript functions, API routes, integrations, utility logic, Edge Functions code.
   - deploy_agent: Deployment tasks (Vercel preview/production, Supabase migrations deploy, Supabase functions deploy).

4. DEPLOYMENT RULES (CRITICAL):
   - If the user request contains "--auto-deploy" OR explicitly asks to "deploy", you MUST create deployment tasks.
   - By DEFAULT, create a Vercel PREVIEW deployment (not production).
   - Only create production deployment if user explicitly specifies "--prod" or "production".
   - For Supabase: ALWAYS deploy migrations if db_agent created any SQL/migration files.
   - For Supabase: Deploy Edge Functions if logic_agent created any edge functions.
   - Deployment tasks MUST have dependencies on the tasks that create the files to deploy:
     * Vercel deploy depends on ALL ui_agent and logic_agent tasks
     * Supabase migration deploy depends on db_agent migration tasks
     * Supabase function deploy depends on logic_agent edge function tasks
   - The FINAL task should be "Deploy to Vercel (preview)" for easy access to the preview URL.

5. Ensure tasks are granular and atomic.
6. Return ONLY valid JSON in the following format:
{
  "tasks": [
    {
      "id": "task_1",
      "description": "Create Next.js project structure with Tailwind CSS",
      "assigned_role": "ui_agent",
      "dependencies": []
    },
    {
      "id": "task_2",
      "description": "Create Supabase schema for contact form submissions",
      "assigned_role": "db_agent",
      "dependencies": []
    },
    {
      "id": "task_3",
      "description": "Create API route for form submission",
      "assigned_role": "logic_agent",
      "dependencies": ["task_1"]
    },
    {
      "id": "task_4",
      "description": "Deploy Supabase migrations",
      "assigned_role": "deploy_agent",
      "dependencies": ["task_2"]
    },
    {
      "id": "task_5",
      "description": "Deploy to Vercel (preview)",
      "assigned_role": "deploy_agent",
      "dependencies": ["task_1", "task_3"]
    }
  ]
}
If the plan is already complete/empty or no changes needed, return {"tasks": []}.
"""

def _get_last_user_message(messages: List[Any]) -> str:
    """Return the most recent user message content."""
    for msg in reversed(messages or []):
        if hasattr(msg, "type") and getattr(msg, "type") == "human":
            return str(getattr(msg, "content", ""))
        if isinstance(msg, dict) and msg.get("role") == "user":
            return str(msg.get("content", ""))
    if messages:
        last = messages[-1]
        return str(getattr(last, "content", last))
    return ""

def _call_api_with_retry(model, prompt: str, max_retries: int = 3) -> Optional[Any]:
    """Calls API with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
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

def supervisor_node(state: SharedState) -> SharedState:
    """
    The Supervisor Node responsible for planning and decomposition.
    """
    from orchestrator.state import can_enter_node
    
    # Ensure API is configured
    _ensure_api_configured()
    
    # Check if we can enter this node from current phase
    current_phase = state.get('phase', 'INTAKE')
    if not can_enter_node("supervisor", current_phase):
        return {
            "error_logs": [{"node": "supervisor", "error": f"Cannot enter supervisor from phase {current_phase}"}],
            "phase": "FAILED"
        }
    
    # Check if all tasks are already completed - no need to replan
    existing_tasks = state.get('tasks_queue', [])
    if existing_tasks:
        running_tasks = [t for t in existing_tasks if t['status'] == 'running']
        if running_tasks:
            # Tasks are running - set phase to EXECUTING if not already
            if current_phase == "EXEC_PLANNED":
                return {"phase": "EXECUTING"}
            return {}

        pending_tasks = [t for t in existing_tasks if t['status'] == 'pending']
        failed_tasks = [t for t in existing_tasks if t['status'] == 'failed']
        
        # If there are pending tasks, don't regenerate the plan
        if pending_tasks and not failed_tasks:
            # Set phase to EXECUTING if tasks are pending
            if current_phase in ["EXEC_PLANNED", "IMPL_REVIEW"]:
                return {"phase": "EXECUTING"}
            return {}
        
        # If all tasks are completed, set phase appropriately
        if all(t['status'] == 'completed' for t in existing_tasks):
            # All tasks done - should go to final validator
            if current_phase == "EXECUTING":
                return {"phase": "EXECUTING"}  # Will transition to VALIDATING via router
            return {}
    
    user_msg = _get_last_user_message(state.get('messages', []))
    if not user_msg:
        return {"error_logs": [{"node": "supervisor", "error": "No user message found in state."}]}
    
    # Read spec-feature specifications if available
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    spec_context = ""
    
    if feature_name:
        try:
            spec_content = read_spec_file(feature_name, 'spec', spec_path)
            plan_content = read_spec_file(feature_name, 'plan', spec_path)
            tasks_content = read_spec_file(feature_name, 'tasks', spec_path)
            constitution_content = read_all_constitution_files(spec_path)
            
            if spec_content and plan_content and tasks_content:
                spec_context = f"""
SPEC-FEATURE SPECIFICATIONS:

=== Specification (spec.md) ===
{spec_content[:3000]}

=== Implementation Plan (plan.md) ===
{plan_content[:3000]}

=== Tasks (tasks.md) ===
{tasks_content[:3000]}

=== Constitution (project rules) ===
{constitution_content[:2000]}

INSTRUCTIONS: Use tasks.md as the primary source for creating tasks. Convert tasks from tasks.md into the JSON format required. Ensure all tasks from tasks.md are included.
"""
                
                # Extract acceptance criteria from spec/tasks
                # Simple heuristic: extract checkboxes or numbered criteria from spec/tasks
                acceptance_criteria = []
                # Look for acceptance criteria in spec.md (common patterns)
                lines = spec_content.split('\n')
                in_criteria_section = False
                for line in lines:
                    if 'acceptance' in line.lower() and 'criteri' in line.lower():
                        in_criteria_section = True
                        continue
                    if in_criteria_section:
                        if line.strip().startswith('-') or line.strip().startswith('*') or line.strip().startswith('1.') or line.strip().startswith('*'):
                            criterion = line.strip().lstrip('-*123456789. ').strip()
                            if criterion and len(criterion) > 10:  # Filter out short/simple markers
                                acceptance_criteria.append(criterion)
                        elif line.strip() and not line.strip().startswith('#'):
                            in_criteria_section = False
                
                # If no criteria found, create a default one
                if not acceptance_criteria:
                    acceptance_criteria = [
                        f"All tasks from tasks.md are completed",
                        f"Implementation matches spec.md requirements",
                        f"Implementation follows plan.md architecture"
                    ]
        except Exception as e:
            print(f"Warning: Could not read spec-feature files: {e}")
            acceptance_criteria = []
    
    # Build context with existing task statuses
    task_context = ""
    if existing_tasks:
        task_context = "\nCurrent Tasks Status:\n"
        for t in existing_tasks:
            task_context += f"- {t['id']}: {t['description']} [{t['status']}]\n"
    
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=SUPERVISOR_PROMPT
    )
    
    prompt = (
        f"User Request: {user_msg}\n"
        f"{spec_context}"
        f"Current Files: {str(state.get('files_snapshot', {}))}"
        f"{task_context}"
    )
    
    try:
        response = _call_api_with_retry(model, prompt)
        
        # Extract JSON
        text = response.text
        # Clean up JSON from markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
            
        plan = json.loads(text.strip())
        
        new_tasks = []
        for t in plan.get("tasks", []):
            task_id = t["id"]
            
            # Skip tasks that already exist and are completed
            existing_task = next((et for et in existing_tasks if et['id'] == task_id), None)
            if existing_task and existing_task['status'] == 'completed':
                continue
                
            new_task: Task = {
                "id": task_id,
                "description": t["description"],
                "assigned_role": t["assigned_role"],
                "status": "pending",
                "dependencies": t.get("dependencies", []),
                "retry_count": existing_task['retry_count'] if existing_task else 0,
                "feedback": existing_task.get('feedback') if existing_task else None
            }
            new_tasks.append(new_task)
            
        # Extract usage
        usage = response.usage_metadata
        token_update = {
            "input_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
            
        # Determine phase: if this is the first planning (no existing tasks), set EXEC_PLANNED
        # Otherwise, if we're planning, we're in EXEC_PLANNED -> EXECUTING transition
        update_state: Dict[str, Any] = {
            "tasks_queue": new_tasks,
            "token_usage": token_update
        }
        
        # Set phase based on whether this is initial planning or replanning
        if not existing_tasks and new_tasks:
            # First planning - set EXEC_PLANNED
            if is_valid_transition(current_phase, "EXEC_PLANNED"):
                update_state["phase"] = "EXEC_PLANNED"
            else:
                update_state["phase"] = current_phase
        elif new_tasks:
            # Replanning - ensure we're in EXECUTING phase
            if is_valid_transition(current_phase, "EXECUTING"):
                update_state["phase"] = "EXECUTING"
        
        # Set acceptance criteria if extracted
        if 'acceptance_criteria' in locals() and acceptance_criteria:
            update_state["acceptance_criteria"] = acceptance_criteria
        
        # Return only new/updated tasks - the reducer will merge them
        return update_state
        
    except json.JSONDecodeError as e:
        print(f"Supervisor JSON Parse Error: {e}")
        return {"error_logs": [{"node": "supervisor", "error": f"Invalid JSON response: {e}"}]}
    except ValueError as e:
        print(f"Supervisor Config Error: {e}")
        return {"error_logs": [{"node": "supervisor", "error": str(e)}]}
    except Exception as e:
        print(f"Supervisor Error: {e}")
        return {"error_logs": [{"node": "supervisor", "error": str(e)}]}

def supervisor_router(state: SharedState) -> str:
    """
    Determines the next step: which worker to run.
    Returns a single role string for the conditional edge.
    Checks phase before allowing transitions.
    """
    from orchestrator.state import can_enter_node, is_valid_transition, has_open_questions
    
    # Check phase
    current_phase = state.get('phase', 'INTAKE')
    
    # Check if we can enter this node from current phase
    if not can_enter_node("supervisor", current_phase):
        print(f"[Supervisor Router] Illegal transition from phase {current_phase} to supervisor")
        return "__end__"
    
    # Additional check: block development if there are open questions
    if current_phase in ["EXEC_PLANNED", "EXECUTING", "IMPL_REVIEW"]:
        if has_open_questions(state):
            open_questions = state.get('open_questions', [])
            open_count = len([q for q in open_questions if q.get("status") == "open"])
            print(f"[Supervisor Router] BLOCKED: Cannot proceed to development with {open_count} open question(s)")
            return "__end__"  # BLOCKED - cannot proceed with open questions
    
    # Check recursion limit
    if state.get('recursion_depth', 0) >= MAX_RECURSION_DEPTH:
        print(f"Recursion limit reached ({MAX_RECURSION_DEPTH}). Ending execution.")
        return "__end__"
    
    tasks = state.get('tasks_queue', [])
    
    if not tasks:
        return "__end__"
    
    # Categorize tasks by status
    running_tasks = [t for t in tasks if t['status'] == 'running']
    pending_tasks = [t for t in tasks if t['status'] == 'pending']
    completed_tasks = [t for t in tasks if t['status'] == 'completed']
    failed_tasks = [t for t in tasks if t['status'] == 'failed']
    
    completed_ids = {t['id'] for t in completed_tasks}
    failed_ids = {t['id'] for t in failed_tasks}
    
    # Check for failed tasks that exceeded retry limit (critical failures)
    critical_failures = [t for t in failed_tasks if t['retry_count'] >= 3]
    if critical_failures:
        print(f"[Supervisor Router] Critical failures detected: {[t['id'] for t in critical_failures]}")
        return "human_intervention"
    
    # Find ready tasks (pending tasks with dependencies met) - check this FIRST
    ready_tasks = []
    for t in pending_tasks:
        # Check if all dependencies are completed
        deps_met = all(d in completed_ids for d in t['dependencies'])
        # Check if any dependency failed
        deps_failed = any(d in failed_ids for d in t['dependencies'])
        
        if deps_failed:
            # Task depends on failed task - skip it for now
            continue
            
        if deps_met:
            ready_tasks.append(t)
    
    # If we have ready tasks, route to dispatcher (highest priority)
    if ready_tasks:
        # Check phase before going to dispatcher
        if not can_enter_node("dispatcher", current_phase):
            print(f"[Supervisor Router] Cannot transition to dispatcher from phase {current_phase}")
            return "__end__"
        
        print(f"[Supervisor Router] Routing to dispatcher for {len(ready_tasks)} ready tasks")
        return "dispatcher"
    
    # No ready tasks - check states in priority order:
    
    # STATE 1: has_pending_or_running → wait/no-op (loop back to supervisor)
    # This prevents premature transition to final_validator when tasks are still in progress
    if running_tasks:
        print(f"[Supervisor Router] Waiting: {len(running_tasks)} running task(s). Looping back to supervisor.")
        return "supervisor"
    
    if pending_tasks:
        # Some pending tasks but none are ready (dependencies not met or circular dependency)
        print(f"[Supervisor Router] Waiting: {len(pending_tasks)} pending task(s) but none ready. Looping back to supervisor.")
        return "supervisor"
    
    # STATE 2: any_failed (non-critical) → generate corrective tasks + back to EXECUTING
    non_critical_failed = [t for t in failed_tasks if t['retry_count'] < 3]
    if non_critical_failed:
        print(f"[Supervisor Router] {len(non_critical_failed)} non-critical failed task(s) detected. Routing to supervisor for corrective tasks generation.")
        return "supervisor"
    
    # STATE 3: all_completed → transition to IMPL_REVIEW/VALIDATING
    # Only proceed if ALL tasks are completed (no running, pending, or failed)
    if all(t['status'] == 'completed' for t in tasks):
        print("[Supervisor Router] All tasks completed successfully. Proceeding to final validation.")
        # Check phase before going to final_validator
        if current_phase == "EXECUTING" and is_valid_transition("EXECUTING", "VALIDATING"):
            return "__end__"  # This will route to final_validator in main.py
        elif current_phase == "IMPL_REVIEW" and is_valid_transition("IMPL_REVIEW", "VALIDATING"):
            return "__end__"
        elif current_phase not in ["EXECUTING", "IMPL_REVIEW"]:
            print(f"[Supervisor Router] Cannot transition to final_validator from phase {current_phase}")
            return "__end__"
    
    # Fallback: no tasks to process or unexpected state
    print(f"[Supervisor Router] Unexpected state: no ready tasks, no running/pending, no failed, not all completed. Ending.")
    return "__end__"
