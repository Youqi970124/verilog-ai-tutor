# Verilog AI Tutor web app. Ubuntu 24.04 ships Icarus Verilog 12, the version VerilogEval requires.
# Yosys is only needed for authoring and mutation testing, not for serving, so it is left out.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv iverilog \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "openai>=1.40"
ENV PATH=/opt/venv/bin:$PATH

# Learner code is compiled and simulated in this container: run as an unprivileged user.
# uid 1000 matches what Hugging Face Spaces uses at runtime.
RUN userdel -r ubuntu 2>/dev/null || true; useradd --create-home --uid 1000 app
WORKDIR /app
COPY --chown=app:app w2a w2a
COPY --chown=app:app web web
COPY --chown=app:app curriculum curriculum
COPY --chown=app:app problems problems
USER app

# Hosts such as Render pass the port in $PORT; 8000 otherwise. WEB_CONCURRENCY sets the worker count
# (1 fits a 512 MB free instance).
ENV PORT=8000 WEB_CONCURRENCY=1
EXPOSE 8000
HEALTHCHECK CMD python3 -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"
# Recommended: docker run --read-only --tmpfs /tmp -p 8000:8000 -e NEBIUS_API_KEY=... verilog-ai-tutor
CMD ["sh", "-c", "exec uvicorn w2a.server:app --host 0.0.0.0 --port \"$PORT\" --workers \"$WEB_CONCURRENCY\""]
