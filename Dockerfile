FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (e.g. for building some python packages or shell tools)
# git is often needed for verification if we add git tools later. 
# Node.js/npm for React/Tailwind tasks support (since agents need to run npm commands)
# curl is needed for some CLI tools
RUN apt-get update && apt-get install -y \
    git \
    nodejs \
    npm \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Supabase CLI globally
RUN npm install -g supabase@latest

# Install Vercel CLI globally
RUN npm install -g vercel@latest

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY orchestrator/ ./orchestrator/
# Copy spec-feature structure (will be overridden by volume mount if provided)
COPY spec/ ./spec/
# Create workspace directory
RUN mkdir workspace

# Set python path to include root
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default command
ENTRYPOINT ["python", "-m", "orchestrator.main"]
