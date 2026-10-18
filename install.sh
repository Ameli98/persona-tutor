#!/usr/bin/env bash
# One-step environment setup for persona-tutor (Linux or WSL2, NVIDIA GPU).
#
#   bash install.sh                       # defaults: conda env "persona-tutor", GPT-SoVITS in ../GPT-SoVITS
#   bash install.sh --gsv ~/GPT-SoVITS    # use (or create) GPT-SoVITS somewhere else
#   bash install.sh --env myenv --source HF-Mirror
#
# What it does:
#   1. checks the NVIDIA driver, git and conda (offers to install Miniforge if conda is missing)
#   2. uses your GPT-SoVITS checkout, or clones the version this project was tested with
#   3. creates a conda env and runs GPT-SoVITS's own installer in it (PyTorch, dependencies, pretrained models)
#   4. adds what that installer misses for this project (CUDA torchaudio, NPP, library paths for faster-whisper)
#   5. installs requirements.txt, checks GPU / speech recognition / Japanese readings, remembers the env for run.sh
# Safe to run again: finished steps are skipped or quick. Everything is logged to install.log.
set -eo pipefail   # (no -u: conda's activation scripts read unset variables)
cd "$(dirname "$0")"
ROOT=$(pwd)
# the log keeps each progress bar's final state only (the part after its last \r), not every update
exec > >(tee >(sed -u 's/.*\r//' >> "$ROOT/install.log")) 2>&1
# GPT-SoVITS downloads with `wget --show-progress`; through tee wget isn't on a terminal and would print a
# dotted line per 50 KB (100k lines). One bar per file instead.
export WGETRC="$ROOT/.wgetrc-install"
echo "progress = bar:force:noscroll" > "$WGETRC"
trap 'rm -f "$WGETRC"' EXIT

ENV_NAME=persona-tutor
GSV_DIR=""
SOURCE=HF                       # pretrained-model mirror for GPT-SoVITS: HF | HF-Mirror | ModelScope
CUDA=128
GSV_REPO=https://github.com/RVC-Boss/GPT-SoVITS.git
GSV_COMMIT=1b47ca0              # the GPT-SoVITS version this project was tested with
TORCH="torch==2.11.0 torchaudio==2.11.0 torchcodec==0.11.1"
YES=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_NAME=$2; shift 2 ;;
    --gsv) GSV_DIR=$2; shift 2 ;;
    --source) SOURCE=$2; shift 2 ;;
    --cuda) CUDA=$2; shift 2 ;;
    -y|--yes) YES=true; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)"; exit 1 ;;
  esac
done

step() { echo; echo "==> $*"; }
ok() { echo "    ✓ $*"; }
die() { echo "    ✗ $*"; exit 1; }
confirm() { $YES && return 0; read -r -p "    $1 [y/N] " a; [[ $a =~ ^[Yy] ]]; }

echo "persona-tutor install — $(date)"

step "1/5 Checking the system"
[[ $(uname -s) == Linux ]] || die "Linux or WSL2 is required (found $(uname -s))"
grep -qi microsoft /proc/version && ok "WSL2" || ok "Linux"
if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
  ok "NVIDIA $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
else
  die "no working NVIDIA driver (nvidia-smi). On WSL2, install the NVIDIA driver on Windows, then reopen the terminal"
