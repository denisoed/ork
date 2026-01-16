# Multi-Agent Orchestrator (LangGraph + Gemini)

This project implements a **Hierarchical Supervisor** system for autonomous software development. It leverages **LangGraph** for state management and **Google Gemini 2.0/1.5** models for intelligence.

## Workflow

User Request → Spec Planner → Spec Reviewer → [Questions/Corrections] → Supervisor → Workers → Final Validator → User Notification

## Architectures

The system consists of:
*   **Orchestrator (Gemini Pro)**: A high-level supervisor that decomposes complex user requests into atomic tasks.
*   **Workers (Gemini Flash)**: Specialized agents (UI, DB, Logic) that execute tasks in parallel.
*   **Validators**: A self-correction layer that verifies worker outputs and triggers retries if errors occur.

## Key Features

*   **Shared State**: A strongly-typed global state (`TypedDict`) ensuring all agents share context.
*   **Self-Healing**: Automated error detection and recovery loop.
*   **Context Caching**: Optimizes token usage by caching static project documentation.
*   **Tools**: Safe file system and shell execution tools constrained to a `workspace` directory.

## Project Structure

```text
orchestrator/
├── main.py                 # Graph definition and entry point
├── state.py                # SharedState and Task definitions
├── nodes/                  # Agent logic (Supervisor, Worker, Validator)
├── tools/                  # MCP-style tools (FS, Shell)
└── utils/                  # Utilities (Caching, Logging)
```

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
    python -m orchestrator.main
    ```

3.  **Run with Docker (Recommended)**
    This runs the agent in an isolated container with `Node.js` and `npm` pre-installed for web development tasks.
    ```bash
    # Usage: ./run_agent.sh "Your Prompt"
    ./run_agent.sh "Create a React login component"
    ```
    Artifacts will be saved to the `workspace/` directory on your host machine.
MIT
