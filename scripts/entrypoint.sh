#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] jive5ab port=${J5A_PORT} v=${J5A_VERBOSITY}"
jive5ab -p "${J5A_PORT}" -m "${J5A_VERBOSITY}" &
J5A_PID=$!

send() { echo "$1;" | socat - TCP:127.0.0.1:${J5A_PORT},connect-timeout=1 || true; }

# Wait for control port
for i in {1..50}; do
  if echo "version?;" | socat - TCP:127.0.0.1:${J5A_PORT},connect-timeout=1 >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

# Ensure bind-mount directories exist
IFS=',' read -r -a DISK_ARR <<< "${DISK_PATHS:-}"
for d in "${DISK_ARR[@]}"; do
  [[ -z "$d" ]] && continue
  mkdir -p "$d" || true
  ls -ld "$d" || true
done

# Configure multiple disks for VBS
if [[ "${#DISK_ARR[@]}" -gt 0 ]]; then
  DISK_LIST=$(IFS=: ; echo "${DISK_ARR[*]}")
  echo "[entrypoint] set_disks = ${DISK_LIST}"
  send "set_disks = ${DISK_LIST}"
fi

# Configure network protocol/port
if [[ "${J5A_PROTOCOL}" == "udps" ]]; then
  echo "[entrypoint] net_protocol = udps : ${J5A_BUFF_RCV} : ${J5A_BUFF_SND} : ${J5A_THREADS}"
  send "net_protocol = udps : ${J5A_BUFF_RCV} : ${J5A_BUFF_SND} : ${J5A_THREADS}"
else
  echo "[entrypoint] net_protocol = udp"
  send "net_protocol = udp"
fi

echo "[entrypoint] net_port = ${J5A_NETPORT}"
send "net_port = ${J5A_NETPORT}"

# (legacy) net2file autostart
if [[ "${AUTOSTART_NET2FILE:-false}" == "true" ]]; then
  mkdir -p "$(dirname "${OUTPUT_PATH}")" || true
  echo "[entrypoint] net2file capture started -> ${OUTPUT_PATH}"
  send "net2file = open : ${OUTPUT_PATH}, w"
  send "net2file = on"
fi

# VBS autostart
if [[ "${AUTOSTART_RECORD:-false}" == "true" && -n "${SCAN_NAME:-}" ]]; then
  echo "[entrypoint] record=on:${SCAN_NAME}"
  send "record = on:${SCAN_NAME}"
fi

# Start aiokatcp proxy if enabled
if [[ "${KATCP_ENABLE:-false}" == "true" ]]; then
  echo "[entrypoint] starting KATCP server on ${KATCP_PORT}"
  python3 /usr/local/bin/jive5ab_katcp_proxy.py --jive-port "${J5A_PORT}" --katcp-port "${KATCP_PORT}" &
fi

wait ${J5A_PID}
