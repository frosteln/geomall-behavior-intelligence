#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=""
SERVICES_FILE=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
STACK_ROOT_DEFAULT="/opt/llm-serving"
MODEL_ROOT_DEFAULT="/mnt/models"
VENV_PATH=""

usage() {
  cat <<'EOF'
Usage:
  bootstrap_ec2.sh --env /path/to/deployment.env --services /path/to/services.yaml
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENV_FILE="$2"
      shift 2
      ;;
    --services)
      SERVICES_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${ENV_FILE}" || -z "${SERVICES_FILE}" ]]; then
  usage
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

if [[ ! -f "${SERVICES_FILE}" ]]; then
  echo "Missing services file: ${SERVICES_FILE}" >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

STACK_ROOT="${STACK_ROOT:-$STACK_ROOT_DEFAULT}"
MODEL_ROOT="${MODEL_ROOT:-$MODEL_ROOT_DEFAULT}"
VENV_PATH="${STACK_ROOT}/.venv"

install_os_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    awscli \
    ffmpeg \
    git \
    jq \
    build-essential \
    pkg-config \
    libsndfile1
}

prepare_dirs() {
  mkdir -p "${STACK_ROOT}" "${STACK_ROOT}/config" "${STACK_ROOT}/services" "${MODEL_ROOT}"
}

find_instance_store_device() {
  local root_parent
  root_parent="$(findmnt -n -o SOURCE / | sed 's/p[0-9]*$//' || true)"

  lsblk -dn -o NAME,TYPE | awk '$2 == "disk" {print "/dev/" $1}' | while read -r dev; do
    if [[ "${dev}" != "${root_parent}" ]]; then
      echo "${dev}"
      return 0
    fi
  done
}

mount_instance_store() {
  local device
  local format_flag="${FORMAT_INSTANCE_STORE:-true}"

  if mountpoint -q "${MODEL_ROOT}"; then
    return 0
  fi

  device="$(find_instance_store_device || true)"
  if [[ -z "${device}" ]]; then
    echo "No separate instance-store block device found; using ${MODEL_ROOT} on the root volume."
    mkdir -p "${MODEL_ROOT}"
    return 0
  fi

  mkdir -p "${MODEL_ROOT}"

  if [[ "${format_flag}" == "true" ]]; then
    mkfs.ext4 -F "${device}"
  fi

  mount "${device}" "${MODEL_ROOT}"
  if ! grep -q "${device} ${MODEL_ROOT}" /etc/fstab; then
    echo "${device} ${MODEL_ROOT} ext4 defaults,nofail 0 2" >> /etc/fstab
  fi
}

setup_python() {
  python3 -m venv "${VENV_PATH}"
  # shellcheck disable=SC1091
  source "${VENV_PATH}/bin/activate"
  pip install --upgrade pip wheel
  pip install -r "${ROOT_DIR}/requirements.deploy.txt"
}

sync_bundle_files() {
  cp "${ENV_FILE}" "${STACK_ROOT}/config/deployment.env"
  cp "${SERVICES_FILE}" "${STACK_ROOT}/config/services.yaml"
  cp "${ROOT_DIR}/services/whisper_api.py" "${STACK_ROOT}/services/whisper_api.py"
  cp "${ROOT_DIR}/services/bert_classifier_api.py" "${STACK_ROOT}/services/bert_classifier_api.py"
  cp "${SCRIPT_DIR}/render_stack.py" "${STACK_ROOT}/render_stack.py"
}

sync_models_from_s3() {
  local sync_enabled="${SYNC_MODELS_ON_BOOT:-true}"

  if [[ "${sync_enabled}" != "true" ]]; then
    echo "Skipping S3 model sync because SYNC_MODELS_ON_BOOT=${sync_enabled}"
    return 0
  fi

  "${VENV_PATH}/bin/python" "${STACK_ROOT}/render_stack.py" sync-models \
    --env "${STACK_ROOT}/config/deployment.env" \
    --services "${STACK_ROOT}/config/services.yaml"
}

render_stack() {
  "${VENV_PATH}/bin/python" "${STACK_ROOT}/render_stack.py" render \
    --env "${STACK_ROOT}/config/deployment.env" \
    --services "${STACK_ROOT}/config/services.yaml" \
    --output "${STACK_ROOT}/generated"
}

install_systemd_units() {
  cp "${STACK_ROOT}/generated/systemd/"*.service /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now vllm-qwen whisper-api bert-classifier litellm open-webui
}

main() {
  install_os_packages
  prepare_dirs
  mount_instance_store
  setup_python
  sync_bundle_files
  sync_models_from_s3
  render_stack
  install_systemd_units
  echo "Bootstrap complete."
}

main "$@"
