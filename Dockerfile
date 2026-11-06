# FCC (Free Claude Code) gateway — NVIDIA NIM + Nemotron 3 Ultra
# Render free web service (Docker). No API key is stored here: the user
# enters their own Nvidia key into the Admin UI's secure field, or it is
# set as the NVIDIA_NIM_API_KEY environment variable in Render.
# FCC's default provider/model are already NVIDIA NIM + Nemotron 3 Ultra.

FROM python:3.14.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL=nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b

# Node.js 24 (for the Claude Code agent CLI) + curl + git
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# FCC server (PyPI package, pinned to the verified version)
RUN pip install --no-cache-dir "free-claude-code==6.18.11" \
    && npm install -g "@anthropic-ai/claude-code@2.1.318"

WORKDIR /app
COPY proxy.py start.sh ./
RUN chmod +x start.sh

# Render sets $PORT; the start script runs fcc-server on internal 8082
# and the basic-auth proxy on $PORT.
CMD ["bash", "start.sh"]
