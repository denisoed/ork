"""
Tools for working with spec-feature structure.
Handles reading/writing spec files, templates, and constitution.
"""

import os
import re
from typing import Tuple, List, Dict, Optional, Any
from pathlib import Path

# Get project root (parent of orchestrator directory)
PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_SPEC_PATH = PROJECT_ROOT / "spec"


def get_spec_path(spec_path: Optional[str] = None) -> Path:
    """Get absolute path to spec directory."""
    if spec_path:
        return Path(spec_path).resolve()
    return DEFAULT_SPEC_PATH.resolve()


def read_feature_instructions(spec_path: Optional[str] = None) -> str:
    """
    Read the main instruction file spec/feature.md.
    
    Args:
        spec_path: Optional custom path to spec directory
        
    Returns:
        Content of spec/feature.md
    """
    spec_dir = get_spec_path(spec_path)
    feature_file = spec_dir / "feature.md"
    
    if not feature_file.exists():
        raise FileNotFoundError(f"spec/feature.md not found at {feature_file}")
    
    with open(feature_file, "r", encoding="utf-8") as f:
        return f.read()


def read_all_constitution_files(spec_path: Optional[str] = None) -> str:
    """
    Read all constitution files from spec/constitution/.
    
    Args:
        spec_path: Optional custom path to spec directory
        
    Returns:
        Combined content of all constitution files
    """
    spec_dir = get_spec_path(spec_path)
    constitution_dir = spec_dir / "constitution"
    
    if not constitution_dir.exists():
        return ""
    
    constitution_files = []
    for file_path in sorted(constitution_dir.glob("*.md")):
        if file_path.name == "README.md":
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                constitution_files.append(f"# {file_path.name}\n\n{content}\n")
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}")
    
    return "\n---\n\n".join(constitution_files)


def read_template_file(template_name: str, spec_path: Optional[str] = None) -> str:
    """
    Read a template file from spec/core/.
    
    Args:
        template_name: Name of template file (e.g., 'spec.md', 'plan.md', 'tasks.md')
        spec_path: Optional custom path to spec directory
        
    Returns:
        Content of the template file
    """
    spec_dir = get_spec_path(spec_path)
    template_file = spec_dir / "core" / template_name
    
    if not template_file.exists():
        raise FileNotFoundError(f"Template {template_name} not found at {template_file}")
    
    with open(template_file, "r", encoding="utf-8") as f:
        return f.read()


def parse_run_tasks_intent(user_input: str) -> Optional[Tuple[str, str]]:
    """
    Parse RUN_TASKS intent from user input.
    
    Supports formats:
    - RUN spec/features/<feature-name>/tasks.md
    - RUN <feature-name>
    
    Args:
        user_input: User request string
        
    Returns:
        Tuple of (feature_name, tasks_path) if intent detected, None otherwise
    """
    user_input_lower = user_input.strip().upper()
    
    # Check if input starts with RUN
    if not user_input_lower.startswith("RUN"):
        return None
    
    # Extract the part after RUN
    rest = user_input[len("RUN"):].strip()
    
    # Pattern 1: RUN spec/features/<feature-name>/tasks.md
    pattern1 = re.search(r'spec[/\\]features[/\\]([^/\\]+)[/\\]tasks\.md', rest, re.IGNORECASE)
    if pattern1:
        feature_name = pattern1.group(1).strip()
        tasks_path = f"spec/features/{feature_name}/tasks.md"
        return feature_name, tasks_path
    
    # Pattern 2: RUN <feature-name> (simple format)
    # Extract feature name (everything after RUN, up to space or end)
    match = re.match(r'^([a-z0-9_-]+)', rest, re.IGNORECASE)
    if match:
        feature_name = match.group(1).strip()
        tasks_path = f"spec/features/{feature_name}/tasks.md"
        return feature_name, tasks_path
    
    return None


