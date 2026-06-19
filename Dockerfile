FROM ghcr.io/astral-sh/uv:python3.13-trixie@sha256:aa1cb04101f7c3f1bc49c5f1108baf115deb831175fc75c71963143900d82a5b

COPY ./cairn/pyproject.toml /cairn/pyproject.toml
COPY ./cairn/uv.lock /cairn/uv.lock
WORKDIR /cairn
RUN uv sync --frozen --no-install-project -i https://mirrors.aliyun.com/pypi/simple/

COPY ./cairn /cairn
COPY ./capabilities /cairn/capabilities
RUN uv sync --frozen -i https://mirrors.aliyun.com/pypi/simple/

ENV TZ=Asia/Shanghai
