"""
Tools for managing validation artifacts and logs.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from orchestrator.tools.fs_tools import WORKSPACE_DIR

ARTIFACTS_DIR = "artifacts"
VALIDATION_DIR = "validation"

def ensure_artifacts_dir(project_root: Optional[str] = None) -> str:
    """
    Ensure artifacts/validation/ directory exists in project root.
    
    Args:
        project_root: Path to project root (default: WORKSPACE_DIR)
        
    Returns:
        Path to validation artifacts directory
    """
    if project_root is None:
        project_root = WORKSPACE_DIR
    
    artifacts_path = os.path.join(project_root, ARTIFACTS_DIR)
    validation_path = os.path.join(artifacts_path, VALIDATION_DIR)
    
    os.makedirs(validation_path, exist_ok=True)
    
    return validation_path

def save_command_log(
    command: str,
    output: str,
    exit_code: Optional[int] = None,
    log_type: str = "command",
    project_root: Optional[str] = None
) -> str:
    """
    Save command output to log file.
    
    Args:
        command: Command that was executed
        output: Command output
        exit_code: Exit code (if available)
        log_type: Type of log (build, test, healthcheck, etc.)
        project_root: Path to project root (default: WORKSPACE_DIR)
        
    Returns:
        Path to saved log file
    """
    validation_dir = ensure_artifacts_dir(project_root)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"{log_type}_{timestamp}.log"
    log_path = os.path.join(validation_dir, log_filename)
    
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(f"Command: {command}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        if exit_code is not None:
            f.write(f"Exit Code: {exit_code}\n")
        f.write("-" * 80 + "\n")
        f.write(output)
    
    return log_path

def save_validation_summary(
    summary: Dict[str, Any],
    project_root: Optional[str] = None
) -> str:
    """
    Save validation summary as JSON.
    
    Args:
        summary: Validation summary dict
        project_root: Path to project root (default: WORKSPACE_DIR)
        
    Returns:
        Path to saved summary file
    """
    validation_dir = ensure_artifacts_dir(project_root)
    
    summary['timestamp'] = datetime.now().isoformat()
    summary_path = os.path.join(validation_dir, 'summary.json')
    
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    return summary_path

def append_validation_log(
    message: str,
    log_type: str = "validation",
    project_root: Optional[str] = None
) -> str:
    """
    Append message to validation log file.
    
    Args:
        message: Message to append
        log_type: Type of log (default: validation)
        project_root: Path to project root (default: WORKSPACE_DIR)
        
    Returns:
        Path to log file
    """
    validation_dir = ensure_artifacts_dir(project_root)
    
    log_path = os.path.join(validation_dir, f"{log_type}.log")
    
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().isoformat()}] {message}\n")
    
    return log_path

def get_validation_summary(project_root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get validation summary from summary.json.
    
    Args:
        project_root: Path to project root (default: WORKSPACE_DIR)
        
    Returns:
        Summary dict or None if not found
    """
    if project_root is None:
        project_root = WORKSPACE_DIR
    
    summary_path = os.path.join(
        project_root, 
        ARTIFACTS_DIR, 
        VALIDATION_DIR, 
        'summary.json'
    )
    
    if not os.path.exists(summary_path):
        return None
    
    try:
        with open(summary_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading validation summary: {e}")
        return None


