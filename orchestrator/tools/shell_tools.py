import subprocess
import os
import re
import shlex
from typing import Tuple, Optional, List
from orchestrator.tools.fs_tools import WORKSPACE_DIR, ensure_workspace
from orchestrator.tools.validation_artifacts import save_command_log

# Whitelist of allowed commands for deployment operations
ALLOWED_DEPLOY_COMMANDS = [
    r'^supabase\s+(db\s+push|functions\s+deploy|migrations\s+up|link)',
    r'^vercel\s+(deploy|--prod|--preview|link)',
    r'^npm\s+(install|run\s+build|run\s+test|ci)',
    r'^npx\s+(eslint|typescript|next|create-next-app)',
    r'^git\s+(add|commit|status|diff|init)',
    r'^node\s+',
    r'^pnpm\s+(install|run|build)',
    r'^yarn\s+(install|run|build)',
]

# General allowlist for non-deploy commands
ALLOWED_COMMANDS = [
    r'^ls(\s+.*)?$',
    r'^pwd$',
    r'^cat\s+.+$',
    r'^rg(\s+.*)?$',
    r'^mkdir\s+.+$',
    r'^touch\s+.+$',
    r'^cp\s+.+$',
    r'^mv\s+.+$',
    r'^npm\s+(install|ci|run\s+[\w:-]+)$',
    r'^npx\s+(eslint|typescript|tsc|next|create-next-app)(\s+.*)?$',
    r'^pnpm\s+(install|run\s+[\w:-]+|build)$',
    r'^yarn\s+(install|run\s+[\w:-]+|build)$',
    r'^git\s+(add|commit|status|diff|init)$',
]

# Extended blacklist of dangerous patterns
DANGEROUS_PATTERNS = [
    r'rm\s+-rf\s+[/~]',           # rm -rf with root or home paths
    r'rm\s+-rf\s+\.\.',           # rm -rf with parent directory
    r'sudo\s+',                    # sudo commands
    r':\(\)\s*\{',                 # fork bomb
    r'>\s*/dev/',                  # redirect to system devices
    r'\|\s*bash\s*$',              # pipe to bash
    r'\|\s*sh\s*$',                # pipe to sh
    r'curl\s+.*\s+\|\s*(bash|sh)', # curl | bash
    r'wget\s+.*\s+\|\s*(bash|sh)', # wget | bash
    r'chmod\s+[0-7]{3,4}\s+/',     # chmod on system paths
    r'chown\s+.*\s+/',             # chown on system paths
    r'echo\s+.*\s+>\s*/etc/',      # write to /etc
    r'echo\s+.*\s+>\s*/var/',      # write to /var
    r'mkfs\.',                     # filesystem creation
    r'dd\s+if=',                   # disk dump
    r'>\s*/dev/sd',                # write to disk devices
    r'eval\s+',                    # eval commands
    r'\$\(',                       # command substitution (potential injection)
    r'`.*`',                       # backtick command substitution
]

# Simple blacklist for exact matches
EXACT_BLACKLIST = [
    "rm -rf /",
    "rm -rf ~",
    ":(){ :|:& };:",
]

# Allowed directories for command execution (only workspace)
ALLOWED_DIRECTORIES = [WORKSPACE_DIR]


