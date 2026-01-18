# Multi-Agent Orchestrator (LangGraph + Gemini)

This project implements a **Hierarchical Supervisor** system for autonomous software development, designed around **Spec-Driven Development** principles. It leverages **LangGraph** for state management and **Google Gemini 2.5** models for intelligence.

## Core Philosophy: Spec-Driven Development

Unlike typical "chat-to-code" agents, this system follows a strict engineering process:
1.  **Specification First**: No code is written until `spec.md`, `plan.md`, and `tasks.md` are created and approved.
2.  **Constitution**: All agents strictly adhere to a set of immutable rules defined in `spec/constitution/`.
3.  **Traceability**: Every requirement is tracked in `trace.json` from specification to implementation and verification.
4.  **Human-in-the-Loop**: The system explicitly pauses for **Clarifications** (`clarifications.md`) and **Blocking Questions** (`questions.md`) before proceeding.

## Workflow

The system moves through distinct phases:

### 1. Specification Phase
*   **Spec Planner**: Analyzes user requests and drafts specifications. If requirements are vague, it creates `clarifications.md` instead of guessing.
*   **Spec Reviewer**: Critiques the generated specs against the Constitution.
*   **Question Generator**: Identifies missing information and generates `questions.md`.
*   **Answer Parser**: Incorporates user answers into the specs.

### 2. Execution Phase
*   **Supervisor**: Orchestrates the execution of the approved `tasks.md`.
*   **Dispatcher**: Routes tasks to specialized workers.
*   **Workers**: Specialized agents executing tasks in parallel:
    *   `ui_agent`: Frontend development.
    *   `db_agent`: Database schema and queries.
    *   `logic_agent`: Backend business logic.
    *   `deploy_agent`: Deployment and DevOps.

### 3. Validation Phase
*   **Implementation Review**: Reviews code changes immediately after generation.
*   **Validator**: Runs tests and verifies acceptance criteria.
*   **Final Validator**: Performs a holistic check of the entire feature before marking it as DONE.

## Project Structure

```text
orchestrator/
├── main.py                 # Graph definition and entry point
├── state.py                # SharedState and Task definitions
├── nodes/                  # Agent logic (Planner, Reviewer, Supervisor, Workers)
├── tools/                  # MCP-style tools (FS, Shell)
└── utils/                  # Utilities (Caching, Logging)

spec/
├── constitution/           # Immutable rules for agents
└── features/               # Generated specs for each feature
    └── {feature_name}/
        ├── spec.md         # Detailed requirements
        ├── plan.md         # Implementation plan
        ├── tasks.md        # Atomic task list
        ├── questions.md    # Blocking questions
        ├── trace.json      # Requirement traceability matrix
        └── clarifications.md # Initial scope clarifications
```

## Key Features

*   **Shared State**: A strongly-typed global state (`TypedDict`) ensuring all agents share context.
*   **Self-Healing**: Automated error detection, retry budgets, and validation loops.
*   **Context Caching**: Optimizes token usage by caching static project documentation.
*   **Traceability**: `trace.json` ensures every line of code maps back to a requirement.
*   **Safe Execution**: Tools are constrained to the `workspace` directory.

## Setup & Usage

1.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configuration**
    Copy the example environment file and add your Google API Key:
    ```bash
    cp .env.example .env
    # Edit .env and set GOOGLE_API_KEY
    ```

3.  **Run the Orchestrator**
    ```bash
    python -m orchestrator.main "Create a login page"
    ```

4.  **Run with Docker (Recommended)**
    This runs the agent in an isolated container with `Node.js` and `npm` pre-installed for web development tasks.
    ```bash
    # Usage: ./run_agent.sh "Your Prompt"
    ./run_agent.sh "Create a React login component"
    ```
    Artifacts will be saved to the `workspace/` directory on your host machine.

## License

MIT
