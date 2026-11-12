#!/usr/bin/env bash
# Build the patched SDK and native Linux game. No Windows/Wine components.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
sdk_commit=c94f5ebdcb3c9d1a460ca48e04f9758448f8d518
work_dir="$repo/out/linux"
game_dir="$repo/assets"
jobs=${CMAKE_BUILD_PARALLEL_LEVEL:-4}
sdk_source=
sdk_only=0
usage() {
  cat <<'EOF'
Usage: scripts/linux/build.sh [options]
  --game-dir DIR     Extracted game dump containing default.xex (default: assets)
  --work-dir DIR     Build/cache directory (default: out/linux)
  --sdk-source DIR   Existing SDK checkout at c94f5eb (never reset automatically)
  --jobs N           Concurrent compilation jobs (default: 4)
  --sdk-only         Build and install the patched SDK without game files
  --help            Show this help

Requires Linux x86_64, Clang >=20, CMake >=3.25, Ninja,
GCC 13+ standard library headers, and the development libraries in BUILDING.md.
Set CC/CXX to select Clang. This script does not install system packages.
EOF
}
die() { echo "error: $*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --game-dir|--work-dir|--sdk-source|--jobs)
      (($# >= 2)) && [[ -n $2 ]] || die "$1 requires a value"
      case "$1" in
        --game-dir) game_dir=$2 ;; --work-dir) work_dir=$2 ;;
        --sdk-source) sdk_source=$2 ;; --jobs) jobs=$2 ;;
      esac
      shift 2 ;;
    --sdk-only) sdk_only=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || die "only native Linux x86_64 is supported"
