FROM kalilinux/kali-rolling

USER root

RUN printf '%s\n' \
    'deb http://mirrors.tuna.tsinghua.edu.cn/kali kali-rolling main contrib non-free non-free-firmware' \
    > /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    dirb \
    enum4linux-ng \
    gobuster \
    hydra \
    john \
    mcp-kali-server \
    nikto \
    nmap \
    python3 \
    python3-pip \
    sqlmap \
    sudo \
    unzip \
    wordlists \
    wpscan \
    && rm -rf /var/lib/apt/lists/*

RUN id kali >/dev/null 2>&1 || useradd -m -s /bin/bash kali \
    && mkdir -p /home/kali/workspace \
    && chown -R kali:kali /home/kali \
    && echo 'kali ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/kali \
    && chmod 0440 /etc/sudoers.d/kali

COPY ./bin/kali-mcp-http-sidecar /usr/local/bin/kali-mcp-http-sidecar
COPY ./bin/mcp-stdio-http-bridge /usr/local/bin/mcp-stdio-http-bridge

RUN chmod +x \
    /usr/local/bin/kali-mcp-http-sidecar \
    /usr/local/bin/mcp-stdio-http-bridge

USER kali
WORKDIR /home/kali/workspace

CMD ["/usr/local/bin/kali-mcp-http-sidecar"]
