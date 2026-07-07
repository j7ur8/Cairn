FROM node:22-bookworm-slim

USER root

ENV DEBIAN_FRONTEND=noninteractive

RUN printf '%s\n' \
    'Types: deb' \
    'URIs: http://mirrors.ustc.edu.cn/debian' \
    'Suites: bookworm bookworm-updates' \
    'Components: main' \
    'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
    '' \
    'Types: deb' \
    'URIs: http://mirrors.ustc.edu.cn/debian-security' \
    'Suites: bookworm-security' \
    'Components: main' \
    'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg' \
    > /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    python3 \
    python3-pip \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash kali \
    && mkdir -p /home/kali/workspace \
    && chown -R kali:kali /home/kali \
    && echo 'kali ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/kali \
    && chmod 0440 /etc/sudoers.d/kali

RUN npm install -g @openai/codex@0.141.0 \
    && npm install -g @anthropic-ai/claude-code@2.1.183 \
    && npm install -g chrome-devtools-mcp@1.1.1 \
    && npm install -g js-reverse-mcp@3.0.9

COPY ./bin/cairn-resources-mcp-stdio /usr/local/bin/cairn-resources-mcp-stdio
COPY ./bin/cairn-browser-mcp /usr/local/bin/cairn-browser-mcp
COPY ./bin/js-reverse-mcp-cairn /usr/local/bin/js-reverse-mcp-cairn

RUN chmod +x \
    /usr/local/bin/cairn-resources-mcp-stdio \
    /usr/local/bin/cairn-browser-mcp \
    /usr/local/bin/js-reverse-mcp-cairn

USER kali
WORKDIR /home/kali/workspace
