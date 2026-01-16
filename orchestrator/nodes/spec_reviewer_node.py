"""
Specification Reviewer Node - validates specifications for completeness and compliance.
"""

import os
import time
import json
from typing import Optional, Any, Dict
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from orchestrator.state import (
    SharedState, 
    add_open_question, 
    all_questions_answered, 
    is_valid_transition,
    get_current_stage,
    check_retry_limit,
    handle_error_with_retry_budget
)
from orchestrator.tools.spec_feature_tools import (
    read_all_constitution_files,
    read_template_file,
    read_spec_file,
    write_spec_file,
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

def spec_reviewer_node(state: SharedState) -> SharedState:
    """
    Specification Reviewer Node - validates specifications.
    """
    from orchestrator.state import can_enter_node
    
    _ensure_api_configured()
    
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    current_phase = state.get('phase', 'INTAKE')
    
    # Check retry budget before proceeding
    stage = get_current_stage(current_phase)
    retry_budget = state.get('retry_budget', {})
    
    if check_retry_limit(stage, retry_budget):
        error_result = handle_error_with_retry_budget(
            state,
            "spec_reviewer",
            f"Retry limit already reached for {stage} stage. Cannot proceed.",
            context={"action": "pre_execution_check"}
        )
        error_result["phase"] = "FAILED"
        return error_result
    
    # Check if we can enter this node from current phase
    if not can_enter_node("spec_reviewer", current_phase):
        error_result = handle_error_with_retry_budget(
            state,
            "spec_reviewer",
            f"Cannot enter spec_reviewer from phase {current_phase}",
            context={"current_phase": current_phase}
        )
        error_result["phase"] = "FAILED"
        return error_result
    
    if not feature_name:
        error_result = handle_error_with_retry_budget(
            state,
            "spec_reviewer",
            "No feature_name in state."
        )
        return error_result
    
    # Set phase to SPEC_REVIEW when starting review
    print(f"[Spec Reviewer] Reviewing feature: {feature_name} (phase: {current_phase} -> SPEC_REVIEW)")
    
    # Read specification files
    spec_content = read_spec_file(feature_name, 'spec', spec_path)
    plan_content = read_spec_file(feature_name, 'plan', spec_path)
    tasks_content = read_spec_file(feature_name, 'tasks', spec_path)
    questions_content = read_spec_file(feature_name, 'questions', spec_path)
    
    if not spec_content or not plan_content or not tasks_content:
        error_result = handle_error_with_retry_budget(
            state,
            "spec_reviewer",
            "Missing specification files",
            context={"feature_name": feature_name, "spec_path": spec_path}
        )
        error_result["phase"] = "QUESTIONS_PENDING"
        return error_result
    
    # Read constitution
    try:
        constitution = read_all_constitution_files(spec_path)
    except Exception as e:
        print(f"Warning: Could not read constitution: {e}")
        constitution = ""
    
    # Read questions template if needed (for reference)
    questions_template = ""
    try:
        questions_template = read_template_file('questions.md', spec_path)
    except Exception:
        pass
    
    # Build review prompt
    prompt = f"""You are a Specification Reviewer. Your task is to validate specifications for completeness, consistency, and compliance with project rules.

CONSTITUTION (project rules - MUST comply):
{constitution}

SPECIFICATION FILES TO REVIEW:

=== spec.md ===
{spec_content[:4000]}

=== plan.md ===
{plan_content[:4000]}

=== tasks.md ===
{tasks_content[:4000]}

=== questions.md (if exists) ===
{questions_content[:1000] if questions_content else "None"}

REVIEW CRITERIA:
1. Completeness: Are all required sections filled? No empty headers or placeholders?
2. Consistency: Do spec.md, plan.md, and tasks.md align with each other?
3. Compliance: Do specifications follow constitution rules?
4. Clarity: Are requirements clear and unambiguous?
5. Feasibility: Is the plan technically feasible?

Output JSON format:
{{
  "status": "approved" or "needs_revision",
  "issues": ["list of issues found, empty if approved"],
  "questions": ["list of clarifying questions if needed, empty if none"],
  "summary": "brief summary of review"
}}

If status is "approved", proceed to implementation.
If status is "needs_revision", provide specific issues and questions that need to be addressed.
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
        
        status = review_result.get("status", "needs_revision")
        issues = review_result.get("issues", [])
        questions = review_result.get("questions", [])
        summary = review_result.get("summary", "")
        
        print(f"[Spec Reviewer] Status: {status}")
        if issues:
            print(f"[Spec Reviewer] Issues found: {len(issues)}")
        if questions:
            print(f"[Spec Reviewer] Questions: {len(questions)}")
        
        # Get existing open_questions
        open_questions = state.get('open_questions', []).copy()
        
        # Convert questions to structured open_questions format
        for q in questions:
            add_open_question(open_questions, q)
        
        # If questions are needed, they will be processed by question_generator_node
        # We just mark them here and let the router handle the transition
        
        # Extract usage
        usage = response.usage_metadata
        token_update = {
            "input_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
        
        # Determine phase based on status
        if status == "approved":
            new_phase = "SPEC_APPROVED"
            # Add notification message for user
            spec_path_value = state.get('spec_path', 'spec/')
            notification_msg = (
                f"Спеки готовы: {spec_path_value}/features/{feature_name}/spec.md и tasks.md\n"
                f"Чтобы начать разработку — напишите команду: RUN {spec_path_value}/features/{feature_name}/tasks.md"
            )
            return {
                "phase": new_phase,
                "open_questions": open_questions,
                "token_usage": token_update,
                "messages": [f"Spec Reviewer: {status}. {summary}\n\n{notification_msg}"]
            }
        elif questions:
            new_phase = "QUESTIONS_PENDING"
        else:
            new_phase = "SPEC_DRAFT"  # Needs revision but no questions
        
        return {
            "phase": new_phase,
            "open_questions": open_questions,
            "token_usage": token_update,
            "messages": [f"Spec Reviewer: {status}. {summary}"]
        }
        
    except json.JSONDecodeError as e:
        print(f"Spec Reviewer JSON Parse Error: {e}")
        print(f"Response was: {response_text[:500]}")
        error_result = handle_error_with_retry_budget(
            state,
            "spec_reviewer",
            f"Invalid JSON response: {e}",
            context={"response_preview": response_text[:200], "feature_name": feature_name}
        )
        error_result["phase"] = "FAILED"
        return error_result
    except Exception as e:
        print(f"Spec Reviewer Error: {e}")
        error_result = handle_error_with_retry_budget(
            state,
            "spec_reviewer",
            str(e),
            context={"feature_name": feature_name}
        )
        error_result["phase"] = "FAILED"
        return error_result

def spec_reviewer_router(state: SharedState) -> str:
    """
    Router for spec reviewer - determines next step based on phase.
    """
    from orchestrator.state import can_enter_node, has_open_decision_points
    
    current_phase = state.get('phase', 'INTAKE')
    
    # Check if we can enter this node from current phase
    if not can_enter_node("spec_reviewer", current_phase):
        print(f"[Spec Reviewer Router] Illegal transition from phase {current_phase} to spec_reviewer")
        return "__end__"
    
    # Check for open decision points (blocking)
    if has_open_decision_points(state):
        decision_points = state.get('decision_points', [])
        open_count = len([dp for dp in decision_points if dp.get("status") == "open"])
        print(f"[Spec Reviewer Router] BLOCKED: Cannot proceed with {open_count} open decision point(s)")
        return "__end__"
    
    # After review, check the resulting phase
    resulting_phase = state.get('phase', current_phase)
    
    if resulting_phase == "SPEC_APPROVED":
        # Spec approved - end graph and wait for RUN_TASKS command
        print(f"[Spec Reviewer Router] Specs approved. Graph ends. User must run: RUN spec/features/{state.get('feature_name', 'feature')}/tasks.md")
        return "__end__"
    
    elif resulting_phase == "QUESTIONS_PENDING":
        # Questions pending - route to question_generator to create questions.md
        # question_generator will create the questions.md file and set phase back to QUESTIONS_PENDING
        print(f"[Spec Reviewer Router] Questions pending. Routing to question_generator")
        return "question_generator"
    
    elif resulting_phase == "SPEC_DRAFT":
        # Needs revision - return to spec_planner
        if is_valid_transition("SPEC_DRAFT", "SPEC_REVIEW"):
            return "spec_planner"
    
    elif resulting_phase == "FAILED":
        return "__end__"
    
    # Fallback: end if no valid transition
    print(f"[Spec Reviewer Router] No valid transition from phase {resulting_phase}")
    return "__end__"
