"""
Deployment tools for Supabase and Vercel.

Provides functions for deploying applications, migrations,
and edge functions to production platforms.
"""

import os
import re
import subprocess
from typing import Dict, Optional, List
from orchestrator.tools.fs_tools import WORKSPACE_DIR, ensure_workspace
from orchestrator.utils.secrets import SecretManager
from orchestrator.tools.validation_artifacts import save_command_log
from orchestrator.tools.shell_tools import (
    ALLOWED_DEPLOY_COMMANDS,
    _validate_no_newlines,
    _validate_no_newlines_in_args,
    _check_command_allowlist,
    _check_directory_allowlist,
    is_deploy_command
)


def _run_deploy_command(command: List[str], timeout: int = 300) -> Dict[str, any]:
    """
    Execute a deployment command with extended timeout.
    
    Args:
        command: Shell command to execute as list of arguments
        timeout: Timeout in seconds (default 5 minutes)
        
    Returns:
        Dict with success, output, and return_code
    """
    ensure_workspace()
    
    # Convert command list to string for logging and validation
    command_str = ' '.join(command)
    
    # 1. Check for \n/\r in each element of command
    is_valid, error_msg = _validate_no_newlines_in_args(command)
    if not is_valid:
        error_msg = f"Error: {error_msg}"
        save_command_log(command_str, error_msg, exit_code=-1, log_type="deploy")
        return {
            'success': False,
            'output': error_msg,
            'return_code': -1
        }
    
    # 2. Check command allowlist (command[0] is the command name)
    if not command:
        error_msg = "Error: Empty command"
        save_command_log(command_str, error_msg, exit_code=-1, log_type="deploy")
        return {
            'success': False,
            'output': error_msg,
            'return_code': -1
        }
    
    command_name = command[0]
    is_deploy = is_deploy_command(command_str)
    is_allowed, error_msg = _check_command_allowlist(command_name, full_command=command_str, is_deploy=is_deploy)
    if not is_allowed:
        error_msg = f"Error: {error_msg}"
        save_command_log(command_str, error_msg, exit_code=-1, log_type="deploy")
        return {
            'success': False,
            'output': error_msg,
            'return_code': -1
        }
    
    # 3. Check directory allowlist (only WORKSPACE_DIR allowed)
    is_allowed, error_msg = _check_directory_allowlist(WORKSPACE_DIR)
    if not is_allowed:
        error_msg = f"Error: {error_msg}"
        save_command_log(command_str, error_msg, exit_code=-1, log_type="deploy")
        return {
            'success': False,
            'output': error_msg,
            'return_code': -1
        }
    
    try:
        # 4. Execute command with shell=False
        # Get deployment environment variables
        deploy_env = {**os.environ, **SecretManager.get_deployment_env()}
        
        result = subprocess.run(
            command,
            cwd=WORKSPACE_DIR,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=deploy_env
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\n{result.stderr}"
        
        # 5. Always log the command execution
        save_command_log(command_str, output, exit_code=result.returncode, log_type="deploy")
        
        return {
            'success': result.returncode == 0,
            'output': output,
            'return_code': result.returncode
        }
        
    except subprocess.TimeoutExpired:
        error_msg = f"Command timed out after {timeout} seconds"
        save_command_log(command_str, error_msg, exit_code=-1, log_type="deploy")
        return {
            'success': False,
            'output': error_msg,
            'return_code': -1
        }
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        save_command_log(command_str, error_msg, exit_code=-1, log_type="deploy")
        return {
            'success': False,
            'output': error_msg,
            'return_code': -1
        }


def _extract_vercel_url(output: str) -> Optional[str]:
    """
    Extract deployment URL from Vercel CLI output.
    
    Args:
        output: Vercel CLI command output
        
    Returns:
        Deployment URL or None if not found
    """
    # Vercel outputs URLs in various formats
    # Pattern matches: https://project-name-xxx.vercel.app
    patterns = [
        r'https://[a-zA-Z0-9-]+\.vercel\.app',
        r'https://[a-zA-Z0-9-]+\.[a-zA-Z0-9-]+\.vercel\.app',
        r'Production: (https://[^\s]+)',
        r'Preview: (https://[^\s]+)',
        r'Deployed to (https://[^\s]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            # Return the captured group if exists, otherwise full match
            return match.group(1) if match.lastindex else match.group(0)
    
    return None


def _extract_supabase_url(project_ref: str) -> str:
    """
    Construct Supabase project URL from project reference.
    
    Args:
        project_ref: Supabase project reference ID
        
    Returns:
        Supabase project URL
    """
    return f"https://{project_ref}.supabase.co"


def deploy_supabase_migration(migration_file: str = "") -> Dict[str, any]:
    """
    Deploy SQL migrations to Supabase.
    
    Args:
        migration_file: Optional migration identifier or file name.
                       Supabase CLI applies all pending migrations; the value is
                       accepted for compatibility but does not scope the push.
        
    Returns:
        Dict with:
        - success: bool
        - output: str (command output)
        - migration_id: str (migration identifier if available)
        - project_url: str (Supabase project URL)
    """
    # Validate credentials
    creds = SecretManager.validate_supabase_credentials()
    if not creds['valid']:
        return {
            'success': False,
            'output': f"Missing Supabase credentials: {', '.join(creds['missing'])}",
            'migration_id': None,
            'project_url': None
        }
    
    project_ref = SecretManager.get_supabase_project_ref()
    
    # Build command
    # Push all pending migrations (Supabase CLI does not support per-file push)
    command = ["supabase", "db", "push"]
    
    # Add project reference if available
    if project_ref:
        command.extend(["--project-ref", project_ref])
    
    # Execute
    result = _run_deploy_command(command)
    if migration_file:
        result['output'] = (
            "Note: specific migration selection is not supported; "
            "pushing all pending migrations.\n"
            + result['output']
        )
    
    # Extract migration ID from output if available
    migration_id = None
    migration_match = re.search(r'migration[:\s]+([a-zA-Z0-9_-]+)', result['output'], re.IGNORECASE)
    if migration_match:
        migration_id = migration_match.group(1)
    
    # Build project URL
    project_url = _extract_supabase_url(project_ref) if project_ref else None
    
    return {
        'success': result['success'],
        'output': result['output'],
        'migration_id': migration_id,
        'project_url': project_url
    }


def deploy_supabase_function(function_name: str, function_dir: str = "supabase/functions") -> Dict[str, any]:
    """
    Deploy an Edge Function to Supabase.
    
    Args:
        function_name: Name of the function to deploy
        function_dir: Directory containing the function (relative to workspace)
        
    Returns:
        Dict with:
        - success: bool
        - output: str (command output)
        - function_url: str (URL to invoke the function)
        - project_url: str (Supabase project URL)
    """
    # Validate credentials
    creds = SecretManager.validate_supabase_credentials()
    if not creds['valid']:
        return {
            'success': False,
            'output': f"Missing Supabase credentials: {', '.join(creds['missing'])}",
            'function_url': None,
            'project_url': None
        }
    
    project_ref = SecretManager.get_supabase_project_ref()
    
    # Build command
    command = ["supabase", "functions", "deploy", function_name]
    
    # Add project reference if available
    if project_ref:
        command.extend(["--project-ref", project_ref])
    
    # Execute
    result = _run_deploy_command(command)
    
    # Build function URL
    function_url = None
    project_url = None
    if project_ref:
        project_url = _extract_supabase_url(project_ref)
        function_url = f"{project_url}/functions/v1/{function_name}"
    
    return {
        'success': result['success'],
        'output': result['output'],
        'function_url': function_url,
        'project_url': project_url
    }


def deploy_to_vercel(project_dir: str = ".", production: bool = False) -> Dict[str, any]:
    """
    Deploy application to Vercel.
    
    Args:
        project_dir: Directory containing the project (relative to workspace)
        production: If True, deploy to production. If False (default), create preview deployment.
        
    Returns:
        Dict with:
        - success: bool
        - output: str (command output)
        - deployment_url: str (the deployed URL)
        - preview_url: str (preview URL, same as deployment_url for preview deploys)
        - is_production: bool
    """
    # Validate credentials
    creds = SecretManager.validate_vercel_credentials()
    if not creds['valid']:
        return {
            'success': False,
            'output': f"Missing Vercel credentials: {', '.join(creds['missing'])}",
            'deployment_url': None,
            'preview_url': None,
            'is_production': production
        }
    
    # Build command
    # --yes to skip confirmations
    # --token is passed via environment
    command = ["vercel", "deploy", "--yes"]
    
    if production:
        command.append("--prod")
    
    # Execute
    result = _run_deploy_command(command, timeout=600)  # 10 minutes for Vercel
    
    # Extract deployment URL
    deployment_url = _extract_vercel_url(result['output'])
    
    return {
        'success': result['success'],
        'output': result['output'],
        'deployment_url': deployment_url,
        'preview_url': deployment_url if not production else None,
        'is_production': production
    }


def link_vercel_project(project_name: str = "") -> Dict[str, any]:
    """
    Link the workspace to a Vercel project.
    
    Args:
        project_name: Optional project name to link to
        
    Returns:
        Dict with success and output
    """
    creds = SecretManager.validate_vercel_credentials()
    if not creds['valid']:
        return {
            'success': False,
            'output': f"Missing Vercel credentials: {', '.join(creds['missing'])}"
        }
    
    command = ["vercel", "link", "--yes"]
    
    if project_name:
        command.extend(["--project", project_name])
    
    return _run_deploy_command(command)


def link_supabase_project(project_ref: str = "") -> Dict[str, any]:
    """
    Link the workspace to a Supabase project.
    
    Args:
        project_ref: Optional project reference to link to.
                    If empty, uses SUPABASE_PROJECT_REF env var.
        
    Returns:
        Dict with success and output
    """
    creds = SecretManager.validate_supabase_credentials()
    if not creds['valid']:
        return {
            'success': False,
            'output': f"Missing Supabase credentials: {', '.join(creds['missing'])}"
        }
    
    ref = project_ref or SecretManager.get_supabase_project_ref()
    if not ref:
        return {
            'success': False,
            'output': "No project reference provided. Set SUPABASE_PROJECT_REF or pass project_ref."
        }
    
    command = ["supabase", "link", "--project-ref", ref]
    
    return _run_deploy_command(command)


def init_supabase_project() -> Dict[str, any]:
    """
    Initialize Supabase project in the workspace.
    
    Returns:
        Dict with success and output
    """
    command = ["supabase", "init"]
    return _run_deploy_command(command, timeout=60)


def get_deployment_status() -> Dict[str, any]:
    """
    Get current deployment status and credentials availability.
    
    Returns:
        Dict with platform statuses and available credentials
    """
    supabase_creds = SecretManager.validate_supabase_credentials()
    vercel_creds = SecretManager.validate_vercel_credentials()
    
    return {
        'supabase': {
            'ready': supabase_creds['valid'],
            'missing': supabase_creds['missing'],
            'project_ref': SecretManager.get_supabase_project_ref()
        },
        'vercel': {
            'ready': vercel_creds['valid'],
            'missing': vercel_creds['missing']
        }
    }
