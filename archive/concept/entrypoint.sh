#!/usr/bin/env bash
set -euo pipefail

# Help message
echo "[entrypoint] starting jive5ab on port ${J5A_PORT} (verbosity=${J5A_VERBOSITY})"
jive5ab -p "${J5A_PORT}" -m "${J5A_VERBOSITY}" &
J5A_PID=$!

# helper to send a command to jive5ab
send() {
  # jive5ab expects commands ending with ';'
  # use socat or nc; socat is installed
  echo "$1;" | socat - TCP:127.0.0.1:${J5A_PORT},connect-timeout=1 || true
}

# Wait for control port to open
for i in {1..50}; do
  if echo "version?;" | socat - TCP:127.0.0.1:${J5A_PORT},connect-timeout=1 >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

# Make sure data dir exists
mkdir -p "$(dirname "${OUTPUT_PATH}")"

# Register disk path inside container (bind-mounted)
send "set_disks = ${DISK_PATH}"

# Configure network protocol/port
if [[ "${J5A_PROTOCOL}" == "udps" ]]; then
  # Buffers + threads apply to udps
  send "net_protocol = udps : ${J5A_BUFF_RCV} : ${J5A_BUFF_SND} : ${J5A_THREADS}"
else
  send "net_protocol = udp"
fi

# net_port can be "50000" or "10.101.0.7@50000"
send "net_port = ${J5A_NETPORT}"

# Optionally autostart capture
if [[ "${AUTOSTART}" == "true" ]]; then
  #send "net2file = connect"
  send "net2file = open : ${OUTPUT_PATH}, w"
  #send "net2file = on"
  echo "[entrypoint] net2file capture started -> ${OUTPUT_PATH}"
else
  echo "[entrypoint] AUTOSTART=false; waiting for external control"
fi

# Optionally start KATCP proxy
if [[ "${KATCP_ENABLE}" == "true" ]]; then
  echo "[entrypoint] starting KATCP server on ${KATCP_PORT}"
  python3 /usr/local/bin/aiokatcp_jive5ab.py --jive-port "${J5A_PORT}" --katcp-port "${KATCP_PORT}" &
fi

# Reap children
wait ${J5A_PID}

