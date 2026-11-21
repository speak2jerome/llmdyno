# Toolchains for the Aider polyglot benchmark (C++, Go, Java, JavaScript, Python, Rust) on top of the sandbox base.
# Build context: the folder LLMDyno prepares when you import the benchmark (warm/ holds the exercises' own build
# files, so Gradle, npm and Cargo caches are filled here and the agent and grader can work offline).
ARG BASE=llmdyno-sandbox:1
FROM golang:1.23-bookworm AS go
FROM rust:1.88-slim-bookworm AS rust
FROM eclipse-temurin:21-jdk AS jdk

FROM ${BASE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
 && rm -rf /var/lib/apt/lists/*
COPY --from=go /usr/local/go /usr/local/go
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
ENV PATH=/usr/local/go/bin:/usr/local/cargo/bin:/opt/java/openjdk/bin:$PATH JAVA_HOME=/opt/java/openjdk \
    CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup GRADLE_USER_HOME=/opt/gradle \
    GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off GOCACHE=/tmp/go-cache GOPATH=/tmp/go \
    CARGO_TARGET_DIR=/tmp/cargo-target CARGO_NET_OFFLINE=true

COPY polyglot-test.sh /usr/local/bin/polyglot-test
RUN chmod +x /usr/local/bin/polyglot-test

# JavaScript: jest and babel from the exercises' package.json, shared by every exercise through a symlink
COPY warm/javascript/ /opt/polyglot-warm/javascript/
RUN mkdir -p /opt/polyglot-js && cp /opt/polyglot-warm/javascript/package.json /opt/polyglot-js/ \
 && cd /opt/polyglot-js && npm_config_offline=false npm install --no-audit --no-fund && npm cache clean --force

# Java: run each distinct Gradle setup once (with its reference solution) to cache the wrapper and test libraries
COPY warm/java/ /opt/polyglot-warm/java/
RUN for d in /opt/polyglot-warm/java/*/; do (cd "$d" && bash ./gradlew test --no-daemon --console=plain -q || true); done \
 && chmod -R a+rwX /opt/gradle

# Rust last: its toolchain changes most often (crates move to new editions), and the layers above stay cached
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
# fetch the crates any exercise (or its reference solution) depends on
COPY warm/rust/ /opt/polyglot-warm/rust/
RUN for d in /opt/polyglot-warm/rust/*/; do (cd "$d" && CARGO_NET_OFFLINE=false cargo fetch) || exit 1; done \
 && chmod -R a+rwX /usr/local/cargo

RUN go version && cargo --version && java -version 2>&1 | head -1 && cmake --version | head -1 \
 && /opt/polyglot-js/node_modules/.bin/jest --version
LABEL org.llmdyno.role=polyglot
WORKDIR /workspace