fi
missing=()
for tool in git curl wget; do command -v $tool >/dev/null || missing+=("$tool"); done
[[ ${#missing[@]} -eq 0 ]] || die "missing: ${missing[*]} — run: sudo apt install -y ${missing[*]}"
ok "git, curl, wget"

CONDA_BASE=""
for base in "$(conda info --base 2>/dev/null || true)" "${CONDA_EXE:+$(dirname "$(dirname "$CONDA_EXE")")}" \
            ~/miniforge3 ~/miniconda3 ~/anaconda3 ~/mambaforge ~/miniforge /opt/conda /opt/miniforge3; do
  [[ -n $base && -f $base/etc/profile.d/conda.sh ]] && { CONDA_BASE=$base; break; }
done
if [[ -z $CONDA_BASE ]]; then
  echo "    conda was not found."
  confirm "Install Miniforge (conda) into ~/miniforge3?" || die "install conda first: https://conda-forge.org/download/"
  inst=$(mktemp -d)/miniforge.sh
  curl -fsSL -o "$inst" "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-$(uname -m).sh"
  bash "$inst" -b -p ~/miniforge3
  CONDA_BASE=~/miniforge3
fi
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
ok "conda $(conda --version | cut -d' ' -f2) at $CONDA_BASE"

step "2/5 GPT-SoVITS"
if [[ -z $GSV_DIR ]]; then
  for c in "$ROOT/../GPT-SoVITS" ~/GPT-SoVITS; do
    [[ -d $c/GPT_SoVITS ]] && { GSV_DIR=$c; break; }
  done
fi
GSV_DIR=${GSV_DIR:-$ROOT/../GPT-SoVITS}
if [[ -d $GSV_DIR/GPT_SoVITS ]]; then
  GSV_DIR=$(cd "$GSV_DIR" && pwd)
  ok "using $GSV_DIR"
else
  echo "    cloning GPT-SoVITS (tested version $GSV_COMMIT) into $GSV_DIR"
  git clone "$GSV_REPO" "$GSV_DIR"
  git -C "$GSV_DIR" checkout -q "$GSV_COMMIT"
  GSV_DIR=$(cd "$GSV_DIR" && pwd)
  ok "cloned"
fi

step "3/5 Conda env '$ENV_NAME' + GPT-SoVITS installer (PyTorch, dependencies, pretrained models — the first run downloads several GB)"
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  ok "env exists"
else
  conda create -y -q -n "$ENV_NAME" python=3.11
  ok "env created"
fi
conda activate "$ENV_NAME"
PY_SITE=$(python -c "import site; print(site.getsitepackages()[0])")
# the tested PyTorch build first, so GPT-SoVITS's unpinned "pip install torch" is already satisfied (~3 GB)
echo "    downloading PyTorch (~3 GB, a few minutes)…"
python -m pip install -q $TORCH --index-url "https://download.pytorch.org/whl/cu$CUDA"
ok "PyTorch: $(python -c 'import torch; print(torch.__version__)')"
echo "    running GPT-SoVITS's installer (several minutes, mostly quiet while it downloads)…"
(cd "$GSV_DIR" && bash install.sh --device "CU$CUDA" --source "$SOURCE")
[[ -f $GSV_DIR/GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth ]] || die "GPT-SoVITS pretrained models are missing — see the installer output above"
ok "GPT-SoVITS installed"

step "4/5 Extras GPT-SoVITS doesn't install"
# its requirements can replace torchaudio with a CPU build; NPP is needed by torchcodec (torchaudio.load)
python -m pip install -q $TORCH --index-url "https://download.pytorch.org/whl/cu$CUDA"
python -m pip install -q "nvidia-npp-cu12" resampy
# pip-wheel CUDA libraries aren't on the loader path: NPP for torchcodec, cuBLAS/cuDNN for faster-whisper
mkdir -p "$CONDA_PREFIX/etc/conda/activate.d"
cat > "$CONDA_PREFIX/etc/conda/activate.d/persona-tutor-libs.sh" <<EOF
_nv="$PY_SITE/nvidia"
export LD_LIBRARY_PATH="\$_nv/npp/lib:\$_nv/cublas/lib:\$_nv/cudnn/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
unset _nv
EOF
conda deactivate && conda activate "$ENV_NAME"   # pick up the library paths
ok "CUDA torchaudio, NPP, library paths"

step "5/5 persona-tutor requirements and checks"
python -m pip install -q -r requirements.txt
ok "requirements.txt"
# env name, where conda lives (activate.sh / run.sh) and where GPT-SoVITS is (tutor.setup's default)
printf '%s\n%s\n%s\n' "$ENV_NAME" "$CONDA_BASE" "$GSV_DIR" > .conda-env
python - "$GSV_DIR" <<'EOF'
import shutil, sys
import torch, ctranslate2, pyopenjtalk
assert torch.cuda.is_available(), "PyTorch can't see the GPU"
print(f"    ✓ PyTorch CUDA: {torch.cuda.get_device_name(0)}")
assert ctranslate2.get_cuda_device_count() > 0, "faster-whisper (ctranslate2) can't see the GPU"
print("    ✓ faster-whisper GPU")
print(f"    ✓ Japanese readings: {pyopenjtalk.g2p('日本語', kana=True)}")
assert shutil.which("ffmpeg"), "ffmpeg missing"
print("    ✓ ffmpeg")
EOF

echo
echo "Done. Next:"
echo "  source activate.sh             # in every new terminal (activates the $ENV_NAME env)"
echo "  python -m tutor.setup          # GPT-SoVITS is at $GSV_DIR"
echo "  then train a voice (python -m voice.ingest tutor <recordings> ... see README.md) and ./run.sh"
