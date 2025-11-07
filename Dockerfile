# Ubuntu 25.04 Docker image template
# - Uses ARGs for flexibility
# - Minimal, production-friendly: non-root user, apt cleanup, sensible defaults
# - Build: docker build --build-arg UBUNTU_VERSION=25.04 -t myimage:latest .

# Choose Ubuntu base (override with --build-arg if needed)
ARG UBUNTU_VERSION=22.04
FROM ubuntu:${UBUNTU_VERSION}

# Keep builds non-interactive
ARG DEBIAN_FRONTEND=noninteractive
ENV DEBIAN_FRONTEND=${DEBIAN_FRONTEND} \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Etc/UTC

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        tzdata \
        # Python (3.x) and pip
        python3 \
        python3-pip \
        python3-venv \
        # common build tools (remove if not needed)
        build-essential \
        sudo \
        git \
    ; \
    # configure timezone non-interactively
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone; \
    apt-get clean; rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create a non-root user for better security
ARG USERNAME=bambu
ARG USER_UID=1001
ARG USER_GID=1001
RUN set -eux; \
    groupadd --gid "$USER_GID" "$USERNAME" || true; \
    useradd --uid "$USER_UID" --gid "$USER_GID" -m "$USERNAME" || true; \
    mkdir -p /home/$USERNAME/.config && chown -R $USERNAME:$USERNAME /home/$USERNAME; \
    # allow sudo without password for convenience during builds (remove for production)
    echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME; \
    chmod 0440 /etc/sudoers.d/$USERNAME

USER bambu

WORKDIR /home/${USERNAME}/app

# Copy application files into the image workdir and set ownership.
# IMPORTANT: add a `.dockerignore` at the repo root to exclude build artifacts,
# node_modules, virtualenvs, secrets, large files, etc. (e.g. .git, .venv, build/)
COPY --chown=${USERNAME}:${USERNAME} . /home/${USERNAME}/app

# Ensure per-user local bin is available and owned by the non-root user
# so packages installed with `pip install --user` are found on PATH.
ENV PATH=/home/${USERNAME}/.local/bin:${PATH}

RUN set -eux; \
    mkdir -p /home/${USERNAME}/.local/bin; \
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}/.local

# Install Python packages from requirements.txt if present. Running this as root
# writes packages into the system Python environment. If you prefer a virtualenv,
# modify to create/activate one and install into it instead.
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

RUN set -eux; \
	pip3 install -r /home/${USERNAME}/app/requirements.txt;

RUN set -eux; \
    pip3 install -e Bambu-Lab-Cloud-API;

# Switch to non-root user
USER ${USERNAME}

# Default command
CMD ["python3", "-m", "monitor.py"]