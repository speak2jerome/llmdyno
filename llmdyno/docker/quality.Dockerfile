# Code-quality tools on top of the sandbox base: ruff, radon, bandit, vulture and coverage.
ARG BASE=llmdyno-sandbox:1
FROM ${BASE}
# The sandbox disables the package index for agents; lift it for this build step only.
RUN env -u PIP_NO_INDEX pip install --no-cache-dir ruff radon bandit vulture pytest-cov coverage \
 && pip freeze | grep -iE "^(ruff|radon|bandit|vulture|pytest-cov|coverage)==" > /opt/quality-tools.txt
LABEL org.llmdyno.role=quality
