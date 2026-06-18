#!/usr/bin/env bash
set -euo pipefail

UV_VERSION="${UV_VERSION:-0.11.6}"
PYTHON_VERSION="${1:-}"
TOOL_ROOT="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/manmankan-ci-tools"
UV_BIN_DIR="${TOOL_ROOT}/uv-${UV_VERSION}/bin"

add_to_path() {
  local dir="$1"
  case ":${PATH}:" in
    *":${dir}:"*) ;;
    *) export PATH="${dir}:${PATH}" ;;
  esac
  if [ -n "${GITHUB_PATH:-}" ]; then
    printf '%s\n' "${dir}" >>"${GITHUB_PATH}"
  fi
}

find_existing_uv() {
  local candidate
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi

  for candidate in \
    "${HOME}/.local/bin/uv" \
    "${HOME}/.cargo/bin/uv" \
    "/usr/local/bin/uv" \
    "/opt/homebrew/bin/uv" \
    "/opt/actions-cache/bin/uv"; do
    if [ -x "${candidate}" ]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  return 1
}

uv_target() {
  local os arch
  case "$(uname -s)" in
    Linux) os="unknown-linux-gnu" ;;
    Darwin) os="apple-darwin" ;;
    *)
      echo "Unsupported OS for uv bootstrap: $(uname -s)" >&2
      return 1
      ;;
  esac

  case "$(uname -m)" in
    x86_64 | amd64) arch="x86_64" ;;
    arm64 | aarch64) arch="aarch64" ;;
    *)
      echo "Unsupported architecture for uv bootstrap: $(uname -m)" >&2
      return 1
      ;;
  esac

  printf '%s-%s\n' "${arch}" "${os}"
}

verify_sha256() {
  local checksum_file="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -c "${checksum_file}"
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c "${checksum_file}"
  else
    echo "No sha256 verifier found; refusing unchecked uv archive." >&2
    return 1
  fi
}

curl_with_retries() {
  local max_time="$1"
  shift

  local retry_flags=(
    --retry 5
    --retry-delay 2
    --retry-connrefused
    --connect-timeout 20
    --max-time "${max_time}"
  )
  if curl --help all 2>/dev/null | grep -q -- "--retry-all-errors"; then
    retry_flags+=(--retry-all-errors)
  fi

  curl -fsSL "${retry_flags[@]}" "$@"
}

install_uv() {
  local target asset tmpdir archive checksum base_url extracted
  target="$(uv_target)"
  asset="uv-${target}.tar.gz"
  base_url="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"

  mkdir -p "${UV_BIN_DIR}"
  if [ -x "${UV_BIN_DIR}/uv" ]; then
    return 0
  fi

  tmpdir="$(mktemp -d)"
  archive="${tmpdir}/${asset}"
  checksum="${archive}.sha256"

  curl_with_retries 180 "${base_url}/${asset}" -o "${archive}"
  curl_with_retries 60 "${base_url}/${asset}.sha256" -o "${checksum}"
  (
    cd "${tmpdir}"
    verify_sha256 "${asset}.sha256" >&2
  )

  tar -xzf "${archive}" -C "${tmpdir}"
  extracted="${tmpdir}/uv-${target}"
  install -m 0755 "${extracted}/uv" "${UV_BIN_DIR}/uv"
  if [ -x "${extracted}/uvx" ]; then
    install -m 0755 "${extracted}/uvx" "${UV_BIN_DIR}/uvx"
  fi
  rm -rf "${tmpdir}"
}

main() {
  local uv_bin uv_dir
  if uv_bin="$(find_existing_uv)"; then
    uv_dir="$(dirname "${uv_bin}")"
    add_to_path "${uv_dir}"
  else
    install_uv
    add_to_path "${UV_BIN_DIR}"
  fi

  uv --version

  if [ -n "${PYTHON_VERSION}" ]; then
    uv python install "${PYTHON_VERSION}"
    if [ -n "${GITHUB_ENV:-}" ]; then
      printf 'UV_PYTHON=%s\n' "${PYTHON_VERSION}" >>"${GITHUB_ENV}"
    fi
    export UV_PYTHON="${PYTHON_VERSION}"
    uv python find "${PYTHON_VERSION}"
  fi
}

main "$@"
