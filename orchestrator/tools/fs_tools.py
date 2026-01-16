import os
from typing import Optional, List

# Security: Restrict file operations to the current working directory sub-folder "workspace"
# to prevent agents from messing with the orchestrator itself or system files.
WORKSPACE_DIR = os.path.join(os.getcwd(), "workspace")

def ensure_workspace():
    if not os.path.exists(WORKSPACE_DIR):
        os.makedirs(WORKSPACE_DIR)

def get_safe_path(filepath: str) -> str:
    ensure_workspace()
    # Normalize path and join with workspace
    # Remove leading slash to treat as relative
    if filepath.startswith("/"):
        filepath = filepath[1:]
    
    workspace_root = os.path.abspath(WORKSPACE_DIR)
    full_path = os.path.abspath(os.path.join(workspace_root, filepath))
    
    # Check if path is within workspace
    if os.path.commonpath([workspace_root, full_path]) != workspace_root:
        raise PermissionError(f"Access denied: Path {filepath} is outside the workspace.")
    
    return full_path

def read_file(filepath: str) -> str:
    """
    Reads the content of a file.
    Args:
        filepath: Relative path to the file within the workspace.
    """
    try:
        path = get_safe_path(filepath)
        if not os.path.exists(path):
            return f"Error: File {filepath} does not exist."
        
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {filepath}: {str(e)}"

def write_file(filepath: str, content: str) -> str:
    """
    Writes content to a file, creating directories if needed.
    Args:
        filepath: Relative path to the file within the workspace.
        content: Text content to write.
    """
    try:
        path = get_safe_path(filepath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            
        return f"Successfully wrote to {filepath}"
    except Exception as e:
        return f"Error writing file {filepath}: {str(e)}"

def list_files(directory: str = ".") -> str:
    """
    Lists files in a directory.
    """
    try:
        path = get_safe_path(directory)
        if not os.path.exists(path):
            return f"Error: Directory {directory} does not exist."

        files = []
        for root, _, filenames in os.walk(path):
            for filename in filenames:
                rel_path = os.path.relpath(os.path.join(root, filename), WORKSPACE_DIR)
                files.append(rel_path)
        
        return "\n".join(files) if files else "Directory is empty."
    except Exception as e:
        print(e)
        return f"Error listing files: {str(e)}"
