"""
Specification Planner Node - creates specifications following spec/feature.md instructions.
"""

import os
import time
import json
from typing import Optional, Any, Dict
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from orchestrator.state import SharedState, add_open_question, all_questions_answered
from orchestrator.tools.spec_feature_tools import (
    read_feature_instructions,
    read_all_constitution_files,
    read_template_file,
    parse_feature_request,
    ensure_feature_directory,
    write_spec_file,
    read_spec_file,
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

def _get_last_user_message(messages) -> str:
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

def spec_planner_node(state: SharedState) -> SharedState:
    """
    Specification Planner Node - creates specifications following spec/feature.md.
    """
    _ensure_api_configured()
    
    # Get user message
    user_msg = _get_last_user_message(state.get('messages', []))
    if not user_msg:
        return {"error_logs": [{"node": "spec_planner", "error": "No user message found in state."}]}
    
    # Parse feature request
    try:
        feature_name, context = parse_feature_request(user_msg)
    except Exception as e:
        return {"error_logs": [{"node": "spec_planner", "error": f"Error parsing feature request: {e}"}]}
    
    print(f"[Spec Planner] Processing feature: {feature_name}")
    
    # Get spec path
    spec_path = state.get('spec_path', 'spec/')
    
    # Read main instruction file
    try:
        feature_instructions = read_feature_instructions(spec_path)
    except Exception as e:
        return {"error_logs": [{"node": "spec_planner", "error": f"Error reading spec/feature.md: {e}"}]}
    
    # Read constitution
    try:
        constitution = read_all_constitution_files(spec_path)
    except Exception as e:
        print(f"Warning: Could not read constitution: {e}")
        constitution = ""
    
    # Read templates
    templates = {}
    template_names = ['spec.md', 'plan.md', 'tasks.md', 'clarifications.md']
    for template_name in template_names:
        try:
            templates[template_name] = read_template_file(template_name, spec_path)
        except Exception as e:
            print(f"Warning: Could not read template {template_name}: {e}")
            templates[template_name] = ""
    
    # Ensure feature directory exists
    if not ensure_feature_directory(feature_name, spec_path):
        return {"error_logs": [{"node": "spec_planner", "error": f"Could not create feature directory for {feature_name}"}]}
    
    # Check if feature already exists (for updates)
    existing_spec = read_spec_file(feature_name, 'spec', spec_path)
    existing_clarifications = read_spec_file(feature_name, 'clarifications', spec_path)
    
    # Build prompt for LLM
    prompt = f"""You are a Specification Planner following the spec-feature process.

MAIN INSTRUCTION (from spec/feature.md):
{feature_instructions}

CONSTITUTION (project rules - MUST follow):
{constitution}

TEMPLATES:
{json.dumps({k: v[:2000] + "..." if len(v) > 2000 else v for k, v in templates.items()}, indent=2)}

FEATURE NAME: {feature_name}
CONTEXT: {context}

EXISTING FILES (if any):
- Existing spec.md: {existing_spec[:500] if existing_spec else "None"}
- Existing clarifications.md: {existing_clarifications[:500] if existing_clarifications else "None"}

INSTRUCTIONS:
1. Follow the steps from spec/feature.md EXACTLY
2. If clarifications are needed, create clarifications.md FIRST and stop
3. Otherwise, create spec.md, plan.md, and tasks.md in sequence
4. Use the templates provided as structure
5. Fill ALL sections - no empty headers or placeholders
6. Write complete, valid Markdown

Output format: JSON with keys for each file to create/update:
{{
  "clarifications": "content or null if not needed",
  "spec": "content for spec.md",
  "plan": "content for plan.md",
  "tasks": "content for tasks.md"
}}

If clarifications are needed, set clarifications to the content and set spec/plan/tasks to null.
Otherwise, set clarifications to null and provide all three files.
"""
    
    # Create model and chat
    model = genai.GenerativeModel(model_name=MODEL_NAME)
    chat = model.start_chat()
    
    try:
        response = _call_api_with_retry(chat, prompt)
        response_text = response.text if hasattr(response, 'text') else str(response)
        
        # Extract JSON from response
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        result = json.loads(response_text.strip())
        
        # Write files
        files_created = []
        needs_clarifications = False
        
        if result.get("clarifications"):
            write_spec_file(feature_name, "clarifications", result["clarifications"], spec_path)
            files_created.append("clarifications.md")
            needs_clarifications = True
            print(f"[Spec Planner] Created clarifications.md - waiting for answers")
        
        if result.get("spec") and not needs_clarifications:
            write_spec_file(feature_name, "spec", result["spec"], spec_path)
            files_created.append("spec.md")
        
        if result.get("plan") and not needs_clarifications:
            write_spec_file(feature_name, "plan", result["plan"], spec_path)
            files_created.append("plan.md")
        
        if result.get("tasks") and not needs_clarifications:
            write_spec_file(feature_name, "tasks", result["tasks"], spec_path)
            files_created.append("tasks.md")
        
        # Extract usage
        usage = response.usage_metadata
        token_update = {
            "input_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
        
        print(f"[Spec Planner] Created files: {', '.join(files_created)}")
        
        # Set feature_id and phase based on what was created
        update_state: Dict[str, Any] = {
            "feature_name": feature_name,
            "feature_id": feature_name,  # Use feature_name as feature_id
            "spec_path": spec_path,
            "token_usage": token_update,
            "messages": [f"Spec Planner created specifications for feature: {feature_name}"]
        }
        
        if needs_clarifications:
            update_state["phase"] = "QUESTIONS_PENDING"
        else:
            update_state["phase"] = "SPEC_DRAFT"
        
        return update_state
        
    except json.JSONDecodeError as e:
        print(f"Spec Planner JSON Parse Error: {e}")
        print(f"Response was: {response_text[:500]}")
        return {"error_logs": [{"node": "spec_planner", "error": f"Invalid JSON response: {e}"}]}
    except Exception as e:
        print(f"Spec Planner Error: {e}")
        return {"error_logs": [{"node": "spec_planner", "error": str(e)}]}

def spec_planner_router(state: SharedState) -> str:
    """
    Router for spec planner - determines next step based on phase.
    """
    from orchestrator.state import can_enter_node, is_valid_transition
    
    current_phase = state.get('phase', 'INTAKE')
    
    # Check if we can enter this node from current phase
    if not can_enter_node("spec_planner", current_phase) and current_phase != "INTAKE":
        print(f"[Spec Planner Router] Illegal transition from phase {current_phase} to spec_planner")
        return "__end__"
    
    # If questions are pending, check if they have been answered
    if current_phase == "QUESTIONS_PENDING":
        # Check if clarifications exist and have answers
        feature_name = state.get('feature_name')
        spec_path = state.get('spec_path', 'spec/')
        open_questions = state.get('open_questions', [])
        
        # Check structured questions first
        if open_questions and all_questions_answered(open_questions):
            # All questions answered - can proceed
            if is_valid_transition("QUESTIONS_PENDING", "SPEC_DRAFT"):
                return "spec_planner"  # Re-run planner with answers
        
        # Fallback: check clarifications file format
        if feature_name:
            clarifications = read_spec_file(feature_name, 'clarifications', spec_path)
            if clarifications and "## Answers" in clarifications:
                if is_valid_transition("QUESTIONS_PENDING", "SPEC_DRAFT"):
                    return "spec_planner"  # Re-run planner with answers
            elif clarifications:
                return "__end__"  # Wait for user to answer questions
        
        # Still pending questions
        return "__end__"
    
    # After creating specs (SPEC_DRAFT), go to reviewer
    if current_phase == "SPEC_DRAFT":
        if is_valid_transition("SPEC_DRAFT", "SPEC_REVIEW"):
            return "spec_reviewer"
    
    # Default: after INTAKE or if phase transition is valid
    if current_phase in ["INTAKE", "QUESTIONS_PENDING"]:
        # INTAKE -> SPEC_DRAFT is handled by the node itself
        # After node creates spec, phase becomes SPEC_DRAFT, then we go to reviewer
        # This router is called after the node, so we check the resulting phase
        # Actually, we should check the phase that was just set
        resulting_phase = state.get('phase', current_phase)
        if resulting_phase == "SPEC_DRAFT" and is_valid_transition("SPEC_DRAFT", "SPEC_REVIEW"):
            return "spec_reviewer"
        elif resulting_phase == "QUESTIONS_PENDING":
            return "__end__"
    
    # Fallback: end if no valid transition
    print(f"[Spec Planner Router] No valid transition from phase {current_phase}")
    return "__end__"
