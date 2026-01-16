"""
Specification Reviewer Node - validates specifications for completeness and compliance.
"""

import os
import time
import json
from typing import Optional, Any, Dict
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from orchestrator.state import SharedState
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
    _ensure_api_configured()
    
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    
    if not feature_name:
        return {"error_logs": [{"node": "spec_reviewer", "error": "No feature_name in state."}]}
    
    print(f"[Spec Reviewer] Reviewing feature: {feature_name}")
    
    # Read specification files
    spec_content = read_spec_file(feature_name, 'spec', spec_path)
    plan_content = read_spec_file(feature_name, 'plan', spec_path)
    tasks_content = read_spec_file(feature_name, 'tasks', spec_path)
    clarifications_content = read_spec_file(feature_name, 'clarifications', spec_path)
    
    if not spec_content or not plan_content or not tasks_content:
        return {
            "error_logs": [{"node": "spec_reviewer", "error": "Missing specification files"}],
            "spec_review_status": "needs_revision"
        }
    
    # Read constitution
    try:
        constitution = read_all_constitution_files(spec_path)
    except Exception as e:
        print(f"Warning: Could not read constitution: {e}")
        constitution = ""
    
    # Read clarifications template if needed
    clarifications_template = ""
    try:
        clarifications_template = read_template_file('clarifications.md', spec_path)
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

=== clarifications.md (if exists) ===
{clarifications_content[:1000] if clarifications_content else "None"}

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
        
        # If questions are needed, update clarifications.md
        if questions and status == "needs_revision":
            clarifications_content_new = clarifications_content or ""
            if clarifications_template:
                clarifications_content_new = clarifications_template
            
            # Add new questions
            questions_section = "\n\n## New Questions\n\n"
            for i, q in enumerate(questions, 1):
                questions_section += f"### Question #{i}\n{q}\n\n**Answer:**\n\n"
            
            clarifications_content_new += questions_section
            write_spec_file(feature_name, "clarifications", clarifications_content_new, spec_path)
        
        # Extract usage
        usage = response.usage_metadata
        token_update = {
            "input_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
        
        return {
            "spec_review_status": status,
            "spec_questions": questions,
            "token_usage": token_update,
            "messages": [f"Spec Reviewer: {status}. {summary}"]
        }
        
    except json.JSONDecodeError as e:
        print(f"Spec Reviewer JSON Parse Error: {e}")
        print(f"Response was: {response_text[:500]}")
        return {
            "error_logs": [{"node": "spec_reviewer", "error": f"Invalid JSON response: {e}"}],
            "spec_review_status": "needs_revision"
        }
    except Exception as e:
        print(f"Spec Reviewer Error: {e}")
        return {
            "error_logs": [{"node": "spec_reviewer", "error": str(e)}],
            "spec_review_status": "needs_revision"
        }

def spec_reviewer_router(state: SharedState) -> str:
    """
    Router for spec reviewer - determines next step based on review status.
    """
    review_status = state.get('spec_review_status', 'pending')
    
    if review_status == 'approved':
        return "supervisor"
    elif review_status == 'needs_revision':
        # Check if clarifications have answers
        feature_name = state.get('feature_name')
        spec_path = state.get('spec_path', 'spec/')
        if feature_name:
            clarifications = read_spec_file(feature_name, 'clarifications', spec_path)
            if clarifications and "## Answers" in clarifications:
                return "spec_planner"  # Re-run planner with answers
        return "__end__"  # Wait for user to answer questions
    
    return "__end__"
