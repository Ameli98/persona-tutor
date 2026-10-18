#!/usr/bin/env bash
# Start the persona-tutor backend (binds 127.0.0.1 only), then open http://localhost:<port> in a browser.
#   ./run.sh                       uses the current python
#   CONDA_ENV=GPTSoVits ./run.sh   activates a conda env first (the one GPT-SoVITS is installed in)
# After install.sh, the env it created is activated automatically (.conda-env).
set -e
cd "$(dirname "$0")"
[ -f config.yaml ] || { echo "config.yaml not found: run python -m tutor.setup (or copy config.example.yaml)"; exit 1; }
[ -z "$CONDA_ENV" ] && [ -f .conda-env ] && CONDA_ENV=$(sed -n 1p .conda-env)
if [ -n "$CONDA_ENV" ]; then
  for base in "$(sed -n 2p .conda-env 2>/dev/null)" "$(conda info --base 2>/dev/null)" ~/miniforge3 ~/miniconda3 ~/anaconda3; do
    [ -f "$base/etc/profile.d/conda.sh" ] && { source "$base/etc/profile.d/conda.sh"; break; }
  done
  conda activate "$CONDA_ENV"
fi
# The API key lives only in this file (chmod 600) and only this process gets it.
# Its own variable name, so other tools that read ANTHROPIC_API_KEY never see it.
KEY_FILE=${PERSONA_TUTOR_KEY_FILE:-~/.config/persona-tutor/api_key}
if [ -f "$KEY_FILE" ]; then
  PERSONA_TUTOR_API_KEY=$(cat "$KEY_FILE")
  export PERSONA_TUTOR_API_KEY
fi
read -r HOST PORT < <(python -c "import yaml; c = yaml.safe_load(open('config.yaml'))['server']; print(c['host'], c['port'])")
echo "starting persona-tutor (loading speech models, 30–60 s)…"
# warnings and errors only: the per-request access log and model chatter just scroll past
exec python -m uvicorn tutor.backend.app:app --host "$HOST" --port "$PORT" --log-level warning --no-access-log
