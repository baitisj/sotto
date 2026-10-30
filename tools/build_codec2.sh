#!/bin/sh
# Build the Codec 2 command-line tools (c2enc, c2dec, c2sim) into build/codec2/src.
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$root/build/codec2"
cd "$root/build/codec2"
cmake -DCMAKE_BUILD_TYPE=Release -DUNITTEST=OFF "$root/codec/codec2" >/dev/null
make -j"$(nproc 2>/dev/null || echo 4)" c2enc c2dec c2sim >/dev/null
echo "built: $root/build/codec2/src/{c2enc,c2dec,c2sim}"
