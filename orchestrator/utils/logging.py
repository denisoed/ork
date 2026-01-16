"""
Logging utility for the orchestrator.
Provides file and console logging with structured output.
"""

import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

# Create logs directory
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")

def ensure_logs_dir():
    """Ensure logs directory exists."""
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)

def get_logger(name: str, log_to_file: bool = True) -> logging.Logger:
    """
    Get a configured logger instance.
    
    Args:
        name: Logger name (typically module name)
        log_to_file: Whether to also log to file
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger  # Already configured
    
    logger.setLevel(logging.DEBUG)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler
    if log_to_file:
        ensure_logs_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(LOGS_DIR, f"orchestrator_{timestamp}.log")
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger

class ExecutionLogger:
    """
    Structured logger for tracking execution history.
    Saves execution data as JSON for analysis.
    """
    
    def __init__(self, session_id: Optional[str] = None):
        ensure_logs_dir()
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(LOGS_DIR, f"execution_{self.session_id}.json")
        self.events = []
        
    def log_event(self, event_type: str, node: str, data: Dict[str, Any]):
        """Log a structured event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "node": node,
            "data": data
        }
        self.events.append(event)
        self._save()
        
    def log_task_start(self, node: str, task_id: str, description: str):
        """Log task start."""
        self.log_event("task_start", node, {
            "task_id": task_id,
            "description": description
        })
        
    def log_task_complete(self, node: str, task_id: str, success: bool, message: str = ""):
        """Log task completion."""
        self.log_event("task_complete", node, {
            "task_id": task_id,
            "success": success,
            "message": message
        })
        
    def log_error(self, node: str, error: str, task_id: Optional[str] = None):
        """Log an error."""
        self.log_event("error", node, {
            "task_id": task_id,
            "error": error
        })
        
    def log_token_usage(self, node: str, input_tokens: int, output_tokens: int):
        """Log token usage."""
        self.log_event("token_usage", node, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens
        })
        
    def _save(self):
        """Save events to file."""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "session_id": self.session_id,
                    "events": self.events
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Failed to save execution log: {e}")
            
    def get_summary(self) -> Dict[str, Any]:
        """Get execution summary."""
        total_tokens = sum(
            e['data'].get('total_tokens', 0) 
            for e in self.events 
            if e['type'] == 'token_usage'
        )
        
        task_starts = [e for e in self.events if e['type'] == 'task_start']
        task_completes = [e for e in self.events if e['type'] == 'task_complete']
        errors = [e for e in self.events if e['type'] == 'error']
        
        successful = len([e for e in task_completes if e['data'].get('success')])
        failed = len([e for e in task_completes if not e['data'].get('success')])
        
        return {
            "session_id": self.session_id,
            "total_events": len(self.events),
            "tasks_started": len(task_starts),
            "tasks_completed": successful,
            "tasks_failed": failed,
            "total_errors": len(errors),
            "total_tokens": total_tokens
        }

