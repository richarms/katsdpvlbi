ARG KATSDPDOCKERBASE_REGISTRY=harbor.sdp.kat.ac.za/dpp
ARG JIVE5AB_REPO=https://github.com/jive-vlbi/jive5ab.git
# Pinned ref for reproducible builds (branch erroneous-delete-nonempty-file as of 2026-02-20)
ARG JIVE5AB_REF=05963cd9b88cc2446e8602d5c29bfb0a2417ccf8

FROM $KATSDPDOCKERBASE_REGISTRY/docker-base-build AS build
ARG JIVE5AB_REPO
ARG JIVE5AB_REF
LABEL maintainer="Richard Armstrong <richarms@sarao.ac.za>"

# Suppress debconf warnings
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies.
USER root

RUN apt-get update && apt-get install -y \
    build-essential git cmake pkg-config libx11-dev libxext-dev \
    libreadline-dev python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Build jive5ab
WORKDIR /opt
RUN git clone "${JIVE5AB_REPO}" /opt/jive5ab
WORKDIR /opt/jive5ab
RUN git checkout --detach "${JIVE5AB_REF}" && \
	mkdir build
WORKDIR /opt/jive5ab/build
RUN cmake -DSSAPI_ROOT=nossapi .. && \
	make -j$(nproc) B2B=64 && \
	make DESTDIR=/jive5ab-install install B2B=64 && \
	rm -r /opt/jive5ab

USER kat
ENV PATH="$PATH_PYTHON3" VIRTUAL_ENV="$VIRTUAL_ENV_PYTHON3"

# Install aiokatcp-python
RUN pip install aiokatcp && pip check

#######################################################################

FROM $KATSDPDOCKERBASE_REGISTRY/docker-base-runtime
LABEL maintainer="Richard Armstrong <richarms@sarao.ac.za>"

# Suppress debconf warnings
ENV DEBIAN_FRONTEND=noninteractive

USER root
RUN apt-get update && apt-get install -y \
    socat netcat-openbsd iproute2 libx11-6 libxext6 libreadline8 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /jive5ab-install /
COPY --from=build --chown=kat:kat /home/kat/ve3 /home/kat/ve3

# Add entrypoint + KATCP proxy
COPY --chown=kat:kat entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chown=kat:kat aiokatcp_jive5ab.py /usr/local/bin/aiokatcp_jive5ab.py
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/aiokatcp_jive5ab.py
RUN ldconfig

RUN mkdir -p /home/kat/runtime /home/kat/data /runtime && \
    chown -R kat:kat /home/kat/runtime /home/kat/data /runtime

USER kat
ENV PATH="$PATH_PYTHON3" VIRTUAL_ENV="$VIRTUAL_ENV_PYTHON3"
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
