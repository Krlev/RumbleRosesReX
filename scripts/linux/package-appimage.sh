#!/usr/bin/env bash
set -euo pipefail
umask 022

usage() {
  cat <<'EOF'
Usage: package-appimage.sh --binary FILE --sdk DIR [options]

Package a native Linux x86_64 Release build. Game data and saves are never copied.

  --binary FILE         Built rumble_roses_xx ELF executable
  --sdk DIR             Patched ReXGlue SDK installation used for this build
  --linuxdeploy FILE    linuxdeploy executable or AppImage (or LINUXDEPLOY)
  --appimagetool FILE    appimagetool executable or AppImage (or APPIMAGETOOL)
  --runtime-file FILE    Use a verified local AppImage runtime instead of downloading
  --output FILE         Output AppImage (default: dist/RumbleRosesReX-x86_64.AppImage)
  --force               Replace an existing output AppImage
  -h, --help            Show this help

Obtain the packaging tools from their official releases and verify their
published checksums before use. AppImage tools run without requiring FUSE.
Build on the oldest Linux distribution you intend to support; host graphics
drivers are not bundled. The Windows Forms launcher is not included.
EOF
}

fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
repo=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
binary= sdk= linuxdeploy=${LINUXDEPLOY:-} appimagetool=${APPIMAGETOOL:-}
runtime_file=
output="$repo/dist/RumbleRosesReX-x86_64.AppImage"
force=0
while (($#)); do
  case "$1" in
    --binary|--sdk|--linuxdeploy|--appimagetool|--runtime-file|--output)
      (($# >= 2)) || fail "missing value for $1"
      case "$1" in
        --binary) binary=$2;;
        --sdk) sdk=$2;;
        --linuxdeploy) linuxdeploy=$2;;
        --appimagetool) appimagetool=$2;;
        --runtime-file) [[ -n $2 ]] || fail '--runtime-file requires a file'; runtime_file=$2;;
        --output) output=$2;;
      esac
      shift 2;;
    --force) force=1; shift;;
    -h|--help) usage; exit 0;;
    *) fail "unknown argument: $1";;
  esac
done
[[ $(uname -sm) == 'Linux x86_64' ]] || fail 'requires a Linux x86_64 build host'
[[ -n $binary && -n $sdk ]] || { usage >&2; exit 1; }
for tool in readelf realpath find install; do
  command -v "$tool" >/dev/null || fail "required command not found: $tool"
done
[[ -x $binary ]] || fail "not an executable: $binary"
[[ -d $sdk ]] || fail "SDK installation not found: $sdk"
[[ -n $linuxdeploy && -x $linuxdeploy ]] || fail 'supply an executable with --linuxdeploy or LINUXDEPLOY'
[[ -n $appimagetool && -x $appimagetool ]] || fail 'supply an executable with --appimagetool or APPIMAGETOOL'
binary=$(realpath -- "$binary")
sdk=$(realpath -- "$sdk")
linuxdeploy=$(realpath -- "$linuxdeploy")
appimagetool=$(realpath -- "$appimagetool")
output=$(realpath -m -- "$output")
[[ ! -e $output || $force == 1 ]] || fail "output already exists (use --force): $output"

assert_elf() {
  local header
  header=$(LC_ALL=C readelf -h -- "$1" 2>/dev/null) || fail "not an ELF binary: $1"
  [[ $header == *'Advanced Micro Devices X86-64'* ]] || fail "not a Linux x86_64 binary: $1"
}
assert_elf "$binary"
if [[ -n $runtime_file ]]; then
  [[ -f $runtime_file && -r $runtime_file ]] || fail "runtime file is not readable: $runtime_file"
  runtime_file=$(realpath -- "$runtime_file")
  assert_elf "$runtime_file"
fi
plugin=
for candidate in "$(dirname -- "$binary")/librexgpu-xenos.so" \
    "$sdk/lib/librexgpu-xenos.so" "$sdk/lib64/librexgpu-xenos.so"; do
  if [[ -f $candidate ]]; then plugin=$candidate; break; fi
done
[[ -n $plugin ]] || fail 'Release librexgpu-xenos.so not found beside the executable or in SDK lib/lib64'
assert_elf "$plugin"

