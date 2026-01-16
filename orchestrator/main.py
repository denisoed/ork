import os
import sys
from dotenv import load_dotenv

# Load environment variables before importing modules that read them
load_dotenv()

from typing import Dict
from langgraph.graph import StateGraph, END
from orchestrator.state import SharedState
from orchestrator.nodes.spec_planner_node import spec_planner_node, spec_planner_router
from orchestrator.nodes.spec_reviewer_node import spec_reviewer_node, spec_reviewer_router
from orchestrator.nodes.supervisor_node import supervisor_node, supervisor_router
from orchestrator.nodes.dispatcher_node import dispatcher_node
from orchestrator.nodes.worker_node import worker_node
from orchestrator.nodes.validator_node import validator_node
from orchestrator.nodes.final_validator_node import final_validator_node
from orchestrator.utils.notification import notify_user
from orchestrator.utils.logging import get_logger, ExecutionLogger

# Initialize logger
logger = get_logger("orchestrator.main")

def build_graph():
    """
    Constructs the Multi-Agent Orchestrator Graph.
    """
    workflow = StateGraph(SharedState)
    
    # 1. Add Nodes
    # Spec-feature nodes
    workflow.add_node("spec_planner", spec_planner_node)
    workflow.add_node("spec_reviewer", spec_reviewer_node)
    workflow.add_node("final_validator", final_validator_node)
    def user_notification_node(state: SharedState) -> SharedState:
        """User notification node - calls notify_user and returns empty state."""
        notify_user(state)
        return {}
    
    workflow.add_node("user_notification", user_notification_node)
    
    # Supervisor and dispatcher
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("dispatcher", dispatcher_node)
    
    # Worker Nodes (Partials)
    workflow.add_node("ui_agent", lambda s: worker_node(s, "ui_agent"))
    workflow.add_node("db_agent", lambda s: worker_node(s, "db_agent"))
    workflow.add_node("logic_agent", lambda s: worker_node(s, "logic_agent"))
    workflow.add_node("deploy_agent", lambda s: worker_node(s, "deploy_agent"))
    
    # Validator Nodes
    workflow.add_node("val_ui", lambda s: validator_node(s, "ui_agent"))
    workflow.add_node("val_db", lambda s: validator_node(s, "db_agent"))
    workflow.add_node("val_logic", lambda s: validator_node(s, "logic_agent"))
    workflow.add_node("val_deploy", lambda s: validator_node(s, "deploy_agent"))
    
    # 2. Add Edges
    # Entry point: spec_planner
    workflow.set_entry_point("spec_planner")
    
    # Conditional Edge from Spec Planner
    workflow.add_conditional_edges(
        "spec_planner",
        spec_planner_router,
        {
            "spec_reviewer": "spec_reviewer",
            "__end__": END
        }
    )
    
    # Conditional Edge from Spec Reviewer
    workflow.add_conditional_edges(
        "spec_reviewer",
        spec_reviewer_router,
        {
            "supervisor": "supervisor",
            "spec_planner": "spec_planner",  # Loop back if needs revision
            "__end__": END
        }
    )
    
    # Conditional Edge from Supervisor
    workflow.add_conditional_edges(
        "supervisor",
        supervisor_router,
        {
            "dispatcher": "dispatcher",
            "human_intervention": END,
            "__end__": "final_validator"  # Go to final validator when all tasks done
        }
    )
    
    # Fan-out: Dispatcher -> Workers (parallel)
    workflow.add_edge("dispatcher", "ui_agent")
    workflow.add_edge("dispatcher", "db_agent")
    workflow.add_edge("dispatcher", "logic_agent")
    workflow.add_edge("dispatcher", "deploy_agent")
    
    # Clean flow: Worker -> Validator
    workflow.add_edge("ui_agent", "val_ui")
    workflow.add_edge("db_agent", "val_db")
    workflow.add_edge("logic_agent", "val_logic")
    workflow.add_edge("deploy_agent", "val_deploy")
    
    # Return from Validator to Supervisor (Loop)
    workflow.add_edge("val_ui", "supervisor")
    workflow.add_edge("val_db", "supervisor")
    workflow.add_edge("val_logic", "supervisor")
    workflow.add_edge("val_deploy", "supervisor")
    
    # Final validator -> Notification -> END
    workflow.add_edge("final_validator", "user_notification")
    workflow.add_edge("user_notification", END)
    
    return workflow.compile()

from langchain_core.messages import HumanMessage

