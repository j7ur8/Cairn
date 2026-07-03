FROM ghcr.io/oritera/cairn-worker-container:latest@sha256:d90d40b7c634b8d5dc9464e04b863a185b9efe964ffd2b246f6e5cbc2a2ef053

USER root

RUN sed -i 's|http://http.kali.org/kali/|https://mirrors.ustc.edu.cn/kali/|g' /etc/apt/sources.list.d/kali.sources
RUN apt update && apt install -y --no-install-recommends \
    mcp-kali-server \
    metasploit-framework \
    metasploitmcp \
    nmap \
    dirb \
    gobuster \
    nikto \
    enum4linux-ng \
    hydra \
    john \
    sqlmap \
    wpscan \
    wordlists \
    && rm -rf /var/lib/apt/lists/*
RUN rm /home/kali/workspace/*.md
RUN npm install -g @openai/codex@0.141.0
RUN npm install -g @anthropic-ai/claude-code@2.1.183
RUN npm install -g chrome-devtools-mcp@1.1.1

USER kali
COPY ./bin/kali-mcp-stdio /usr/local/bin/kali-mcp-stdio
COPY ./bin/metasploit-mcp-stdio /usr/local/bin/metasploit-mcp-stdio
COPY ./bin/cairn-resources-mcp-stdio /usr/local/bin/cairn-resources-mcp-stdio
RUN sudo chmod +x /usr/local/bin/kali-mcp-stdio /usr/local/bin/metasploit-mcp-stdio /usr/local/bin/cairn-resources-mcp-stdio



WORKDIR /home/kali/workspace