work=$(mktemp -d "${TMPDIR:-/tmp}/rrxx-appimage.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
appdir="$work/RumbleRosesReX.AppDir"
install -d "$appdir/usr/bin" "$appdir/usr/lib" "$appdir/usr/share/applications" \
  "$appdir/usr/share/icons/hicolor/scalable/apps" "$appdir/usr/share/doc/rumble-roses-rex/licenses"
install -m755 "$binary" "$appdir/usr/bin/rumble_roses_xx"
# ReXGlue dlopens its GPU plugin by an absolute path beside the executable.
install -m755 "$plugin" "$appdir/usr/bin/librexgpu-xenos.so"

# Only shared libraries from this SDK installation are staged, never arbitrary
# build-directory contents (which may include game files, configs or saves).
libdirs=()
for libdir in "$sdk/lib" "$sdk/lib64"; do
  if [[ -d $libdir ]]; then libdirs+=("$libdir"); fi
done
for libdir in "${libdirs[@]}"; do
  while IFS= read -r -d '' library; do
    case $(basename -- "$library") in librexgpu-*) continue;; esac
    install -m755 "$library" "$appdir/usr/lib/$(basename -- "$library")"
  done < <(find "$libdir" -maxdepth 2 \( -type f -o -type l \) -name '*.so*' -print0)
done
install -m644 "$repo/packaging/linux/rumble-roses-rex.desktop" "$appdir/usr/share/applications/"
install -m644 "$repo/packaging/linux/rumble-roses-rex.svg" "$appdir/usr/share/icons/hicolor/scalable/apps/"
install -m755 "$repo/packaging/linux/AppRun" "$appdir/AppRun"
install -m644 "$repo/CREDITS.md" "$appdir/usr/share/doc/rumble-roses-rex/"
for license in "$repo"/licenses/*; do
  [[ ! -f $license ]] || install -m644 "$license" "$appdir/usr/share/doc/rumble-roses-rex/licenses/"
done

run_tool() {
  local tool=$1
  shift
  # AppImage type 2 runtime marker at offset 8. Native tools do not accept this
  # runtime-only argument, so detect the marker rather than guessing by name.
  if [[ $(od -An -tx1 -j8 -N3 -- "$tool" | tr -d ' \n') == 414902 ]]; then
    "$tool" --appimage-extract-and-run "$@"
  else
    "$tool" "$@"
  fi
}
export LD_LIBRARY_PATH="$appdir/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
deploy_args=(--appdir "$appdir" --executable "$appdir/usr/bin/rumble_roses_xx"
  --library "$appdir/usr/bin/librexgpu-xenos.so"
  --desktop-file "$appdir/usr/share/applications/rumble-roses-rex.desktop"
  --icon-file "$appdir/usr/share/icons/hicolor/scalable/apps/rumble-roses-rex.svg"
  --custom-apprun "$repo/packaging/linux/AppRun")
for library in "$appdir"/usr/lib/*.so*; do
  [[ ! -f $library ]] || deploy_args+=(--library "$library")
done
run_tool "$linuxdeploy" "${deploy_args[@]}"
# linuxdeploy may normalize the dependency location to usr/lib. Preserve the
# executable-relative name required by LoadGpuPlugin regardless of that choice.
if [[ ! -f $appdir/usr/bin/librexgpu-xenos.so ]]; then
  [[ -f $appdir/usr/lib/librexgpu-xenos.so ]] || fail 'linuxdeploy removed the GPU plugin'
  ln -s ../lib/librexgpu-xenos.so "$appdir/usr/bin/librexgpu-xenos.so"
fi
# An explicit .DirIcon also supports the SVG icon with appimagetool versions
# which only try PNG/XPM when choosing this symlink themselves.
ln -sfn rumble-roses-rex.svg "$appdir/.DirIcon"
# Some linuxdeploy releases create directories according to inherited umask;
# ensure the mounted image can be traversed by users other than its builder.
chmod -R a+rX "$appdir"
mkdir -p -- "$(dirname -- "$output")"
image_args=()
if [[ -n $runtime_file ]]; then image_args+=(--runtime-file "$runtime_file"); fi
ARCH=x86_64 run_tool "$appimagetool" "${image_args[@]}" "$appdir" "$work/output.AppImage"
[[ -s $work/output.AppImage ]] || fail 'appimagetool did not produce an AppImage'
[[ $(od -An -tx1 -j8 -N3 -- "$work/output.AppImage" | tr -d ' \n') == 414902 ]] || fail 'output is not a type 2 AppImage'
install -m755 "$work/output.AppImage" "$output"
printf 'AppImage created: %s\n' "$output"
printf 'Game data is external. Set RRXX_GAME_DIR to the directory containing default.xex.\n'
