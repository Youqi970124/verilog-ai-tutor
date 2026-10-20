# Wire-to-Adder web app. Ubuntu 24.04 ships Icarus Verilog 12 (required by VerilogEval) and Yosys.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv iverilog yosys \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "openai>=1.40"
ENV PATH=/opt/venv/bin:$PATH

# Learner code is compiled and simulated in this container: run as an unprivileged user.
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --chown=app:app w2a w2a
COPY --chown=app:app web web
COPY --chown=app:app curriculum curriculum
COPY --chown=app:app problems problems
USER app

EXPOSE 8000
HEALTHCHECK CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
# Recommended: docker run --read-only --tmpfs /tmp -p 8000:8000 -e NEBIUS_API_KEY=... wire-to-adder
CMD ["uvicorn", "w2a.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
