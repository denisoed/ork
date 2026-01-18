"""
Tools for reading and parsing project_profile.yaml/json files.
"""

import os
import json
import yaml
from typing import Optional, Dict, Any, List
from orchestrator.tools.fs_tools import WORKSPACE_DIR, read_file

# Project profile structure
ProjectProfile = Dict[str, Any]

def _load_yaml(filepath: str) -> Optional[Dict[str, Any]]:
    """Load YAML file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading YAML file {filepath}: {e}")
        return None

def _load_json(filepath: str) -> Optional[Dict[str, Any]]:
    """Load JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading JSON file {filepath}: {e}")
        return None

def load_project_profile(project_root: Optional[str] = None) -> Optional[ProjectProfile]:
    """
    Load project_profile.yaml or project_profile.json from project root.
    
    Args:
        project_root: Path to project root (default: WORKSPACE_DIR)
        
    Returns:
        Project profile dict or None if not found/invalid
    """
    if project_root is None:
        project_root = WORKSPACE_DIR
    
    # Try YAML first, then JSON
    yaml_path = os.path.join(project_root, 'project_profile.yaml')
    json_path = os.path.join(project_root, 'project_profile.json')
    
    profile = None
    
    if os.path.exists(yaml_path):
        profile = _load_yaml(yaml_path)
    elif os.path.exists(json_path):
        profile = _load_json(json_path)
    else:
        return None
    
    if profile is None:
        return None
    
    # Validate and normalize structure
    return _validate_profile(profile)

def _validate_profile(profile: Dict[str, Any]) -> Optional[ProjectProfile]:
    """
    Validate and normalize project profile structure.
    
    Returns:
        Validated profile or None if invalid
    """
    if not isinstance(profile, dict):
        return None
    
    # Normalize structure
    normalized: ProjectProfile = {
        'build_commands': [],
        'test_commands': [],
        'run_commands': [],
        'healthcheck': None,
        'smoke_checks': []
    }
    
    # Build commands
    if 'build_commands' in profile:
        build_cmds = profile['build_commands']
        if isinstance(build_cmds, list):
            normalized['build_commands'] = [str(cmd) for cmd in build_cmds if cmd]
        elif isinstance(build_cmds, str):
            normalized['build_commands'] = [build_cmds]
    
    # Test commands
    if 'test_commands' in profile:
        test_cmds = profile['test_commands']
        if isinstance(test_cmds, list):
            normalized['test_commands'] = [str(cmd) for cmd in test_cmds if cmd]
        elif isinstance(test_cmds, str):
            normalized['test_commands'] = [test_cmds]
    
    # Run commands
    if 'run_commands' in profile:
        run_cmds = profile['run_commands']
        if isinstance(run_cmds, list):
            normalized['run_commands'] = [str(cmd) for cmd in run_cmds if cmd]
        elif isinstance(run_cmds, str):
            normalized['run_commands'] = [run_cmds]
    
    # Healthcheck
    if 'healthcheck' in profile and profile['healthcheck']:
        hc = profile['healthcheck']
        if isinstance(hc, dict):
            normalized['healthcheck'] = {
                'type': hc.get('type', 'url'),
                'value': str(hc.get('value', '')),
                'timeout': int(hc.get('timeout', 30))
            }
        elif isinstance(hc, str):
            # Simple string healthcheck treated as URL
            normalized['healthcheck'] = {
                'type': 'url',
                'value': hc,
                'timeout': 30
            }
    
    # Smoke checks
    if 'smoke_checks' in profile:
        smoke = profile['smoke_checks']
        if isinstance(smoke, list):
            normalized['smoke_checks'] = [str(cmd) for cmd in smoke if cmd]
        elif isinstance(smoke, str):
            normalized['smoke_checks'] = [smoke]
    
    return normalized

def has_project_profile(project_root: Optional[str] = None) -> bool:
    """
    Check if project_profile.yaml or project_profile.json exists.
    
    Args:
        project_root: Path to project root (default: WORKSPACE_DIR)
        
    Returns:
        True if profile exists
    """
    if project_root is None:
        project_root = WORKSPACE_DIR
    
    yaml_path = os.path.join(project_root, 'project_profile.yaml')
    json_path = os.path.join(project_root, 'project_profile.json')
    
    return os.path.exists(yaml_path) or os.path.exists(json_path)

def is_service_project(profile: ProjectProfile) -> bool:
    """
    Check if project is a service (has run_commands and healthcheck).
    
    Args:
        profile: Project profile
        
    Returns:
        True if project is a service
    """
    return (
        profile.get('run_commands') and 
        len(profile.get('run_commands', [])) > 0 and
        profile.get('healthcheck') is not None
    )