def parse_feature_request(user_input: str) -> Tuple[str, str]:
    """
    Parse feature request in format #feature-name# context.
    
    Args:
        user_input: User request string
        
    Returns:
        Tuple of (feature_name, context)
    """
    # Try to match format #feature-name# context
    match = re.search(r'#([^#]+)#\s*(.*)', user_input, re.DOTALL)
    if match:
        feature_name = match.group(1).strip()
        context = match.group(2).strip()
        return feature_name, context
    
    # If format not found, try to extract feature name from context
    # Look for common patterns like "create X", "implement X", "build X"
    patterns = [
        r'(?:create|implement|build|add|develop)\s+([a-z0-9-]+)',
        r'feature[:\s]+([a-z0-9-]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, user_input.lower())
        if match:
            feature_name = match.group(1).strip()
            # Clean up feature name
            feature_name = re.sub(r'[^a-z0-9-]', '-', feature_name)
            return feature_name, user_input
    
    # Default: use sanitized version of first few words
    words = re.findall(r'\w+', user_input.lower())[:3]
    feature_name = '-'.join(words) if words else "feature"
    return feature_name, user_input


def ensure_feature_directory(feature_name: str, spec_path: Optional[str] = None) -> bool:
    """
    Ensure spec/features/<feature-name>/ directory exists.
    
    Args:
        feature_name: Name of the feature
        spec_path: Optional custom path to spec directory
        
    Returns:
        True if directory exists or was created
    """
    spec_dir = get_spec_path(spec_path)
    feature_dir = spec_dir / "features" / feature_name
    
    try:
        feature_dir.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        print(f"Error creating feature directory {feature_dir}: {e}")
        return False


def read_spec_file(feature_name: str, file_type: str, spec_path: Optional[str] = None) -> str:
    """
    Read a spec file from spec/features/<feature-name>/.
    
    Args:
        feature_name: Name of the feature
        file_type: Type of file ('spec', 'plan', 'tasks', 'clarifications', 'questions', 'verify-report')
        spec_path: Optional custom path to spec directory
        
    Returns:
        Content of the file, or empty string if not found
    """
    spec_dir = get_spec_path(spec_path)
    
    # Map file_type to actual filename
    file_map = {
        'spec': 'spec.md',
        'plan': 'plan.md',
        'tasks': 'tasks.md',
        'clarifications': 'clarifications.md',
        'questions': 'questions.md',
        'verify-report': 'verify-report.md',
        'summary': 'summary.md',
        'validation-report': 'validation_report.md',
        'risks-debt': 'risks_debt.md',
    }
    
    filename = file_map.get(file_type, f"{file_type}.md")
    file_path = spec_dir / "features" / feature_name / filename
    
    if not file_path.exists():
        return ""
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return ""


def write_spec_file(feature_name: str, file_type: str, content: str, spec_path: Optional[str] = None) -> bool:
    """
    Write a spec file to spec/features/<feature-name>/.
    
    Args:
        feature_name: Name of the feature
        file_type: Type of file ('spec', 'plan', 'tasks', 'clarifications', 'questions', 'verify-report')
        content: Content to write
        spec_path: Optional custom path to spec directory
        
    Returns:
        True if successful
    """
    spec_dir = get_spec_path(spec_path)
    
    # Ensure feature directory exists
    if not ensure_feature_directory(feature_name, spec_path):
        return False
    
    # Map file_type to actual filename
    file_map = {
        'spec': 'spec.md',
        'plan': 'plan.md',
        'tasks': 'tasks.md',
        'clarifications': 'clarifications.md',
        'questions': 'questions.md',
        'verify-report': 'verify-report.md',
        'summary': 'summary.md',
        'validation-report': 'validation_report.md',
        'risks-debt': 'risks_debt.md',
    }
    
    filename = file_map.get(file_type, f"{file_type}.md")
    file_path = spec_dir / "features" / feature_name / filename
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"Error writing {file_path}: {e}")
        return False


def list_features(spec_path: Optional[str] = None) -> List[str]:
    """
    List all features in spec/features/.
    
    Args:
        spec_path: Optional custom path to spec directory
        
    Returns:
        List of feature names
    """
    spec_dir = get_spec_path(spec_path)
    features_dir = spec_dir / "features"
    
    if not features_dir.exists():
        return []
    
    features = []
    for item in features_dir.iterdir():
        if item.is_dir():
            features.append(item.name)
    
    return sorted(features)


def check_spec_structure(feature_name: str, spec_path: Optional[str] = None) -> Dict[str, bool]:
    """
    Check which spec files exist for a feature.
    
    Args:
        feature_name: Name of the feature
        spec_path: Optional custom path to spec directory
        
    Returns:
        Dictionary mapping file types to existence status
    """
    spec_dir = get_spec_path(spec_path)
    feature_dir = spec_dir / "features" / feature_name
    
    files = {
        'spec': (feature_dir / "spec.md").exists(),
        'plan': (feature_dir / "plan.md").exists(),
        'tasks': (feature_dir / "tasks.md").exists(),
        'clarifications': (feature_dir / "clarifications.md").exists(),
        'questions': (feature_dir / "questions.md").exists(),
        'verify-report': (feature_dir / "verify-report.md").exists(),
        'trace': (feature_dir / "trace.json").exists(),
    }
    
    return files


def read_trace_json(feature_name: str, spec_path: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """
    Read trace.json file from spec/features/<feature-name>/.
    
    Args:
        feature_name: Name of the feature
        spec_path: Optional custom path to spec directory
        
    Returns:
        List of trace records, or None if file doesn't exist or is invalid
    """
    import json
    
    spec_dir = get_spec_path(spec_path)
    trace_file = spec_dir / "features" / feature_name / "trace.json"
    
    if not trace_file.exists():
        return None
    
    try:
        with open(trace_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        print(f"Error reading trace.json: {e}")
        return None


def write_trace_json(feature_name: str, trace_data: List[Dict[str, Any]], spec_path: Optional[str] = None) -> bool:
    """
    Write trace.json file to spec/features/<feature-name>/.
    
    Args:
        feature_name: Name of the feature
        trace_data: List of trace records (each with req_id, implementation, verification, evidence, status)
        spec_path: Optional custom path to spec directory
        
    Returns:
        True if successful
    """
    import json
    
    spec_dir = get_spec_path(spec_path)
    
    # Ensure feature directory exists
    if not ensure_feature_directory(feature_name, spec_path):
        return False
    
    trace_file = spec_dir / "features" / feature_name / "trace.json"
    
    try:
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error writing trace.json: {e}")
        return False
