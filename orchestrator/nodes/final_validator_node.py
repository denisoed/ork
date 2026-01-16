"""
Final Validator Node - validates implementation against specifications and creates verify-report.md.
"""

import os
import time
import json
from datetime import datetime
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
from orchestrator.tools.shell_tools import run_shell_command
from orchestrator.tools.fs_tools import WORKSPACE_DIR, list_files

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

def _run_tests() -> Dict[str, Any]:
    """Run tests if available."""
    test_results = {
        "ran": False,
        "passed": False,
        "output": "",
        "error": None
    }
    
    # Check for package.json
    package_json = os.path.join(WORKSPACE_DIR, 'package.json')
    if not os.path.exists(package_json):
        test_results["output"] = "No package.json found - skipping tests"
        return test_results
    
    # Try to run tests
    try:
        result = run_shell_command("npm test", timeout=60)
        test_results["ran"] = True
        test_results["output"] = result
        
        # Check if tests passed (simple heuristic)
        if "failing" not in result.lower() and "error" not in result.lower():
            test_results["passed"] = True
    except Exception as e:
        test_results["error"] = str(e)
        test_results["output"] = f"Error running tests: {e}"
    
    return test_results

def _get_workspace_files_summary() -> str:
    """Get summary of files in workspace."""
    try:
        files = list_files(".")
        # Limit to first 50 files for context
        file_list = files.split("\n")[:50]
        return "\n".join(file_list)
    except Exception:
        return "Could not list files"

