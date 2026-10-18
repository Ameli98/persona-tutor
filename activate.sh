# Activate the conda env that install.sh created, in this terminal only (no ~/.bashrc changes).
#   source activate.sh
# install.sh records the env name and the conda it used in .conda-env, so this works wherever conda lives.
_pt_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
_pt_env=$(sed -n 1p "$_pt_dir/.conda-env" 2>/dev/null)
_pt_base=$(sed -n 2p "$_pt_dir/.conda-env" 2>/dev/null)
if [ "$(type -t conda)" != function ]; then   # conda not initialized in this shell yet
  for _pt_b in "$_pt_base" "$(conda info --base 2>/dev/null)" ~/miniforge3 ~/miniconda3 ~/anaconda3; do
    [ -n "$_pt_b" ] && [ -f "$_pt_b/etc/profile.d/conda.sh" ] && { . "$_pt_b/etc/profile.d/conda.sh"; break; }
  done
fi
if [ "$(type -t conda)" = function ]; then
  conda activate "${_pt_env:-persona-tutor}" && echo "persona-tutor: env '${_pt_env:-persona-tutor}' active"
else
  echo "conda not found — run: bash install.sh"
fi
unset _pt_dir _pt_env _pt_base _pt_b
