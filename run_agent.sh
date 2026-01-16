#!/bin/bash

# Ensure a prompt was provided
if [ -z "$1" ]; then
    echo "Usage: ./run_agent.sh \"Your Prompt Here\""
    exit 1
fi

PROMPT="$1"

# Check for .env file
if [ ! -f .env ]; then
    echo "Error: .env file not found. Please create one with your Google API Key."
    exit 1
fi

echo "Building Docker image..."
docker build -t orchestrator-agent .

echo "Running Agent with prompt: $PROMPT"
echo "-----------------------------------"

# Run container
# -v $(pwd)/workspace:/app/workspace: Maps host workspace to container workspace
# -v $(pwd)/spec:/app/spec: Maps host spec to container spec (for spec-feature)
# --env-file .env: Passes API keys
docker run --rm \
    -v "$(pwd)/workspace":/app/workspace \
    -v "$(pwd)/spec":/app/spec \
    --env-file .env \
    orchestrator-agent "$PROMPT"