def final_validator_node(state: SharedState) -> SharedState:
    """
    Final Validator Node - validates implementation and creates verify-report.md.
    """
    from orchestrator.state import can_enter_node, is_valid_transition
    
    _ensure_api_configured()
    
    feature_name = state.get('feature_name')
    spec_path = state.get('spec_path', 'spec/')
    current_phase = state.get('phase', 'INTAKE')
    
    # Check if we can enter this node from current phase
    if not can_enter_node("final_validator", current_phase):
        return {
            "error_logs": [{"node": "final_validator", "error": f"Cannot enter final_validator from phase {current_phase}"}],
            "phase": "FAILED"
        }
    
    if not feature_name:
        return {"error_logs": [{"node": "final_validator", "error": "No feature_name in state."}]}
    
    # Set phase to VALIDATING when starting validation
    print(f"[Final Validator] Validating feature: {feature_name} (phase: {current_phase} -> VALIDATING)")
    
    # Read specification files
    spec_content = read_spec_file(feature_name, 'spec', spec_path)
    plan_content = read_spec_file(feature_name, 'plan', spec_path)
    tasks_content = read_spec_file(feature_name, 'tasks', spec_path)
    
    if not spec_content or not plan_content or not tasks_content:
        return {
            "error_logs": [{"node": "final_validator", "error": "Missing specification files"}],
            "final_validation_report": {"status": "failed", "error": "Missing specifications"}
        }
    
    # Read original user request
    user_request = ""
    messages = state.get('messages', [])
    if messages:
        for msg in reversed(messages):
            if hasattr(msg, "type") and getattr(msg, "type") == "human":
                user_request = str(getattr(msg, "content", ""))
                break
            if isinstance(msg, dict) and msg.get("role") == "user":
                user_request = str(msg.get("content", ""))
                break
    
    # Read constitution
    try:
        constitution = read_all_constitution_files(spec_path)
    except Exception as e:
        print(f"Warning: Could not read constitution: {e}")
        constitution = ""
    
    # Read verify template
    verify_template = ""
    try:
        verify_template = read_template_file('verify.md', spec_path)
    except Exception:
        pass
    
    # Get workspace files summary
    workspace_files = _get_workspace_files_summary()
    
    # Run tests
    test_results = _run_tests()
    
    # Build validation prompt
    prompt = f"""You are a Final Validator. Your task is to validate that the implementation matches the specifications and works correctly.

ORIGINAL USER REQUEST:
{user_request}

SPECIFICATION FILES:

=== spec.md ===
{spec_content[:4000]}

=== plan.md ===
{plan_content[:4000]}

=== tasks.md ===
{tasks_content[:4000]}

CONSTITUTION (compliance check):
{constitution[:2000]}

WORKSPACE FILES (implementation):
{workspace_files[:2000]}

TEST RESULTS:
- Tests ran: {test_results['ran']}
- Tests passed: {test_results['passed']}
- Output: {test_results['output'][:1000] if test_results['output'] else 'N/A'}

VALIDATION CRITERIA:
1. Implementation matches spec.md requirements
2. Implementation follows plan.md architecture
3. All tasks from tasks.md are completed
4. Implementation complies with constitution rules
5. Code works (tests pass, no critical errors)
6. Original user request is fulfilled

Output JSON format:
{{
  "status": "passed" or "failed",
  "spec_compliance": true/false,
  "plan_compliance": true/false,
  "tasks_completed": true/false,
  "constitution_compliance": true/false,
  "functional": true/false,
  "issues": ["list of issues found"],
  "summary": "brief summary of validation"
}}

Then provide verify-report.md content following the template structure.
"""
    
    # Create model and chat
    model = genai.GenerativeModel(model_name=MODEL_NAME)
    chat = model.start_chat()
    
    try:
        response = _call_api_with_retry(chat, prompt)
        response_text = response.text if hasattr(response, 'text') else str(response)
        
        # Extract JSON from response
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_text = response_text[json_start:json_end]
            validation_result = json.loads(json_text)
            
            # Extract verify-report content (after JSON)
            verify_report_content = response_text[json_end:].strip()
            if "```" in verify_report_content:
                verify_report_content = verify_report_content.split("```")[1].split("```")[0] if len(verify_report_content.split("```")) > 2 else verify_report_content
        else:
            # Fallback: try to parse entire response as JSON
            validation_result = json.loads(response_text.strip())
            verify_report_content = ""
        
        # If verify-report content is missing, generate it
        if not verify_report_content or len(verify_report_content) < 100:
            verify_report_content = f"""# Verify Report - {feature_name}

**Date:** {datetime.now().strftime('%Y-%m-%d')}
**Context:** Final validation of implementation

## Task verification results

Status: {validation_result.get('status', 'unknown')}

- Spec compliance: {validation_result.get('spec_compliance', False)}
- Plan compliance: {validation_result.get('plan_compliance', False)}
- Tasks completed: {validation_result.get('tasks_completed', False)}
- Constitution compliance: {validation_result.get('constitution_compliance', False)}
- Functional: {validation_result.get('functional', False)}

## Discrepancy log

{chr(10).join(f"- {issue}" for issue in validation_result.get('issues', [])) if validation_result.get('issues') else "No discrepancies detected"}

## Summary

{validation_result.get('summary', 'Validation completed')}
"""
        
        # Write verify-report.md
        write_spec_file(feature_name, "verify-report", verify_report_content, spec_path)
        
        # Extract usage
        usage = response.usage_metadata
        token_update = {
            "input_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "total_tokens": usage.total_token_count
        }
        
        validation_status = validation_result.get('status', 'failed')
        print(f"[Final Validator] Validation status: {validation_status}")
        
        # Determine phase based on validation status
        if validation_status == "passed":
            # Validation passed - move to TRACE_VALIDATION, then DONE
            new_phase = "TRACE_VALIDATION"
            # After trace validation (which is done here), set to DONE
            # Actually, we'll set DONE immediately after TRACE_VALIDATION in this node
            # But let's set TRACE_VALIDATION first, then transition to DONE
            if is_valid_transition("VALIDATING", "TRACE_VALIDATION"):
                # Set to TRACE_VALIDATION, then immediately to DONE if all checks pass
                new_phase = "DONE"
        else:
            # Validation failed
            new_phase = "FAILED"
        
        return {
            "phase": new_phase,
            "final_validation_report": {
                "status": validation_status,
                "spec_compliance": validation_result.get('spec_compliance', False),
                "plan_compliance": validation_result.get('plan_compliance', False),
                "tasks_completed": validation_result.get('tasks_completed', False),
                "constitution_compliance": validation_result.get('constitution_compliance', False),
                "functional": validation_result.get('functional', False),
                "issues": validation_result.get('issues', []),
                "summary": validation_result.get('summary', ''),
                "test_results": test_results
            },
            "token_usage": token_update,
            "messages": [f"Final Validator: {validation_status}. {validation_result.get('summary', '')}"]
        }
        
    except json.JSONDecodeError as e:
        print(f"Final Validator JSON Parse Error: {e}")
        print(f"Response was: {response_text[:500]}")
        return {
            "error_logs": [{"node": "final_validator", "error": f"Invalid JSON response: {e}"}],
            "final_validation_report": {"status": "failed", "error": "JSON parse error"},
            "phase": "FAILED"
        }
    except Exception as e:
        print(f"Final Validator Error: {e}")
        return {
            "error_logs": [{"node": "final_validator", "error": str(e)}],
            "final_validation_report": {"status": "failed", "error": str(e)},
            "phase": "FAILED"
        }
