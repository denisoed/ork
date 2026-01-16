"""
Spec Updater Node - updates spec.md and tasks.md based on answers from questions.md.
"""

import os
import time
import json
from typing import Optional, Any, Dict
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from orchestrator.state import SharedState, all_questions_answered
from orchestrator.tools.spec_feature_tools import (
    read_all_constitution_files,
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

def spec_updater_node(state: SharedState) -> SharedState:
    """
    Spec Updater Node - updates spec.md and tasks.md based on answers.
    """
    _ensure_api_configured()
    
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    current_phase = state.get('phase', 'INTAKE')
    
    if not feature_name:
        return {"error_logs": [{"node": "spec_updater", "error": "No feature_name in state."}]}
    
    print(f"[Spec Updater] Updating spec files for feature: {feature_name} (phase: {current_phase})")
    
    # Check if all questions are answered
    open_questions = state.get('open_questions', [])
    if not all_questions_answered(open_questions):
        return {
            "error_logs": [{"node": "spec_updater", "error": "Not all questions are answered yet"}],
            "messages": ["Spec Updater: Not all questions are answered. Please provide answers for all questions first."]
        }
    
    # Read specification files
    spec_content = read_spec_file(feature_name, 'spec', spec_path)
    plan_content = read_spec_file(feature_name, 'plan', spec_path)
    tasks_content = read_spec_file(feature_name, 'tasks', spec_path)
    questions_content = read_spec_file(feature_name, 'questions', spec_path)
    
    if not spec_content or not tasks_content:
        return {
            "error_logs": [{"node": "spec_updater", "error": "Missing spec.md or tasks.md files"}],
            "phase": "FAILED"
        }
    
    if not questions_content:
        return {
            "error_logs": [{"node": "spec_updater", "error": "Missing questions.md file"}],
            "phase": "FAILED"
        }
    
    # Read constitution
    try:
        constitution = read_all_constitution_files(spec_path)
    except Exception as e:
        print(f"Warning: Could not read constitution: {e}")
        constitution = ""
    
    # Extract answers from questions.md and open_questions
    answers_summary = []
    for q in open_questions:
        if q.get("status") == "answered":
            question_text = q.get("question", "")
            answer_text = q.get("answer", "")
            answers_summary.append(f"Q: {question_text}\nA: {answer_text}")
    
    if not answers_summary:
        return {
            "error_logs": [{"node": "spec_updater", "error": "No answers found in questions"}],
            "phase": "FAILED"
        }
    
    answers_text = "\n\n".join(answers_summary)
    
    # Build prompt for updating specs
    prompt = f"""You are a Spec Updater. Your task is to update spec.md and tasks.md based on answers provided in questions.md.

CONSTITUTION (project rules - MUST comply):
{constitution}

CURRENT SPECIFICATION FILES:

=== spec.md ===
{spec_content[:4000]}

=== plan.md ===
{plan_content[:3000] if plan_content else "None"}

=== tasks.md ===
{tasks_content[:4000]}

=== questions.md (with answers) ===
{questions_content[:3000]}

ANSWERS TO INCORPORATE:
{answers_text[:2000]}

INSTRUCTIONS:
1. Review the answers provided
2. Update spec.md to incorporate the answers - replace ambiguous or incomplete sections with concrete decisions
3. Update tasks.md to reflect any changes needed based on the answers
4. Maintain consistency between spec.md, plan.md, and tasks.md
5. Preserve all existing valid content - only update parts that were dependent on the questions
6. Ensure all sections are complete - no placeholders or empty headers

Output JSON format:
{{
  "spec": "updated spec.md content",
  "tasks": "updated tasks.md content",
  "summary": "brief summary of what was updated"
}}

Update spec.md and tasks.md based on the answers provided.
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
        
        result = json.loads(response_text.strip())
        
        updated_spec = result.get("spec", "")
        updated_tasks = result.get("tasks", "")
        summary = result.get("summary", "")
        
        if not updated_spec or not updated_tasks:
            return {
                "error_logs": [{"node": "spec_updater", "error": "LLM did not return updated spec or tasks"}],
                "phase": "FAILED"
            }
        
        # Write updated files
        write_spec_file(feature_name, "spec", updated_spec, spec_path)
        write_spec_file(feature_name, "tasks", updated_tasks, spec_path)
        
        print(f"[Spec Updater] Updated spec.md and tasks.md based on answers")
        print(f"[Spec Updater] Summary: {summary}")
        
        # Extract usage
        usage = response.usage_metadata
        token_update = {
            "input_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
        
        # Set phase to SPEC_REVIEW for re-review
        return {
            "phase": "SPEC_REVIEW",
            "token_usage": token_update,
            "messages": [f"Spec Updater: Updated spec.md and tasks.md based on answers. Summary: {summary}. Proceeding to re-review."]
        }
        
    except json.JSONDecodeError as e:
        print(f"Spec Updater JSON Parse Error: {e}")
        print(f"Response was: {response_text[:500]}")
        return {
            "error_logs": [{"node": "spec_updater", "error": f"Invalid JSON response: {e}"}],
            "phase": "FAILED"
        }
    except Exception as e:
        print(f"Spec Updater Error: {e}")
        return {
            "error_logs": [{"node": "spec_updater", "error": str(e)}],
            "phase": "FAILED"
        }

def spec_updater_router(state: SharedState) -> str:
    """
    Router for spec updater - determines next step after updating specs.
    """
    from orchestrator.state import is_valid_transition
    
    current_phase = state.get('phase', 'INTAKE')
    
    # After updating specs, go to spec_reviewer for re-review
    if current_phase == "SPEC_REVIEW":
        print(f"[Spec Updater Router] Specs updated. Proceeding to spec_reviewer for re-review.")
        if is_valid_transition("SPEC_REVIEW", "SPEC_REVIEW"):
            return "spec_reviewer"
    
    # If failed, end
    if current_phase == "FAILED":
        return "__end__"
    
    # Default: end
    return "__end__"

