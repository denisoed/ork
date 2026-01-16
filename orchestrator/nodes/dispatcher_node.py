import os
from typing import List

from orchestrator.state import SharedState, Task

# Parallelism control
MAX_PARALLEL_TASKS = int(os.getenv("MAX_PARALLEL_TASKS", "2"))

# Priority order for roles (deploy_agent is last to ensure all files are ready)
ROLE_PRIORITY = ['db_agent', 'logic_agent', 'ui_agent', 'deploy_agent']


def _get_ready_tasks(tasks: List[Task]) -> List[Task]:
    completed_ids = {t['id'] for t in tasks if t['status'] == 'completed'}
    failed_ids = {t['id'] for t in tasks if t['status'] == 'failed'}
    ready_tasks = []

    for t in tasks:
        if t['status'] != 'pending':
            continue
        if any(d in failed_ids for d in t['dependencies']):
            continue
        if all(d in completed_ids for d in t['dependencies']):
            ready_tasks.append(t)

    return ready_tasks


def dispatcher_node(state: SharedState) -> SharedState:
    """
    Selects up to MAX_PARALLEL_TASKS ready tasks and marks them as running.
    Ensures only one task per role is running at a time.
    """
    tasks = state.get('tasks_queue', [])
    if not tasks:
        return {}

    running_tasks = [t for t in tasks if t['status'] == 'running']
    running_roles = {t['assigned_role'] for t in running_tasks}
    available_slots = MAX_PARALLEL_TASKS - len(running_tasks)

    if available_slots <= 0:
        return {}

    ready_tasks = _get_ready_tasks(tasks)
    if not ready_tasks:
        return {}

    selected_updates: List[Task] = []
    used_roles = set(running_roles)

    # Pick tasks by role priority first
    for role in ROLE_PRIORITY:
        if available_slots <= 0:
            break
        for t in ready_tasks:
            if t['assigned_role'] == role and t['assigned_role'] not in used_roles:
                selected_updates.append({**t, "status": "running"})
                used_roles.add(t['assigned_role'])
                available_slots -= 1
                break

    # Fill remaining slots with any other roles
    if available_slots > 0:
        for t in ready_tasks:
            if available_slots <= 0:
                break
            if t['assigned_role'] in used_roles:
                continue
            selected_updates.append({**t, "status": "running"})
            used_roles.add(t['assigned_role'])
            available_slots -= 1

    if not selected_updates:
        return {}

    return {"tasks_queue": selected_updates}
