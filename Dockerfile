ARG KATSDPDOCKERBASE_REGISTRY=harbor.sdp.kat.ac.za/dpp

FROM $KATSDPDOCKERBASE_REGISTRY/docker-base-build AS build
LABEL maintainer="Richard Armstrong <richarms@sarao.ac.za>"

# Suppress debconf warnings
ENV DEBIAN_FRONTEND=noninteractive

# Install some system packages used by multiple images.
USER root

RUN apt-get update && apt-get install -y \
    build-essential git cmake pkg-config libx11-dev libxext-dev \
    libreadline-dev python3 python3-pip socat netcat-openbsd iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Build jive5ab
WORKDIR /opt
RUN git clone https://github.com/jive-vlbi/jive5ab.git
WORKDIR /opt/jive5ab
# checkout branch that includes the net2file fix and build
RUN git checkout erroneous-delete-nonempty-file && \
	mkdir build
WORKDIR /opt/jive5ab/build
RUN cmake -DSSAPI_ROOT=nossapi .. && \
	make -j$(nproc) B2B=64 && \
	make install B2B=64 && \
	rm -r /opt/jive5ab

# Add entrypoint + KATCP proxy
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY aiokatcp_jive5ab.py /usr/local/bin/aiokatcp_jive5ab.py
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/aiokatcp_jive5ab.py


USER kat
ENV PATH="$PATH_PYTHON3" VIRTUAL_ENV="$VIRTUAL_ENV_PYTHON3"

# Install aiokatcp-python
RUN pip3 install aiokatcp

# Runtime dir
RUN mkdir -p /home/kat/runtime /home/kat/data
WORKDIR /runtime


# Default environment
ENV J5A_PORT=2620 \
    J5A_VERBOSITY=3 \
    J5A_PROTOCOL=udps \
    J5A_NETPORT=50000 \
    DISK_PATH=/mnt/disk0 \
    OUTPUT_PATH=/mnt/disk0/testscan/testscan.vdif \
    AUTOSTART=true \
    J5A_BUFF_RCV=33554432 \
    J5A_BUFF_SND=33554432 \
    J5A_THREADS=4 \
    KATCP_ENABLE=true \
    KATCP_PORT=7147

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

