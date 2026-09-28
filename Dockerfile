# ChronoHive evaluation client toolbox.
#
# © 2026 Layer1Labs Silicon Inc. All rights reserved.
# CONFIDENTIAL — PROPRIETARY. Licensed solely for evaluation under the
# ChronoHive Terms of Confidentiality (TOC.md) and the ChronoHive
# Evaluation License (LICENSE). Do not distribute.
#
# This is a CLIENT image: the compile client, the LF workload project,
# the TOC signing tools, the vendored chronoc compiler, and the pinned
# lfc + JRE for the validation gate. It contains no API server and no
# compiler source.
#
#   docker build -t chronohive-eval .
#   docker run --rm chronohive-eval                     # offline self-check
#   docker run --rm chronohive-eval python3 clients/compile_client.py \
#       --local --capacity storage_bw=100 -o /tmp/io.chb   # full local compile
#   docker run --rm -e CHRONOHIVE_API_KEY=... chronohive-eval \
#       python3 clients/compile_client.py --api-url https://api.layer1labs.ai \
#           --api-key "$CHRONOHIVE_API_KEY" --capacity storage_bw=100 -o /tmp/io.chb

FROM docker.io/library/python:3.12-slim-trixie@sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b

# Pinned toolchain assets (verified by SHA-256 at build time).
ARG LFC_VERSION=0.13.0
ARG LFC_SHA256=175784319935e388a5ebe44f33dc4e3367eed9f24d071c82af8b50afe013a1c2
ARG JRE_SHA256=2413149700df0f7d440500a84a8f764c535f21e5a5e87d38328b64eec2c5b500

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists

# Pinned Eclipse Temurin 21 JRE (what lfc runs on).
RUN curl -fsSL -o /tmp/jre.tar.gz \
      "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jre_x64_linux_hotspot_21.0.12.1_1.tar.gz" \
 && echo "${JRE_SHA256}  /tmp/jre.tar.gz" | sha256sum -c - \
 && mkdir -p /opt/java \
 && tar xzf /tmp/jre.tar.gz -C /opt/java --strip-components=1 \
 && rm /tmp/jre.tar.gz

# Pinned lfc v0.13.0 — the authoritative LF validation gate.
RUN curl -fsSL -o /tmp/lfc.tar.gz \
      "https://github.com/lf-lang/lingua-franca/releases/download/v${LFC_VERSION}/lf-cli-${LFC_VERSION}-Linux-x86_64.tar.gz" \
 && echo "${LFC_SHA256}  /tmp/lfc.tar.gz" | sha256sum -c - \
 && mkdir -p /opt/lf \
 && tar xzf /tmp/lfc.tar.gz -C /opt/lf --strip-components=1 \
 && rm /tmp/lfc.tar.gz \
 && /opt/java/bin/java -version >/dev/null

ENV JAVA_HOME=/opt/java \
    LFC=/opt/lf/bin/lfc \
    CHRONOC=/pkg/toolchain/chronoc-linux-x86_64 \
    PATH="/opt/java/bin:/opt/lf/bin:${PATH}"

WORKDIR /pkg

# The evaluation client package (nothing server-side, no secrets).
COPY clients/ ./clients/
COPY tools/ ./tools/
COPY scripts/ ./scripts/
COPY examples/ ./examples/
COPY lf/ ./lf/
COPY docs/ ./docs/
COPY toolchain/chronoc-linux-x86_64 ./toolchain/chronoc-linux-x86_64
COPY toolchain/README.md ./toolchain/README.md
COPY README.md LICENSE NOTICE TOC.md ./

RUN python3 -m compileall -q clients tools scripts examples \
 && /opt/lf/bin/lfc --version \
 && /pkg/toolchain/chronoc-linux-x86_64 --help >/dev/null

# Default: the offline self-check (project map, lfc gate, reference blob).
CMD ["python3", "clients/compile_client.py", "--check"]