def validate_environment() -> bool:
    """Validate required environment variables."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("GOOGLE_API_KEY environment variable is not set!")
        logger.error("Please create a .env file with: GOOGLE_API_KEY=your_api_key")
        return False
    return True


def print_deployment_results(deployment_urls: Dict[str, str]):
    """
    Print deployment results in a formatted way.
    
    Args:
        deployment_urls: Dictionary of deployment URLs
    """
    if not deployment_urls:
        return
    
    print("\n" + "=" * 50)
    print("DEPLOYMENT RESULTS")
    print("=" * 50)
    
    # Print Vercel URLs
    if deployment_urls.get('vercel_preview'):
        print(f"  Vercel Preview: {deployment_urls['vercel_preview']}")
    if deployment_urls.get('vercel_production'):
        print(f"  Vercel Production: {deployment_urls['vercel_production']}")
    
    # Print Supabase URLs
    if deployment_urls.get('supabase_project'):
        print(f"  Supabase Project: {deployment_urls['supabase_project']}")
    if deployment_urls.get('supabase_function'):
        print(f"  Supabase Function: {deployment_urls['supabase_function']}")
    
    print("=" * 50)


def run_orchestrator(user_input: str) -> dict:
    """
    Run the orchestrator with the given input.
    
    Args:
        user_input: The user's request
        
    Returns:
        Summary dict with execution results
    """
    exec_logger = ExecutionLogger()
    
    logger.info("Initializing Multi-Agent Orchestrator...")
    
    try:
        app = build_graph()
        logger.info("Graph compiled successfully.")
        
        logger.info(f"Processing request: {user_input}")
        
        initial_state = {
            "messages": [HumanMessage(content=user_input)],
            "tasks_queue": [],
            "files_snapshot": {},
            "error_logs": [],
            "recursion_depth": 0,
            "token_usage": {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0},
            "deployment_urls": {},
            "spec_path": "spec/",
            "feature_name": None,
            # State machine fields
            "phase": "INTAKE",
            "feature_id": None,
            "open_questions": [],
            "acceptance_criteria": [],
            "evidence": [],
            "final_validation_report": None
        }
        
        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        final_state = initial_state
        all_deployment_urls = {}
        
        print("\n" + "=" * 50)
        print("EXECUTION START")
        print("=" * 50)
        
        for event in app.stream(initial_state):
            for node_name, node_state in event.items():
                print(f"\n--- Node: {node_name} ---")
                logger.debug(f"Node completed: {node_name}")
                
                # Update final state
                final_state.update(node_state)
                
                # Track token usage
                if "token_usage" in node_state:
                    u = node_state['token_usage']
                    input_t = u.get('input_tokens', 0)
                    output_t = u.get('output_tokens', 0)
                    
                    print(f"  Tokens: {input_t} in / {output_t} out")
                    
                    total_usage["input_tokens"] += input_t
                    total_usage["output_tokens"] += output_t
                    total_usage["total_tokens"] += u.get("total_tokens", 0)
                    
                    exec_logger.log_token_usage(node_name, input_t, output_t)

                # Print Task Updates
                if "tasks_queue" in node_state:
                    tasks = node_state['tasks_queue']
                    pending = len([t for t in tasks if t['status'] == 'pending'])
                    completed = len([t for t in tasks if t['status'] == 'completed'])
                    failed = len([t for t in tasks if t['status'] == 'failed'])
                    print(f"  Tasks: {completed} done, {pending} pending, {failed} failed")
                
                # Collect deployment URLs
                if "deployment_urls" in node_state and node_state["deployment_urls"]:
                    all_deployment_urls.update(node_state["deployment_urls"])
                    print(f"  Deployment URL collected: {node_state['deployment_urls']}")
                
                # Print errors if any
                if "error_logs" in node_state and node_state["error_logs"]:
                    for err in node_state["error_logs"]:
                        error_msg = err.get('error', 'Unknown error')
                        task_id = err.get('task_id', 'N/A')
                        print(f"  ERROR [{task_id}]: {error_msg}")
                        exec_logger.log_error(node_name, error_msg, task_id)
        
        print("\n" + "=" * 50)
        print("EXECUTION COMPLETE")
        print("=" * 50)
        
        # Final summary
        final_tasks = final_state.get('tasks_queue', [])
        completed_tasks = [t for t in final_tasks if t['status'] == 'completed']
        failed_tasks = [t for t in final_tasks if t['status'] == 'failed']
        
        print(f"\nResults:")
        print(f"  Total tasks: {len(final_tasks)}")
        print(f"  Completed: {len(completed_tasks)}")
        print(f"  Failed: {len(failed_tasks)}")
        print(f"\nToken Usage:")
        print(f"  Input: {total_usage['input_tokens']}")
        print(f"  Output: {total_usage['output_tokens']}")
        print(f"  Total: {total_usage['total_tokens']}")
        
        # Print deployment results
        final_deployment_urls = all_deployment_urls or final_state.get('deployment_urls', {})
        print_deployment_results(final_deployment_urls)
        
        # Log summary
        summary = exec_logger.get_summary()
        logger.info(f"Execution summary: {summary}")
        
        return {
            "success": len(failed_tasks) == 0,
            "tasks_completed": len(completed_tasks),
            "tasks_failed": len(failed_tasks),
            "token_usage": total_usage,
            "deployment_urls": final_deployment_urls,
            "log_file": exec_logger.log_file
        }
        
    except Exception as e:
        logger.exception(f"Error running graph: {e}")
        exec_logger.log_error("main", str(e))
        return {
            "success": False,
            "error": str(e),
            "log_file": exec_logger.log_file
        }

if __name__ == "__main__":
    # Validate environment
    if not validate_environment():
        sys.exit(1)
    
    # Get user input
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
    else:
        user_input = input("Enter your request (e.g., 'Create a login page'): ")
        
    if not user_input:
        print("No input provided. Exiting.")
        sys.exit(0)
    
    # Run orchestrator
    result = run_orchestrator(user_input)
    
    print(f"\nLog file: {result.get('log_file', 'N/A')}")
    
    # Print deployment URLs one more time for easy copy
    if result.get('deployment_urls'):
        print("\n" + "-" * 50)
        print("Quick Access URLs:")
        for key, url in result['deployment_urls'].items():
            print(f"  {key}: {url}")
        print("-" * 50)
    
    # Exit with appropriate code
    sys.exit(0 if result.get('success', False) else 1)
