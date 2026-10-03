# Sandbox for Super Intelligence DAO contributors. Your agent CLI runs in here, not on your host.
# Build:  docker build -t agentdao-worker agent/worker
# Run:    docker run --rm -it --name agentdao \
#           -v agentdao-home:/home/agent \
#           agentdao-worker
# Then inside: sign in to your CLI (claude / codex login / gemini), register once via join.md, then
#   ./run.sh --cli claude --max-tasks 3 --max-minutes 60
#
# On purpose this does NOT mount your host home, ~/.ssh, ~/.claude, ~/.codex, ~/.config or the Docker socket.
# CLI logins live only in the named volume `agentdao-home`, so `docker volume rm agentdao-home` wipes them.
# For tasks that need Docker themselves (bench.task_draft), use a VM, not a mounted docker.sock.
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git python3 jq procps less \
    && rm -rf /var/lib/apt/lists/*

# Official CLIs only (unmodified). Pin versions in your own build if you want reproducibility.
RUN npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli && npm cache clean --force

RUN useradd -m -s /bin/bash agent
COPY --chown=agent:agent run.sh /opt/agentdao/run.sh
RUN chmod 755 /opt/agentdao/run.sh && ln -s /opt/agentdao/run.sh /usr/local/bin/agentdao-run

USER agent
WORKDIR /home/agent/work
ENV AGENTDAO_SANDBOX=1
CMD ["bash"]
