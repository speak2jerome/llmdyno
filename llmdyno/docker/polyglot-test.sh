#!/bin/bash
# Runs an Aider polyglot exercise's tests from the exercise folder (the current directory), with every test enabled.
# The same command the Aider benchmark uses for each language; agents can call it while they work.
set -o pipefail
if [ -f Cargo.toml ]; then
  exec cargo test --offline -- --include-ignored "$@"
elif [ -f go.mod ]; then
  exec go test -v ./... "$@"
elif [ -f build.gradle ] || [ -f build.gradle.kts ]; then
  exec bash ./gradlew test --offline --no-daemon --console=plain "$@"
elif [ -f CMakeLists.txt ]; then
  mkdir -p build && cd build && cmake -DEXERCISM_RUN_ALL_TESTS=1 -G "Unix Makefiles" .. >/dev/null && exec make "$@"
elif [ -f package.json ]; then
  [ -e node_modules ] || ln -s /opt/polyglot-js/node_modules node_modules
  exec /opt/polyglot-js/node_modules/.bin/jest --ci "$@"
else
  exec python -m pytest -q -p no:cacheprovider "$@"
fi
