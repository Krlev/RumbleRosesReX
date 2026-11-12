# Native Linux build and AppImage

The Linux scripts build the game and its patched ReXGlue SDK natively, with
Vulkan graphics. They do not use Wine or include the Windows Forms launcher.
This workflow is experimental. The patched SDK builds and installs on Ubuntu
24.04 with Clang 20 and GCC 13 headers, including a repeat setup run. Packaging
has been tested with a synthetic ELF fixture, but compiling the full game and
testing gameplay still require a local game dump. No playable Linux binary is
supplied with these changes.

The handwritten C++ sources also compile against that installed SDK with
synthetic guest declarations and the SDK's template macros. This checks native
API compatibility without linking a game; it does not validate generated game
code or runtime behavior.

## Requirements

- Linux x86_64 with an x86-64-v2 CPU (SSE4.2); other architectures are not covered.
- Clang 20 or newer, CMake 3.25+, Ninja, Git, Python 3,
  pkg-config, and GCC 13+ C++ standard library headers.
- X11, Wayland and audio development libraries, plus a working Vulkan graphics
  driver on the machine that runs the game.
- Your own extracted game dump, including `default.xex` and all game assets.
  DLC is optional. Keep the entire dump external to the AppImage.

On Ubuntu 24.04, first enable the official signed LLVM 20 repository
([LLVM's package instructions](https://apt.llvm.org/)):

```sh
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg
llvm_key=$(mktemp)
curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key | gpg --dearmor > "$llvm_key"
sudo install -m 644 "$llvm_key" /usr/share/keyrings/llvm-archive-keyring.gpg
rm -f "$llvm_key"
echo 'deb [signed-by=/usr/share/keyrings/llvm-archive-keyring.gpg] https://apt.llvm.org/noble/ llvm-toolchain-noble-20 main' | sudo tee /etc/apt/sources.list.d/llvm20.list
```

Then install the build prerequisites:

```sh
sudo apt-get update
sudo apt-get install clang-20 cmake ninja-build build-essential g++-13 git \
  python3 pkg-config curl file binutils autoconf libgtk-3-dev libx11-xcb-dev \
  libxss-dev libvulkan-dev libwayland-dev libwayland-bin wayland-protocols \
  libxkbcommon-dev libdecor-0-dev libasound2-dev libpulse-dev libpipewire-0.3-dev
```

Package names differ on other distributions. Build on the oldest distribution
you intend to support: an AppImage does not eliminate glibc or CPU requirements.
A build on Ubuntu 24.04 requires its glibc version or newer. Graphics drivers
remain supplied by the host. Linux x86_64 under WSL2 can build the package;
testing graphics there requires a functioning Vulkan/display setup.

## Build on the host containing your game dump

From this repository's root:

```sh
CC=clang-20 CXX=clang++-20 bash scripts/linux/build.sh \
  --game-dir "/path/to/extracted game" --jobs 4
```

The script clones SDK commit `c94f5ebdcb3c9d1a460ca48e04f9758448f8d518`, applies
the fork's SDK patch, initializes the Linux submodules, and builds a Release
SDK with Vulkan enabled. Tracy and optional FidelityFX are disabled. Then it
generates the game's recompiled sources and builds the game. Four parallel
compilation jobs is a conservative default; adjust for your available memory.

The script checks C++23 `std::expected` support before fetching the SDK. The
SDK's stated minimum of Clang 18 fails this check with Ubuntu's GCC 13 headers;
use Clang 20+. When changing compilers, choose a new `--work-dir` to avoid
CMake reusing or discarding settings from another toolchain's cache.

The default build/cache directory is `out/linux`. Use `--work-dir DIR` to change
it or `--sdk-source DIR` to reuse a checkout at that exact SDK commit. Existing
SDK checkouts are never reset. An already applied patch is reused. The script
does not install system packages or copy your dump into the checkout. Generated
code stays in ignored `generated/default`; a temporary manifest is removed
automatically. `--sdk-only` builds just the SDK without game files.

Test the native build before packaging:

```sh
RRXX_GAME_DIR="/path/to/extracted game" out/linux/game-build/rumble_roses_xx
```

Verify graphics, controller input, saving/loading and the F4 settings menu on
your machine. The Windows launcher's setup, DLC/mod-pack UI, updater and DLSS
add-on are not ported; the Linux package launches the game directly.

## Create an AppImage

Obtain `linuxdeploy-x86_64.AppImage` from the official
[linuxdeploy releases](https://github.com/linuxdeploy/linuxdeploy/releases) and
`appimagetool-x86_64.AppImage` from the official
[appimagetool releases](https://github.com/AppImage/appimagetool/releases).
Verify any checksums/signatures provided with the chosen release. Keep those
tool versions for reproducible packaging; the script does not download tools.

```sh
chmod +x /path/to/linuxdeploy-x86_64.AppImage /path/to/appimagetool-x86_64.AppImage
bash scripts/linux/package-appimage.sh \
  --binary out/linux/game-build/rumble_roses_xx \
  --sdk out/linux/sdk-install \
  --linuxdeploy /path/to/linuxdeploy-x86_64.AppImage \
  --appimagetool /path/to/appimagetool-x86_64.AppImage
```

Output: `dist/RumbleRosesReX-x86_64.AppImage`. Use `--output FILE` for a different
name and `--force` to replace an existing output. Packaging stages only the
executable, SDK libraries, resolved shared-library dependencies, desktop/icon
files and credits/licenses. The runtime-loaded Xenos plugin is staged beside
the executable. Game files, DLC, generated source, saves and settings are not
copied into the AppImage. Packaging tools run in extract-and-run mode without
FUSE. Recent appimagetool releases may also download their AppImage runtime.
For pinned or offline runtime selection, obtain `runtime-x86_64` from the official
[type2-runtime releases](https://github.com/AppImage/type2-runtime/releases),
verify the release's published checksums/signatures, and add
`--runtime-file /path/to/runtime-x86_64` to the packaging command. This option
passes the readable Linux x86_64 ELF runtime directly to appimagetool; it does
not download or execute the runtime during packaging.

## Run with portable user data

```sh
./dist/RumbleRosesReX-x86_64.AppImage --portable \
  --game-dir "/path/to/extracted game"
```

Portable mode creates `RumbleRosesReX-x86_64.AppImage.portable` beside that exact
AppImage filename. Keep this directory with the AppImage when moving it. To
keep the game dump alongside it too, place the dump in
`RumbleRosesReX-x86_64.AppImage.portable/data/rumble-roses-xx/assets`. Later
launches automatically detect an existing sidecar, so double-clicking keeps
portable mode enabled. Set `RRXX_PORTABLE=0` to opt out, or `RRXX_PORTABLE=1`
to force it. The sidecar directory must be writable;
`RRXX_PORTABLE_DIR=/some/writable/directory` overrides it and enables portable
mode unless `RRXX_PORTABLE=0` is set.
Renaming the AppImage also changes its default sidecar name, so rename/move the
existing sidecar with it or use the override.

| Content | Path inside the portable directory |
| --- | --- |
| Game dump (optional location) | `data/rumble-roses-xx/assets/` |
| Saves and installed DLC | `data/rumble-roses-xx/saves/` |
| Mods | `data/rumble-roses-xx/mods/` |
| Save backups | `data/rumble-roses-xx/save-backups/` |
| Settings | `config/rumble-roses-xx/RumbleRosesReX.toml` |
| Shader cache and logs | `cache/rumble-roses-xx/` |

With portable mode disabled, the same subpaths use standard `$XDG_DATA_HOME`
(`~/.local/share`), `$XDG_CONFIG_HOME` (`~/.config`) and `$XDG_CACHE_HOME`
(`~/.cache`). `RRXX_GAME_DIR` selects an external dump, and `--game-dir` also
sets the runtime's `game_data_root` option. Explicit runtime options and TOML
path overrides are supported. Absolute paths in a copied TOML still refer to
the old location: remove those overrides to use portable defaults.

`--help` works without game files. Pass game options after `--`, for example:

```sh
./dist/RumbleRosesReX-x86_64.AppImage --portable -- --fullscreen
```

On systems without FUSE, use `--appimage-extract-and-run` before the wrapper
options. The F4 "Open saves folder" button is currently Windows-only; open the
saves path listed above manually.

## Script regression checks

```sh
python3 -m unittest discover -s tests/linux -v
```

The 26 checks use temporary fixtures, including compilation of the real app
header against a small SDK API fixture. They do not validate gameplay or
replace building and running against your own dump.
