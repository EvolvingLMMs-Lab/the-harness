#!/bin/bash
# A CUDA 12.8 build toolkit (nvcc, cudart, cccl) for the CUDA extensions built against
# torch's CUDA 12.8 wheels (cuRobo), assembled from NVIDIA's redist archives
# (sha256-checked) into DEST. A host toolkit of another version is refused by torch
# for extensions; this one changes nothing on the machine.
#
#   bash environment/cuda_toolkit.sh DEST     (default $HARNESS_CUDA_BUILD_TOOLKIT)
set -euo pipefail

TOOLKIT="${1:-${HARNESS_CUDA_BUILD_TOOLKIT:?give the toolkit directory}}"
REDIST="${HARNESS_CUDA_REDIST:-https://developer.download.nvidia.com/compute/cuda/redist}"

if [ -x "$TOOLKIT/bin/nvcc" ]; then
  echo "CUDA 12.8 build toolkit already in $TOOLKIT"
  exit 0
fi
mkdir -p "$TOOLKIT" "$TOOLKIT.downloads"
while read -r path sha; do
  file="$TOOLKIT.downloads/$(basename "$path")"
  [ -f "$file" ] || curl -sS -L -o "$file" "$REDIST/$path"
  echo "$sha  $file" | sha256sum -c -
  tar -xJf "$file" -C "$TOOLKIT.downloads"
  cp -a "${file%.tar.xz}"/. "$TOOLKIT"/
done <<LIST
cuda_nvcc/linux-x86_64/cuda_nvcc-linux-x86_64-12.8.93-archive.tar.xz 9961b3484b6b71314063709a4f9529654f96782ad39e72bf1e00f070db8210d3
cuda_cudart/linux-x86_64/cuda_cudart-linux-x86_64-12.8.90-archive.tar.xz 8d566b5fe745c46842dc16945cf36686227536decd2302c372be86da37faca68
cuda_cccl/linux-x86_64/cuda_cccl-linux-x86_64-12.8.90-archive.tar.xz 0740e9e01e4f15e17c5ab8d68bba4f8ec0eb6b84edccba4ac45112d2d2174e4b
LIST
ls "$TOOLKIT/bin/nvcc"
