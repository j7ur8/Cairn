FROM ghcr.io/oritera/cairn-worker-container:latest

USER root

RUN find /etc/apt/sources.list.d/ -name "*.list" -name "*kali*" -exec sed -i 's|mirror.twds.com.tw|mirrors.ustc.edu.cn|g' {} \;
RUN apt update
RUN rm /home/kali/workspace/*.md

USER kali
COPY ./bin/kali-mcp-stdio /usr/local/bin/kali-mcp-stdio
COPY ./bin/metasploit-mcp-stdio /usr/local/bin/metasploit-mcp-stdio
RUN sudo chmod +x /usr/local/bin/kali-mcp-stdio /usr/local/bin/metasploit-mcp-stdio


WORKDIR /home/kali/workspace
