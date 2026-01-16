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
from orchestrator.state import (
    SharedState,
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
from orchestrator.tools.shell_tools import run_shell_command
from orchestrator.tools.fs_tools import WORKSPACE_DIR, list_files
from orchestrator.tools.project_profile_tools import (
    load_project_profile,
    has_project_profile,
    is_service_project
)
from orchestrator.tools.validation_artifacts import (
    ensure_artifacts_dir,
    save_command_log,
    save_validation_summary,
    append_validation_log
)
import subprocess
import requests
import socket

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

def _load_project_profile() -> Optional[Dict[str, Any]]:
    """Load project profile from workspace."""
    return load_project_profile(WORKSPACE_DIR)

def _execute_build_commands(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Execute build commands from profile."""
    build_results = {
        "ran": False,
        "passed": False,
        "output": "",
        "error": None,
        "logs": []
    }
    
    build_commands = profile.get('build_commands', [])
    if not build_commands:
        build_results["output"] = "No build commands specified"
        return build_results
    
    build_results["ran"] = True
    all_passed = True
    
    for cmd in build_commands:
        try:
            print(f"[Validation] Running build command: {cmd}")
            result = run_shell_command(cmd, timeout=300)
            
            # Save log
            log_path = save_command_log(cmd, result, log_type="build")
            build_results["logs"].append(log_path)
            
            # Check exit code (simple heuristic)
            if "[EXIT CODE]" in result and "0" not in result:
                all_passed = False
                build_results["output"] += f"Build command failed: {cmd}\n{result}\n"
            else:
                build_results["output"] += f"Build command succeeded: {cmd}\n{result[:500]}\n"
                
        except Exception as e:
            all_passed = False
            error_msg = f"Error running build command '{cmd}': {e}"
            build_results["error"] = error_msg
            build_results["output"] += error_msg + "\n"
            save_command_log(cmd, error_msg, log_type="build")
    
    build_results["passed"] = all_passed
    return build_results

def _execute_test_commands(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Execute test commands from profile."""
    test_results = {
        "ran": False,
        "passed": False,
        "output": "",
        "error": None,
        "logs": []
    }
    
    test_commands = profile.get('test_commands', [])
    if not test_commands:
        test_results["output"] = "No test commands specified"
        return test_results
    
    test_results["ran"] = True
    all_passed = True
    
    for cmd in test_commands:
        try:
            print(f"[Validation] Running test command: {cmd}")
            result = run_shell_command(cmd, timeout=300)
            
            # Save log
            log_path = save_command_log(cmd, result, log_type="test")
            test_results["logs"].append(log_path)
            
            # Check if tests passed (simple heuristic)
            if "[EXIT CODE]" in result and "0" not in result:
                all_passed = False
            if "failing" in result.lower() or "failed" in result.lower():
                all_passed = False
            
            test_results["output"] += f"Test command: {cmd}\n{result[:1000]}\n"
                
        except Exception as e:
            all_passed = False
            error_msg = f"Error running test command '{cmd}': {e}"
            test_results["error"] = error_msg
            test_results["output"] += error_msg + "\n"
            save_command_log(cmd, error_msg, log_type="test")
    
    test_results["passed"] = all_passed
    return test_results

def _start_service(profile: Dict[str, Any]) -> Optional[subprocess.Popen]:
    """Start service using run_commands from profile."""
    run_commands = profile.get('run_commands', [])
    if not run_commands:
        return None
    
    # Start service in background
    # Note: This is a simplified implementation
    # In production, you might want more sophisticated process management
    try:
        # For now, we'll just log that service should be started
        # Actual background process management would require more complex handling
        print(f"[Validation] Service should be started with: {run_commands}")
        append_validation_log(f"Service start commands: {run_commands}", log_type="service")
        return None  # Placeholder - actual implementation would start process
    except Exception as e:
        print(f"[Validation] Error starting service: {e}")
        return None

def _check_health(healthcheck: Dict[str, Any]) -> Dict[str, Any]:
    """Check service health using healthcheck configuration."""
    health_results = {
        "checked": False,
        "passed": False,
        "output": "",
        "error": None
    }
    
    hc_type = healthcheck.get('type', 'url')
    hc_value = healthcheck.get('value', '')
    timeout = healthcheck.get('timeout', 30)
    
    if not hc_value:
        health_results["error"] = "Healthcheck value not specified"
        return health_results
    
    health_results["checked"] = True
    
    try:
        if hc_type == 'url':
            # Check URL
            response = requests.get(hc_value, timeout=timeout)
            health_results["passed"] = response.status_code == 200
            health_results["output"] = f"Healthcheck URL {hc_value}: status {response.status_code}"
            
        elif hc_type == 'port':
            # Check if port is open
            # hc_value can be "3000" or "localhost:3000" or "host:port"
            if ':' in hc_value:
                host, port_str = hc_value.split(':', 1)
            else:
                host = 'localhost'
                port_str = hc_value
            
            try:
                port = int(port_str)
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((host, port))
                sock.close()
                health_results["passed"] = result == 0
                health_results["output"] = f"Healthcheck port {host}:{port}: {'open' if result == 0 else 'closed'}"
            except (ValueError, socket.error) as e:
                health_results["error"] = f"Invalid port or connection error: {e}"
                health_results["passed"] = False
            
        elif hc_type == 'command':
            # Execute healthcheck command
            result = run_shell_command(hc_value, timeout=timeout)
            health_results["passed"] = "[EXIT CODE]" not in result or "0" in result
            health_results["output"] = f"Healthcheck command: {result[:500]}"
        else:
            health_results["error"] = f"Unknown healthcheck type: {hc_type}"
            health_results["passed"] = False
            
    except Exception as e:
        health_results["error"] = str(e)
        health_results["output"] = f"Healthcheck error: {e}"
        health_results["passed"] = False
    
    # Save healthcheck log
    save_command_log(
        f"healthcheck ({hc_type})",
        health_results["output"],
        log_type="healthcheck"
    )
    
    return health_results

def _execute_validation_workflow() -> Dict[str, Any]:
    """
    Execute full validation workflow:
    1. Load project profile
    2. Execute build commands
    3. Execute test commands (or return NEEDS_USER_DECISION if none)
    4. Start service and check health (if service project)
    5. Save all logs
    """
    validation_results = {
        "profile_loaded": False,
        "build": {"ran": False, "passed": False},
        "tests": {"ran": False, "passed": False, "needs_decision": False},
        "service": {"started": False, "healthcheck": {"checked": False, "passed": False}},
        "logs": [],
        "needs_user_decision": False,
        "decision_reason": None
    }
    
    # Ensure artifacts directory exists
    ensure_artifacts_dir(WORKSPACE_DIR)
    append_validation_log("Starting validation workflow", log_type="validation")
    
    # Load project profile
    profile = _load_project_profile()
    if not profile:
        append_validation_log("No project_profile.yaml/json found - using legacy validation", log_type="validation")
        # Fallback to legacy _run_tests behavior
        return {
            "profile_loaded": False,
            "build": {"ran": False, "passed": False},
            "tests": {"ran": False, "passed": False, "needs_decision": False},
            "service": {"started": False, "healthcheck": {"checked": False, "passed": False}},
            "logs": [],
            "needs_user_decision": False,
            "decision_reason": None,
            "legacy_test_results": _run_tests_legacy()
        }
    
    validation_results["profile_loaded"] = True
    append_validation_log("Project profile loaded", log_type="validation")
    
    # Execute build commands
    if profile.get('build_commands'):
        build_results = _execute_build_commands(profile)
        validation_results["build"] = {
            "ran": build_results["ran"],
            "passed": build_results["passed"],
            "output": build_results["output"],
            "logs": build_results["logs"]
        }
        validation_results["logs"].extend(build_results["logs"])
    
    # Execute test commands
    test_commands = profile.get('test_commands', [])
    if not test_commands:
        # No tests - need user decision
        validation_results["tests"]["needs_decision"] = True
        validation_results["needs_user_decision"] = True
        validation_results["decision_reason"] = "Нет тестов, подтверждаете такой критерий приёмки?"
        append_validation_log("No test commands found - requires user decision", log_type="validation")
    else:
        test_results = _execute_test_commands(profile)
        validation_results["tests"] = {
            "ran": test_results["ran"],
            "passed": test_results["passed"],
            "output": test_results["output"],
            "logs": test_results["logs"],
            "needs_decision": False
        }
        validation_results["logs"].extend(test_results["logs"])
    
    # Check if service project and handle healthcheck
    if is_service_project(profile):
        append_validation_log("Service project detected - starting service and healthcheck", log_type="validation")
        service_process = _start_service(profile)
        validation_results["service"]["started"] = service_process is not None
        
        healthcheck = profile.get('healthcheck')
        if healthcheck:
            # Wait a bit for service to start
            time.sleep(5)
            health_results = _check_health(healthcheck)
            validation_results["service"]["healthcheck"] = {
                "checked": health_results["checked"],
                "passed": health_results["passed"],
                "output": health_results["output"]
            }
            if health_results.get("error"):
                validation_results["service"]["healthcheck"]["error"] = health_results["error"]
    
    # Save validation summary
    summary = {
        "validation_results": validation_results,
        "timestamp": datetime.now().isoformat()
    }
    save_validation_summary(summary, WORKSPACE_DIR)
    
    return validation_results

def _run_tests_legacy() -> Dict[str, Any]:
    """Legacy test runner for backward compatibility."""
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
    
    # Check retry budget before proceeding
    stage = get_current_stage(current_phase)
    retry_budget = state.get('retry_budget', {})
    
    if check_retry_limit(stage, retry_budget):
        error_result = handle_error_with_retry_budget(
            state,
            "final_validator",
            f"Retry limit already reached for {stage} stage. Cannot proceed.",
            context={"action": "pre_execution_check"}
        )
        error_result["phase"] = "FAILED"
        return error_result
    
    # Check if we can enter this node from current phase
    if not can_enter_node("final_validator", current_phase):
        error_result = handle_error_with_retry_budget(
            state,
            "final_validator",
            f"Cannot enter final_validator from phase {current_phase}",
            context={"current_phase": current_phase}
        )
        error_result["phase"] = "FAILED"
        return error_result
    
    if not feature_name:
        error_result = handle_error_with_retry_budget(
            state,
            "final_validator",
            "No feature_name in state."
        )
        return error_result
    
    # Set phase to VALIDATING when starting validation
    print(f"[Final Validator] Validating feature: {feature_name} (phase: {current_phase} -> VALIDATING)")
    
    # Read specification files
    spec_content = read_spec_file(feature_name, 'spec', spec_path)
    plan_content = read_spec_file(feature_name, 'plan', spec_path)
    tasks_content = read_spec_file(feature_name, 'tasks', spec_path)
    
    if not spec_content or not plan_content or not tasks_content:
        error_result = handle_error_with_retry_budget(
            state,
            "final_validator",
            "Missing specification files",
            context={"feature_name": feature_name, "spec_path": spec_path}
        )
        error_result["final_validation_report"] = {"status": "failed", "error": "Missing specifications"}
        return error_result
    
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
    
    # Execute validation workflow
    validation_results = _execute_validation_workflow()
    
    # Check if user decision is needed
    if validation_results.get("needs_user_decision"):
        decision_reason = validation_results.get("decision_reason", "Требуется решение пользователя")
        return {
            "phase": "NEEDS_USER_DECISION",
            "messages": [f"Final Validator: {decision_reason}"],
            "final_validation_report": {
                "status": "pending",
                "needs_user_decision": True,
                "decision_reason": decision_reason,
                "validation_results": validation_results
            }
        }
    
    # Prepare test results for backward compatibility
    test_results = {
        "ran": validation_results.get("tests", {}).get("ran", False),
        "passed": validation_results.get("tests", {}).get("passed", False),
        "output": validation_results.get("tests", {}).get("output", ""),
        "error": None
    }
    
    # If legacy mode, use legacy test results
    if not validation_results.get("profile_loaded") and "legacy_test_results" in validation_results:
        test_results = validation_results["legacy_test_results"]
    
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

VALIDATION RESULTS:
- Build: {'ran' if validation_results.get('build', {}).get('ran') else 'not run'} {'passed' if validation_results.get('build', {}).get('passed') else 'failed'}
- Tests: {'ran' if validation_results.get('tests', {}).get('ran') else 'not run'} {'passed' if validation_results.get('tests', {}).get('passed') else 'failed'}
- Service healthcheck: {'checked' if validation_results.get('service', {}).get('healthcheck', {}).get('checked') else 'not checked'} {'passed' if validation_results.get('service', {}).get('healthcheck', {}).get('passed') else 'failed'}

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
                "test_results": test_results,
                "validation_results": validation_results
            },
            "token_usage": token_update,
            "messages": [f"Final Validator: {validation_status}. {validation_result.get('summary', '')}"]
        }
        
    except json.JSONDecodeError as e:
        print(f"Final Validator JSON Parse Error: {e}")
        print(f"Response was: {response_text[:500]}")
        error_result = handle_error_with_retry_budget(
            state,
            "final_validator",
            f"Invalid JSON response: {e}",
            context={"response_preview": response_text[:200], "feature_name": feature_name}
        )
        error_result["final_validation_report"] = {"status": "failed", "error": "JSON parse error"}
        error_result["phase"] = "FAILED"
        return error_result
    except Exception as e:
        print(f"Final Validator Error: {e}")
        error_result = handle_error_with_retry_budget(
            state,
            "final_validator",
            str(e),
            context={"feature_name": feature_name}
        )
        error_result["final_validation_report"] = {"status": "failed", "error": str(e)}
        error_result["phase"] = "FAILED"
        return error_result
