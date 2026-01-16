from typing import TypedDict, List, Dict, Optional, Any, Annotated, Literal
from langgraph.graph.message import add_messages
import operator
import uuid
from datetime import datetime

class Task(TypedDict):
    """
    Represents a single unit of work in the system.
    """
    id: str
    description: str
    assigned_role: str  # 'ui_agent', 'db_agent', 'logic_agent', 'deploy_agent'
    status: str         # 'pending', 'running', 'completed', 'failed'
    dependencies: List[str] # List of Task IDs this task depends on
    retry_count: int
    feedback: Optional[str] # Error details if failed, or previous attempt feedback

def merge_tasks(current: List[Task], updates: List[Task]) -> List[Task]:
    current = current or []
    updates = updates or []
    
    # Map current tasks by ID
    task_map = {t['id']: t for t in current}
    
    # Apply updates
    for t in updates:
        task_map[t['id']] = t
        
    # Reconstruct list maintaining order
    result_list = []
    
    # 1. Add known tasks in original order (updated if needed)
    for t in current:
        result_list.append(task_map[t['id']])
        
    # 2. Add truly new tasks
    existing_ids = set(t['id'] for t in current)
    for t in updates:
        if t['id'] not in existing_ids:
            result_list.append(t)
            
    return result_list

def reduce_max(left: Optional[int], right: Optional[int]) -> int:
    left = left if left is not None else 0
    right = right if right is not None else 0
    return max(left, right)

class TokenUsage(TypedDict):
    input_tokens: int
    output_tokens: int
    total_tokens: int

def reduce_usage(left: Optional[TokenUsage], right: Optional[TokenUsage]) -> TokenUsage:
    left = left or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    right = right or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    return {
        "input_tokens": left.get("input_tokens", 0) + right.get("input_tokens", 0),
        "output_tokens": left.get("output_tokens", 0) + right.get("output_tokens", 0),
        "total_tokens": left.get("total_tokens", 0) + right.get("total_tokens", 0)
    }


def merge_deployment_urls(current: Optional[Dict[str, str]], updates: Optional[Dict[str, str]]) -> Dict[str, str]:
    """
    Merge deployment URLs from different deploy tasks.
    Updates override current values for the same keys.
    """
    current = current or {}
    updates = updates or {}
    return {**current, **updates}


def merge_lists(current: Optional[List[Any]], updates: Optional[List[Any]]) -> List[Any]:
    """
    Merge lists by appending updates to current, removing duplicates.
    For questions and evidence, we maintain unique items by ID.
    """
    current = current or []
    updates = updates or []
    
    if not updates:
        return current
    
    # For dict-based lists (questions, evidence), merge by ID
    if current and isinstance(current[0], dict) and 'id' in current[0]:
        current_dict = {item['id']: item for item in current}
        for item in updates:
            if isinstance(item, dict) and 'id' in item:
                current_dict[item['id']] = item
        return list(current_dict.values())
    
    # For simple lists (acceptance_criteria), append and dedupe
    result = list(current)
    for item in updates:
        if item not in result:
            result.append(item)
    return result


# Phase enum type
Phase = Literal[
    "INTAKE",
    "SPEC_DRAFT",
    "SPEC_REVIEW",
    "QUESTIONS_PENDING",
    "SPEC_APPROVED",
    "EXEC_PLANNED",
    "EXECUTING",
    "IMPL_REVIEW",
    "VALIDATING",
    "TRACE_VALIDATION",
    "DONE",
    "FAILED",
    "NEEDS_USER_DECISION"
]

# Transition graph: from_phase -> list of allowed to_phases
PHASE_TRANSITIONS: Dict[str, List[str]] = {
    "INTAKE": ["SPEC_DRAFT"],
    "SPEC_DRAFT": ["SPEC_REVIEW", "QUESTIONS_PENDING"],
    "SPEC_REVIEW": ["SPEC_APPROVED", "QUESTIONS_PENDING", "SPEC_DRAFT"],
    "QUESTIONS_PENDING": ["SPEC_DRAFT", "NEEDS_USER_DECISION"],
    "SPEC_APPROVED": ["EXEC_PLANNED"],
    "EXEC_PLANNED": ["EXECUTING"],
    "EXECUTING": ["IMPL_REVIEW"],
    "IMPL_REVIEW": ["VALIDATING", "EXECUTING"],
    "VALIDATING": ["TRACE_VALIDATION", "EXECUTING"],
    "TRACE_VALIDATION": ["DONE", "EXECUTING"],
    "FAILED": [],  # Can transition from any phase, but can't transition to specific phases programmatically
    "NEEDS_USER_DECISION": [],  # Can transition from any phase, but can't transition to specific phases programmatically
    "DONE": []  # Terminal state
}

