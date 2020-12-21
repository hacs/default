FROM mcr.microsoft.com/vscode/devcontainers/python:0-3.8
ENV DEBIAN_FRONTEND=noninteractive

# Install GH CLI
RUN apt-get update \
    \
    && curl -sfSL https://raw.githubusercontent.com/microsoft/vscode-dev-containers/master/script-library/github-debian.sh | bash -