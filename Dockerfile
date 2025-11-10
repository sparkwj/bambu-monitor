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
        sudo \
        git \
    ; \
    # configure timezone non-interactively
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone; \
    apt-get clean; rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ENV TZ=Asia/Shanghai

WORKDIR /app
COPY . .

# Install Python packages from requirements.txt if present. Running this as root
# writes packages into the system Python environment. If you prefer a virtualenv,
# modify to create/activate one and install into it instead.
RUN pip config set global.index-url https://mirrors.ustc.edu.cn/pypi/simple/
RUN pip config set global.trusted-host mirrors.ustc.edu.cn
RUN pip install -U pip

RUN set -eux; \
    pip3 install git+https://github.com/sparkwj/Bambu-Lab-Cloud-API.git
RUN set -eux; \
	pip3 install -r requirements.txt;

# Default command
CMD ["python3", "-m", "monitor.py"]