# Node to phase mapping: which phases allow entering specific nodes
NODE_PHASES: Dict[str, List[str]] = {
    "spec_planner": ["INTAKE", "QUESTIONS_PENDING", "EXEC_PLANNED"],  # EXEC_PLANNED for RUN_TASKS intent
    "spec_reviewer": ["SPEC_DRAFT"],
    "supervisor": ["SPEC_APPROVED", "EXEC_PLANNED", "EXECUTING", "IMPL_REVIEW"],
    "dispatcher": ["EXEC_PLANNED", "EXECUTING", "IMPL_REVIEW"],
    "final_validator": ["EXECUTING"]
}


def is_valid_transition(from_phase: str, to_phase: str) -> bool:
    """
    Check if transition from one phase to another is valid.
    
    Args:
        from_phase: Current phase
        to_phase: Target phase
        
    Returns:
        True if transition is valid, False otherwise
    """
    if from_phase not in PHASE_TRANSITIONS:
        return False
    
    allowed_transitions = PHASE_TRANSITIONS[from_phase]
    
    # FAILED and NEEDS_USER_DECISION can transition to any phase (recovery)
    if from_phase in ["FAILED", "NEEDS_USER_DECISION"]:
        return True
    
    # DONE is terminal
    if from_phase == "DONE":
        return False
    
    return to_phase in allowed_transitions


def get_allowed_next_phases(current_phase: str) -> List[str]:
    """
    Get list of allowed next phases from current phase.
    
    Args:
        current_phase: Current phase
        
    Returns:
        List of allowed next phases
    """
    if current_phase not in PHASE_TRANSITIONS:
        return []
    
    allowed = PHASE_TRANSITIONS[current_phase]
    
    # FAILED and NEEDS_USER_DECISION can transition to any phase
    if current_phase in ["FAILED", "NEEDS_USER_DECISION"]:
        # Return all phases except DONE (unless explicitly requested)
        all_phases = [
            "INTAKE", "SPEC_DRAFT", "SPEC_REVIEW", "QUESTIONS_PENDING",
            "SPEC_APPROVED", "EXEC_PLANNED", "EXECUTING", "IMPL_REVIEW",
            "VALIDATING", "TRACE_VALIDATION", "DONE", "FAILED", "NEEDS_USER_DECISION"
        ]
        return all_phases
    
    return allowed


def can_enter_node(node_name: str, current_phase: str) -> bool:
    """
    Check if node can be entered from current phase.
    
    Args:
        node_name: Name of the node to enter
        current_phase: Current phase
        
    Returns:
        True if node can be entered, False otherwise
    """
    if node_name not in NODE_PHASES:
        # Unknown node - allow by default (backward compatibility)
        return True
    
    allowed_phases = NODE_PHASES[node_name]
    
    # FAILED and NEEDS_USER_DECISION can enter any node (recovery)
    if current_phase in ["FAILED", "NEEDS_USER_DECISION"]:
        return True
    
    return current_phase in allowed_phases


def add_open_question(
    questions: List[Dict[str, Any]],
    question: str,
    options: Optional[List[str]] = None
) -> str:
    """
    Add an open question to the list and return its ID.
    
    Args:
        questions: Current list of questions
        question: Question text
        options: Optional list of answer options
        
    Returns:
        Generated question ID
    """
    question_id = str(uuid.uuid4())
    question_dict: Dict[str, Any] = {
        "id": question_id,
        "question": question,
        "status": "open",
    }
    if options:
        question_dict["options"] = options
    
    questions.append(question_dict)
    return question_id


