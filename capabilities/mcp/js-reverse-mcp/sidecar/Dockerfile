FROM node:22-bookworm-slim

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
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://mirrors.ustc.edu.cn|https://mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fluxbox \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libexpat1 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    novnc \
    procps \
    websockify \
    x11vnc \
    xauth \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cairn-cloak
RUN npm init -y >/dev/null \
    && npm install cloakbrowser@0.4.8 puppeteer-core@24.11.2 \
    && npx cloakbrowser install

COPY control-server.mjs /opt/cairn-cloak/control-server.mjs
COPY entrypoint.sh /usr/local/bin/cairn-cloak-entrypoint
RUN chmod +x /usr/local/bin/cairn-cloak-entrypoint

EXPOSE 6080 7310 9222 9223
CMD ["/usr/local/bin/cairn-cloak-entrypoint"]
