# LLMDyno sandbox base: everything the built-in benchmarks need, so agents never need the network.
# Harness images build FROM this image; graders run in it directly.
FROM node:24-bookworm-slim AS node

FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN apt-get update \
 && apt-get install -y --no-install-recommends bash ca-certificates git ripgrep curl sqlite3 procps less file \
      bzip2 xz-utils unzip jq tree \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
      flask flask-login flask-wtf werkzeug \
      fastapi "uvicorn[standard]" httpx pydantic sqlalchemy python-multipart \
      django djangorestframework \
      pytest pytest-timeout requests \
      numpy pandas pyarrow scikit-learn scipy joblib matplotlib python-dateutil \
 && npm install -g --no-audit --no-fund typescript@5 @types/node \
 && pip freeze > /opt/pip-freeze.txt

RUN git config --global user.email "agent@llmdyno.local" && git config --global user.name "LLMDyno agent" \
 && git config --global init.defaultBranch main

# Offline by default: package managers fail fast instead of hanging on the internal network.
ENV PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 npm_config_offline=true \
    PYTHONDONTWRITEBYTECODE=1 NODE_PATH=/usr/local/lib/node_modules \
    DO_NOT_TRACK=1 NO_UPDATE_NOTIFIER=1
LABEL org.llmdyno.role=sandbox
WORKDIR /workspace
