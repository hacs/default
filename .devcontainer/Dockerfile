FROM mcr.microsoft.com/vscode/devcontainers/python:0-3.8
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    \
    && wget -O /tmp/github-debian.sh https://raw.githubusercontent.com/microsoft/vscode-dev-containers/master/script-library/github-debian.sh \
    && bash /tmp/github-debian.sh