[[ $jobs =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer"
# Fail before downloads/builds if the game cannot be generated.
if (( ! sdk_only )); then
  [[ -f "$game_dir/default.xex" ]] || die "missing $game_dir/default.xex; use --game-dir with your extracted dump, or --sdk-only"
  game_dir=$(cd -- "$game_dir" && pwd)
fi
for tool in git cmake ninja python3 pkg-config; do
  command -v "$tool" >/dev/null || die "missing tool: $tool (see BUILDING.md)"
done
cc=${CC:-}
cxx=${CXX:-}
if [[ -z $cc && -z $cxx ]]; then
  for version in 20 21; do
    if command -v "clang-$version" >/dev/null && command -v "clang++-$version" >/dev/null; then
      cc=clang-$version; cxx=clang++-$version; break
    fi
  done
fi
cc=${cc:-clang}; cxx=${cxx:-clang++}
command -v "$cc" >/dev/null || die "missing Clang; set CC and CXX (see BUILDING.md)"
command -v "$cxx" >/dev/null || die "missing Clang++; set CC and CXX (see BUILDING.md)"
# SDK's advertised Clang 18 minimum is insufficient with GCC 13's <expected>.
# Check the real compiler/header combination before fetching or building SDK.
if ! "$cxx" -std=c++23 -x c++ -fsyntax-only - <<'CPP'
#if !defined(__clang__) || __clang_major__ < 20
#error Use Clang 20 or newer for this build
#endif
#include <expected>
std::expected<int, int> value{42};
CPP
then
  die "C++23 toolchain check failed; use Clang 20+ with GCC 13+ headers (see LINUX.md)"
fi
# CMake may silently drop SDK options when it changes a cached compiler.
# Preserve the old build and require a separate directory instead.
compiler_path=$(realpath -- "$(command -v "$cxx")")
for cache in "$work_dir/sdk-build/CMakeCache.txt" "$work_dir/game-build/CMakeCache.txt"; do
  if [[ -f $cache ]]; then
    cached_compiler=$(sed -n 's/^CMAKE_CXX_COMPILER:[^=]*=//p' "$cache")
    if [[ -n $cached_compiler && $(realpath -m -- "$cached_compiler") != "$compiler_path" ]]; then
      die "compiler changed in $cache; use a new --work-dir instead of reusing another toolchain's cache"
    fi
  fi
done
mkdir -p -- "$work_dir"
work_dir=$(cd -- "$work_dir" && pwd)
sdk_source=${sdk_source:-"$work_dir/rexglue-sdk"}
if [[ ! -e $sdk_source ]]; then
  git clone --no-checkout https://github.com/rexglue/rexglue-sdk.git "$sdk_source"
  git -C "$sdk_source" checkout --detach "$sdk_commit"
fi
sdk_source=$(cd -- "$sdk_source" && pwd)
[[ $(git -C "$sdk_source" rev-parse HEAD) == "$sdk_commit" ]] || die "SDK must be at $sdk_commit; refusing to reset existing checkout"
patch_file="$repo/sdk-patch/rexglue-sdk-v0.10-all-fixes.patch"
if git -C "$sdk_source" apply --reverse --check "$patch_file" 2>/dev/null; then
  echo "SDK patch already applied"
else
  [[ -z $(git -C "$sdk_source" status --porcelain --untracked-files=no) ]] || die "SDK has local changes; refusing to apply patch"
  git -C "$sdk_source" apply --check "$patch_file"
  git -C "$sdk_source" apply "$patch_file"
fi
# Only Linux build dependencies: omit MoltenVK and other unused SDK submodules.
submodules=(cli11 libmspack FFmpeg tomlplusplus simde xxHash spdlog fmt utfcpp
  imgui sdl3 o1heap inja vulkan-headers vulkan-memory-allocator spirv-headers
  spirv-tools glslang)
paths=()
for submodule in "${submodules[@]}"; do paths+=("thirdparty/$submodule"); done
git -C "$sdk_source" submodule update --init --recursive --jobs "$jobs" -- "${paths[@]}"
sdk_install="$work_dir/sdk-install"
cmake -S "$sdk_source" -B "$work_dir/sdk-build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cxx" \
  -DCMAKE_C_FLAGS=-march=x86-64-v2 -DCMAKE_CXX_FLAGS=-march=x86-64-v2 \
  -DCMAKE_INSTALL_PREFIX="$sdk_install" -DCMAKE_INSTALL_LIBDIR=lib \
  -DREXGLUE_USE_VULKAN=ON -DREXGLUE_USE_D3D12=OFF \
  -DREXGLUE_ENABLE_TRACY=OFF -DREXGLUE_ENABLE_FIDELITYFX=OFF -DREXGLUE_BUILD_TESTS=OFF
cmake --build "$work_dir/sdk-build" --target install --parallel "$jobs"
if (( sdk_only )); then echo "SDK installed: $sdk_install"; exit 0; fi

# A temporary manifest points codegen at external game files without copying them
# into the repository. ReXGlue resolves manifest paths relative to its location.
manifest=$(mktemp "$repo/.rrxx-codegen.XXXXXX.toml")
trap 'rm -f -- "$manifest"' EXIT
python3 - "$repo/rumble_roses_xx_manifest.toml" "$manifest" "$game_dir" <<'PY'
import json, pathlib, re, sys
source, target, game = sys.argv[1:]
text = pathlib.Path(source).read_text()
text, roots = re.subn(r'(?m)^game_root = .*$', lambda _: 'game_root = ' + json.dumps(game), text)
text, entries = re.subn(r'(?m)^file_path = "assets/default\.xex"$',
                        lambda _: 'file_path = ' + json.dumps(str(pathlib.Path(game) / 'default.xex')), text)
if (roots, entries) != (1, 1):
    raise SystemExit('Manifest layout changed: update the Linux codegen path overrides')
pathlib.Path(target).write_text(text)
PY
cd -- "$repo"
"$sdk_install/bin/rexglue" codegen "$manifest"
cmake -S "$repo" -B "$work_dir/game-build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cxx" \
  -DCMAKE_CXX_FLAGS=-march=x86-64-v2 -DCMAKE_PREFIX_PATH="$sdk_install"
cmake --build "$work_dir/game-build" --parallel "$jobs"
# The SDK's Linux helper stages the plugin but not its shared runtime.
cp -L -- "$sdk_install/lib/librexruntime.so" "$work_dir/game-build/"
echo "Game built: $work_dir/game-build/rumble_roses_xx"
echo "Run with: RRXX_GAME_DIR=\"$game_dir\" \"$work_dir/game-build/rumble_roses_xx\""