def answer_question(
    questions: List[Dict[str, Any]],
    question_id: str,
    answer: str
) -> bool:
    """
    Answer a question by ID.
    
    Args:
        questions: List of questions
        question_id: ID of question to answer
        answer: Answer text
        
    Returns:
        True if question was found and answered, False otherwise
    """
    for q in questions:
        if q.get("id") == question_id:
            q["status"] = "answered"
            q["answer"] = answer
            return True
    return False


def all_questions_answered(questions: Optional[List[Dict[str, Any]]]) -> bool:
    """
    Check if all questions are answered.
    
    Args:
        questions: List of questions
        
    Returns:
        True if all questions are answered or no questions exist, False otherwise
    """
    if not questions:
        return True
    
    return all(q.get("status") == "answered" for q in questions)


def add_evidence(
    evidence_list: List[Dict[str, Any]],
    evidence_type: str,
    requirement_id: Optional[str] = None,
    command: Optional[str] = None,
    output_path: Optional[str] = None,
    status: str = "pending"
) -> str:
    """
    Add evidence to the list and return its ID.
    
    Args:
        evidence_list: Current list of evidence
        evidence_type: Type of evidence (e.g., "test_result", "file_created", "command_output")
        requirement_id: Optional ID of requirement this evidence satisfies
        command: Optional command that was executed
        output_path: Optional path to output file
        status: Status of evidence (default: "pending")
        
    Returns:
        Generated evidence ID
    """
    evidence_id = str(uuid.uuid4())
    evidence_dict: Dict[str, Any] = {
        "id": evidence_id,
        "type": evidence_type,
        "status": status,
        "created_at": datetime.now().isoformat()
    }
    
    if requirement_id:
        evidence_dict["requirement_id"] = requirement_id
    if command:
        evidence_dict["command"] = command
    if output_path:
        evidence_dict["output_path"] = output_path
    
    evidence_list.append(evidence_dict)
    return evidence_id


def update_evidence_status(
    evidence_list: List[Dict[str, Any]],
    evidence_id: str,
    status: str
) -> bool:
    """
    Update status of evidence by ID.
    
    Args:
        evidence_list: List of evidence
        evidence_id: ID of evidence to update
        status: New status
        
    Returns:
        True if evidence was found and updated, False otherwise
    """
    for ev in evidence_list:
        if ev.get("id") == evidence_id:
            ev["status"] = status
            ev["updated_at"] = datetime.now().isoformat()
            return True
    return False


class SharedState(TypedDict):
    """
    Global state shared across all nodes in the graph.
    """
    # Chat history with the user and internal monologues
    messages: Annotated[List[Any], add_messages]
    
    # The master plan generated by the Supervisor
    # Uses a custom reducer to allow parallel updates from different workers
    tasks_queue: Annotated[List[Task], merge_tasks]
    
    # Current snapshot of the file system (to avoid re-reading unchanged files)
    # Mapping: "path/to/file" -> "file_hash" or concise summary
    files_snapshot: Dict[str, str]
    
    # Accumulated error logs for analysis
    error_logs: List[Dict[str, Any]]
    
    # Global retry counters to prevent infinite loops (Graph recursion limit)
    recursion_depth: Annotated[int, reduce_max]
    
    # Token usage tracking
    token_usage: Annotated[TokenUsage, reduce_usage]
    
    # Deployment URLs collected from deploy tasks
    # Keys: 'vercel_preview', 'vercel_production', 'supabase_project', 'supabase_function'
    deployment_urls: Annotated[Dict[str, str], merge_deployment_urls]
    
    # spec-feature related fields
    spec_path: str  # Path to spec directory (default: 'spec/')
    feature_name: Optional[str]  # Current feature name extracted from #feature# format
    
    # State machine fields
    phase: Phase  # Current phase of the process
    feature_id: Optional[str]  # Feature/work ID for grouping artifacts
    
    # Questions and answers
    open_questions: Annotated[List[Dict[str, Any]], merge_lists]  # Structured questions: {id, question, options?, status: open|answered, answer?}
    
    # Acceptance criteria and evidence
    acceptance_criteria: Annotated[List[str], merge_lists]  # Criteria for "works"
    evidence: Annotated[List[Dict[str, Any]], merge_lists]  # Evidence: {id, type, requirement_id?, command?, output_path?, status, created_at?, updated_at?}
    
    # Final validation report
    final_validation_report: Optional[Dict[str, Any]]  # Final validation report
