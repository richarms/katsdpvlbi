#!/usr/bin/env bash
set -euo pipefail

# If Docker/Mesos provides a command, run it instead of the default startup.
# This allows controller wrappers (e.g. delay_run.sh + env setup) to execute.
if [[ "$#" -gt 0 ]]; then
  exec "$@"
fi

echo "[entrypoint] jive5ab port=${J5A_PORT} v=${J5A_VERBOSITY}"
jive5ab -p "${J5A_PORT}" -m "${J5A_VERBOSITY}" &
J5A_PID=$!

send() { echo "$1;" | socat - TCP:127.0.0.1:${J5A_PORT},connect-timeout=1 || true; }

extract_target() {
  printf '%s\n' "${J5A_NETPORT%%@*}"
}

extract_route_dev() {
  awk '{for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit }}'
}

is_multicast_ipv4() {
  local first_octet="${1%%.*}"
  [[ "${first_octet}" =~ ^[0-9]+$ ]] || return 1
  (( first_octet >= 224 && first_octet <= 239 ))
}

verify_multicast_route() {
  local target route_output route_dev
  target="$(extract_target)"
  [[ -n "${target}" ]] || return 0
  [[ -n "${J5A_CBF_INTERFACE:-}" ]] || return 0
  is_multicast_ipv4 "${target}" || return 0
  command -v ip >/dev/null 2>&1 || return 0

  route_output="$(ip route get "${target}" 2>/dev/null || true)"
  route_dev="$(printf '%s\n' "${route_output}" | extract_route_dev)"
  if [[ -z "${route_dev}" ]]; then
    echo "[entrypoint][preflight] ERROR: unable to resolve route for multicast target ${target}" >&2
    return 1
  fi
  if [[ "${route_dev}" != "${J5A_CBF_INTERFACE}" ]]; then
    echo "[entrypoint][preflight] ERROR: multicast target ${target} resolves to ${route_dev}, expected ${J5A_CBF_INTERFACE}" >&2
    echo "[entrypoint][preflight] ERROR: ip route get ${target} -> ${route_output}" >&2
    echo "[entrypoint][preflight] ERROR: add a persistent host route for the controller multicast pool on ${J5A_CBF_INTERFACE}" >&2
    return 1
  fi
  echo "[entrypoint][preflight] multicast target ${target} resolves to expected interface ${route_dev}"
}

# Wait for control port
for i in {1..50}; do
  if echo "version?;" | socat - TCP:127.0.0.1:${J5A_PORT},connect-timeout=1 >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

# Configure jumbo receive MTU before any recorder state that depends on it.
if [[ -n "${J5A_MTU:-}" ]]; then
  echo "[entrypoint] mtu = ${J5A_MTU}"
  send "mtu = ${J5A_MTU}"
fi

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

# Configure VDIF mode required by vbsrecord.
# This can be overridden by setting J5A_MODE explicitly.
if [[ -n "${J5A_MODE:-}" ]]; then
  echo "[entrypoint] mode = ${J5A_MODE}"
  send "mode = ${J5A_MODE}"
fi

# Configure network protocol/port
if [[ "${J5A_PROTOCOL}" == "udps" || "${J5A_PROTOCOL}" == "udpsnor" ]]; then
  echo "[entrypoint] net_protocol = ${J5A_PROTOCOL} : ${J5A_BUFF_RCV} : ${J5A_BUFF_SND} : ${J5A_THREADS}"
  send "net_protocol = ${J5A_PROTOCOL} : ${J5A_BUFF_RCV} : ${J5A_BUFF_SND} : ${J5A_THREADS}"
else
  echo "[entrypoint] net_protocol = udp"
  send "net_protocol = udp"
fi

echo "[entrypoint] net_port = ${J5A_NETPORT}"
send "net_port = ${J5A_NETPORT}"

verify_multicast_route

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