def _validate_no_newlines(text: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that text does not contain newline or carriage return characters.
    
    Args:
        text: Text to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if '\n' in text or '\r' in text:
        return False, "Newline or carriage return characters are not allowed"
    return True, None


def _validate_no_newlines_in_args(args: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate that no argument contains newline or carriage return characters.
    
    Args:
        args: List of arguments to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    for arg in args:
        is_valid, error_msg = _validate_no_newlines(arg)
        if not is_valid:
            return False, error_msg
    return True, None


def _check_command_allowlist(command_name: str, full_command: str = None, is_deploy: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Check if command is in allowlist.
    
    Args:
        command_name: Command name (first argument) to check
        full_command: Full command string to check against patterns (optional)
        is_deploy: Whether this is a deployment command
        
    Returns:
        Tuple of (is_allowed, error_message)
    """
    command_name = command_name.strip()
    
    # Use full command if provided, otherwise just command name
    command_to_check = full_command.strip() if full_command else command_name
    
    # Check deploy commands allowlist
    if is_deploy:
        for pattern in ALLOWED_DEPLOY_COMMANDS:
            if re.match(pattern, command_to_check, re.IGNORECASE):
                return True, None
        # Also check if command name matches base pattern
        for pattern in ALLOWED_DEPLOY_COMMANDS:
            # Extract base command from pattern
            pattern_match = re.match(r'\^?([a-zA-Z0-9_-]+)', pattern)
            if pattern_match and pattern_match.group(1) == command_name:
                return True, None
    
    # Check general commands allowlist
    for pattern in ALLOWED_COMMANDS:
        if re.match(pattern, command_to_check, re.IGNORECASE):
            return True, None
        # Also check if command name matches base pattern
        pattern_match = re.match(r'\^?([a-zA-Z0-9_-]+)', pattern)
        if pattern_match and pattern_match.group(1) == command_name:
            return True, None
    
    return False, f"Command '{command_name}' is not in allowlist"


def _check_directory_allowlist(cwd: str) -> Tuple[bool, Optional[str]]:
    """
    Check if directory is in allowlist.
    
    Args:
        cwd: Directory path to check
        
    Returns:
        Tuple of (is_allowed, error_message)
    """
    workspace_root = os.path.abspath(WORKSPACE_DIR)
    cwd_abs = os.path.abspath(cwd)
    
    # Check if cwd is in allowed directories
    if cwd_abs == workspace_root:
        return True, None
    
    # Also check if cwd is within workspace (subdirectory)
    try:
        common_path = os.path.commonpath([workspace_root, cwd_abs])
        if common_path == workspace_root:
            return True, None
    except ValueError:
        # Different drive on Windows or no common path
        pass
    
    return False, f"Directory '{cwd}' is not in allowlist (only {WORKSPACE_DIR} allowed)"


def is_command_safe(command: str) -> Tuple[bool, Optional[str]]:
    """
    Validates if a command is safe to execute.
    
    Args:
        command: The shell command to validate
        
    Returns:
        Tuple of (is_safe, error_message)
    """
    command_stripped = command.strip()
    
    # Block shell metacharacters to reduce injection surface
    if re.search(r'[;&|<>]', command_stripped):
        return False, "Command blocked: shell metacharacters are not allowed"
    
    # Check exact blacklist matches
    for blocked in EXACT_BLACKLIST:
        if blocked in command_stripped:
            return False, f"Command blocked: contains dangerous pattern '{blocked}'"
    
    # Check dangerous regex patterns
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command_stripped, re.IGNORECASE):
            return False, f"Command blocked: matches dangerous pattern"
    
    # Check for path traversal attempts
    if '..' in command_stripped:
        # Allow .. only within workspace context
        normalized = os.path.normpath(command_stripped)
        if normalized.startswith('..') or '/../' in command_stripped:
            return False, "Command blocked: path traversal attempt detected"
    
    # Check for absolute paths outside workspace
    abs_path_match = re.search(r'(?<!\w)/(?:etc|var|usr|bin|sbin|root|home)/', command_stripped)
    if abs_path_match:
        return False, "Command blocked: attempts to access system directories"
    
    # Reject absolute paths outside workspace
    workspace_root = os.path.abspath(WORKSPACE_DIR)
    try:
        tokens = shlex.split(command_stripped)
    except ValueError:
        return False, "Command blocked: invalid shell syntax"
    
    for token in tokens:
        candidate = None
        if token.startswith("/"):
            candidate = token
        elif "=/" in token:
            candidate = token.split("=", 1)[1]
        elif token.startswith("~"):
            return False, "Command blocked: home-relative paths are not allowed"
        
        if candidate:
            abs_path = os.path.abspath(candidate)
            if os.path.commonpath([workspace_root, abs_path]) != workspace_root:
                return False, "Command blocked: absolute paths must stay within workspace"
    
    # Allowlist enforcement
    if not is_deploy_command(command_stripped):
        allowed = any(re.match(pattern, command_stripped, re.IGNORECASE) for pattern in ALLOWED_COMMANDS)
        if not allowed:
            return False, "Command blocked: not in allowlist"
    
    return True, None


def is_deploy_command(command: str) -> bool:
    """
    Check if command is a whitelisted deployment command.
    
    Args:
        command: The shell command to check
        
    Returns:
        True if command matches deployment whitelist
    """
    command_stripped = command.strip()
    
    for pattern in ALLOWED_DEPLOY_COMMANDS:
        if re.match(pattern, command_stripped, re.IGNORECASE):
            return True
    
    return False


def run_shell_command(command: str, timeout: int = 120, require_confirmation: bool = False) -> str:
    """
    Executes a shell command in the workspace directory with security checks.
    
    Args:
        command: The shell command to execute
        timeout: Timeout in seconds (default 120, extended to 300 for deploy commands)
        require_confirmation: If True, blocks execution (placeholder for future interactive mode)
        
    Returns:
        Command output or error message
    """
    ensure_workspace()
    
    # 1. Check for \n/\r in command string
    is_valid, error_msg = _validate_no_newlines(command)
    if not is_valid:
        error_msg = f"Error: {error_msg}"
        save_command_log(command, error_msg, exit_code=-1, log_type="command")
        return error_msg
    
    # 2. Parse command string into list of arguments
    try:
        args = shlex.split(command)
    except ValueError as e:
        error_msg = f"Error: Command blocked: invalid shell syntax - {str(e)}"
        save_command_log(command, error_msg, exit_code=-1, log_type="command")
        return error_msg
    
    if not args:
        error_msg = "Error: Empty command"
        save_command_log(command, error_msg, exit_code=-1, log_type="command")
        return error_msg
    
    # 3. Check for \n/\r in each argument
    is_valid, error_msg = _validate_no_newlines_in_args(args)
    if not is_valid:
        error_msg = f"Error: {error_msg}"
        save_command_log(command, error_msg, exit_code=-1, log_type="command")
        return error_msg
    
    # 4. Check command allowlist (args[0] is the command name)
    command_name = args[0]
    is_deploy = is_deploy_command(command)
    is_allowed, error_msg = _check_command_allowlist(command_name, full_command=command, is_deploy=is_deploy)
    if not is_allowed:
        error_msg = f"Error: {error_msg}"
        save_command_log(command, error_msg, exit_code=-1, log_type="command")
        return error_msg
    
    # 5. Check directory allowlist (only WORKSPACE_DIR allowed)
    is_allowed, error_msg = _check_directory_allowlist(WORKSPACE_DIR)
    if not is_allowed:
        error_msg = f"Error: {error_msg}"
        save_command_log(command, error_msg, exit_code=-1, log_type="command")
        return error_msg
    
    # Check if this is a deploy command and extend timeout
    if is_deploy:
        timeout = max(timeout, 300)  # 5 minutes for deploy commands
    
    # Production deployment confirmation check
    if require_confirmation:
        if any(prod_flag in command.lower() for prod_flag in ['--prod', '--production']):
            error_msg = "Error: Production deployment requires explicit confirmation. Use --auto-deploy flag."
            save_command_log(command, error_msg, exit_code=-1, log_type="command")
            return error_msg
    
    try:
        # 6. Execute command with shell=False
        result = subprocess.run(
            args,
            cwd=WORKSPACE_DIR,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, 'PATH': os.environ.get('PATH', '')}
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"
            
        if result.returncode != 0:
            output += f"\n[EXIT CODE] {result.returncode}"
        
        # 7. Always log the command execution
        save_command_log(command, output, exit_code=result.returncode, log_type="command")
            
        return output
        
    except subprocess.TimeoutExpired:
        error_msg = f"Error: Command timed out after {timeout} seconds."
        save_command_log(command, error_msg, exit_code=-1, log_type="command")
        return error_msg
    except Exception as e:
        error_msg = f"Error executing command: {str(e)}"
        save_command_log(command, error_msg, exit_code=-1, log_type="command")
        return error_msg
