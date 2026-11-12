"""Compile the real Linux path hook against a small SDK API fixture.

This checks the app's path policy without game files or a built SDK. The cvar
fixture models the pinned SDK's source ordering; it does not validate its TOML
parser, ABI, or the game. Run with unittest discovery from tests/linux.
"""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]

SDK_FIXTURE = r"""
#pragma once
#include <atomic>
#include <cstdlib>
#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <string_view>
#include <vector>
#define REXLOG_WARN(...) ((void)0)
#define REXLOG_INFO(...) ((void)0)
#define REXCVAR_DECLARE(type, name) extern type name
#define REXCVAR_GET(name) name
inline int PPCImageConfig = 0;
inline std::string gpu_backend = "vulkan";
inline bool pause_on_focus_loss = true;
namespace rex {
struct PathConfig {
  std::filesystem::path game_data_root, user_data_root, update_data_root;
  std::filesystem::path cache_root, metadata_root, config_path;
};
struct RuntimeConfig { std::unique_ptr<int> graphics; std::string gpu_plugin; };
inline std::filesystem::path to_path(std::string_view s) { return std::filesystem::path(s); }
inline std::string path_to_utf8(const std::filesystem::path& p) { return p.string(); }
namespace filesystem {
inline std::filesystem::path executable;
inline std::filesystem::path GetExecutableFolder() { return executable; }
}
namespace audio { inline std::atomic_bool g_audio_muted{false}; }
namespace input { inline std::atomic_bool g_input_blocked{false}; }
namespace ui {
class WindowedAppContext {};
class WindowedApp { public: virtual ~WindowedApp() = default; };
}
class ReXApp : public ui::WindowedApp {
 public:
  ReXApp(ui::WindowedAppContext&, const char*, int) {}
  virtual void OnPreSetup(RuntimeConfig&) {}
  virtual void OnWindowFocusChanged(bool) {}
  virtual void OnConfigurePaths(PathConfig&) {}
};
namespace system {
inline std::unique_ptr<int> LoadGpuPlugin(std::string_view, std::string_view) { return {}; }
}
namespace cvar {
enum class Source { kDefault, kConfig, kEnvironment, kCommandLine, kRuntime };
struct FlagEntry {
  std::string name, default_value;
  Source source = Source::kDefault;
  std::function<bool(std::string_view)> setter;
  std::function<std::string()> getter;
};
inline std::map<std::string, std::string> values;
inline std::vector<FlagEntry> registry;
inline std::map<std::string, std::string> config_flags;
inline std::filesystem::path loaded_config;
inline std::vector<FlagEntry>& GetRegistry() { return registry; }
inline void Reset() {
  values.clear(); registry.clear(); config_flags.clear();
  for (const std::string name : {"game_data_root", "user_data_root", "mods_root",
                                 "cache_root", "log_file", "update_data_root",
                                 "metadata_root", "resolution_scale"}) {
    const std::string initial = name == "resolution_scale" ? "2" : "";
    values[name] = initial;
    registry.push_back({name, initial, Source::kDefault,
      [name](std::string_view value) { values[name] = value; return true; },
      [name] { return values[name]; }});
  }
}
inline bool Apply(std::string_view name, std::string_view value, Source source) {
  for (auto& entry : registry) {
    if (entry.name != name) continue;
    if (source < entry.source || !entry.setter(value)) return false;
    entry.source = source;
    return true;
  }
  return false;
}
inline std::string GetFlagByName(std::string_view name) { return values[std::string(name)]; }
inline bool SetFlagByName(std::string_view name, std::string_view value) {
  return Apply(name, value, Source::kRuntime);
}
inline void LoadConfig(const std::filesystem::path& path) {
  loaded_config = path;
  for (const auto& [name, value] : config_flags) Apply(name, value, Source::kConfig);
}
// Match SerializeToTOML's selection exactly: source does not matter, only
// getter() != default_value. The fixture omits text formatting/parsing.
inline std::map<std::string, std::string> SavedValues() {
  std::map<std::string, std::string> saved;
  for (const auto& entry : registry)
    if (entry.getter() != entry.default_value) saved[entry.name] = entry.getter();
  return saved;
}
}
}
"""

CONTRACT = r"""
#include <cassert>
#include <iostream>
#include "rumble_roses_xx_app.h"

int main(int, char** argv) {
  namespace fs = std::filesystem;
  namespace cv = rex::cvar;
  const fs::path base = argv[1];
  const auto home = base / "Home With Spaces";
  setenv("HOME", home.c_str(), 1);
  for (auto name : {"XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "RRXX_GAME_DIR"})
    unsetenv(name);
  rex::filesystem::executable = base / "mounted AppImage/usr/bin";
  fs::create_directories(rex::filesystem::executable / "assets");
  fs::create_directories(rex::filesystem::executable / "../saves");
  rex::ui::WindowedAppContext context;
  RumbleRosesXxApp app(context, "test", 0);
  auto resolve = [&] {
    // Mimic SDK defaults resolved before the application's hook.
    rex::PathConfig result;
    result.user_data_root = base / "sdk-default-saves";
    result.cache_root = result.user_data_root / "cache";
    result.config_path = rex::filesystem::executable / "RumbleRosesReX.toml";
    app.OnConfigurePaths(result);
    return result;
  };
  auto reset = [] { cv::Reset(); };
  reset();

  auto paths = resolve();
  const auto data = home / ".local/share/rumble-roses-xx";
  assert(paths.game_data_root == data / "assets");
  assert(paths.user_data_root == data / "saves");
  assert(paths.config_path == home / ".config/rumble-roses-xx/RumbleRosesReX.toml");
  assert(cv::loaded_config == paths.config_path);
  assert(paths.cache_root == home / ".cache/rumble-roses-xx");
  assert(cv::GetFlagByName("mods_root") == (data / "mods").string());
  assert(cv::GetFlagByName("game_data_root") == paths.game_data_root.string());
  assert(cv::GetFlagByName("user_data_root") == paths.user_data_root.string());
  assert(cv::GetFlagByName("log_file") == (paths.cache_root / "logs/RumbleRosesReX.log").string());
  for (const auto& dir : {paths.config_path.parent_path(), paths.cache_root,
                          paths.user_data_root, data / "mods", paths.cache_root / "logs"})
    assert(fs::is_directory(dir));
  assert(!fs::exists(rex::filesystem::executable / "RumbleRosesReX.toml"));
  assert(cv::SavedValues().empty());

  // Portable mode supplies XDG directories outside the mounted AppImage.
  reset();
  const auto portable = base / "Game.AppImage.portable";
  setenv("XDG_DATA_HOME", (portable / "data").c_str(), 1);
  setenv("XDG_CONFIG_HOME", (portable / "config").c_str(), 1);
  setenv("XDG_CACHE_HOME", (portable / "cache").c_str(), 1);
  paths = resolve();
  assert(paths.game_data_root == portable / "data/rumble-roses-xx/assets");
  assert(paths.user_data_root == portable / "data/rumble-roses-xx/saves");
  assert(paths.config_path == portable / "config/rumble-roses-xx/RumbleRosesReX.toml");
  assert(paths.cache_root == portable / "cache/rumble-roses-xx");

  reset();
  setenv("RRXX_GAME_DIR", (base / "Owned Game").c_str(), 1);
  paths = resolve();
  assert(paths.game_data_root == base / "Owned Game");

  // TOML path cvars must replace the SDK's already-resolved defaults.
  reset();
  cv::config_flags = {{"game_data_root", (base / "configured-game").string()},
                      {"user_data_root", (base / "configured-saves").string()},
                      {"cache_root", (base / "configured-cache").string()},
                      {"mods_root", (base / "configured-mods").string()},
                      {"update_data_root", (base / "updates").string()},
                      {"metadata_root", (base / "metadata").string()},
                      {"log_file", (base / "custom.log").string()}};
  paths = resolve();
  assert(paths.game_data_root == base / "configured-game");
  assert(paths.user_data_root == base / "configured-saves");
  assert(paths.cache_root == base / "configured-cache");
  assert(paths.update_data_root == base / "updates");
  assert(paths.metadata_root == base / "metadata");
  assert(cv::GetFlagByName("mods_root") == (base / "configured-mods").string());
  assert(cv::GetFlagByName("log_file") == (base / "custom.log").string());

  // Command-line values retain the pinned SDK's higher source priority.
  cv::Apply("game_data_root", (base / "cli-game").string(), cv::Source::kCommandLine);
  cv::Apply("user_data_root", (base / "cli-saves").string(), cv::Source::kCommandLine);
  paths = resolve();
  assert(paths.game_data_root == base / "cli-game");
  assert(paths.user_data_root == base / "cli-saves");

  reset();
  unsetenv("RRXX_GAME_DIR");
  for (auto name : {"XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"})
    setenv(name, "invalid-relative-directory", 1);
  paths = resolve();
  assert(paths.game_data_root == data / "assets");
  assert(paths.config_path == home / ".config/rumble-roses-xx/RumbleRosesReX.toml");
  assert(paths.cache_root == home / ".cache/rumble-roses-xx");

  // F4 saves all changed getters, even if the source is not kRuntime. Saving
  // ordinary settings must not freeze derived absolute portable paths.
  reset();
  setenv("XDG_DATA_HOME", (portable / "data").c_str(), 1);
  setenv("XDG_CONFIG_HOME", (portable / "config").c_str(), 1);
  setenv("XDG_CACHE_HOME", (portable / "cache").c_str(), 1);
  setenv("RRXX_GAME_DIR", (portable / "owned-game").c_str(), 1);
  cv::Apply("game_data_root", (portable / "owned-game").string(), cv::Source::kCommandLine);
  paths = resolve();
  cv::Apply("resolution_scale", "3", cv::Source::kRuntime);
  const auto saved = cv::SavedValues();
  assert(saved.size() == 1 && saved.at("resolution_scale") == "3");
  reset();  // Fresh process after moving the entire sidecar to another folder.
  cv::config_flags = saved;
  const auto moved = base / "Relocated Folder/Game.AppImage.portable";
  setenv("XDG_DATA_HOME", (moved / "data").c_str(), 1);
  setenv("XDG_CONFIG_HOME", (moved / "config").c_str(), 1);
  setenv("XDG_CACHE_HOME", (moved / "cache").c_str(), 1);
  setenv("RRXX_GAME_DIR", (moved / "owned-game").c_str(), 1);
  cv::Apply("game_data_root", (moved / "owned-game").string(), cv::Source::kCommandLine);
  paths = resolve();
  assert(paths.game_data_root == moved / "owned-game");
  assert(paths.user_data_root == moved / "data/rumble-roses-xx/saves");
  assert(paths.cache_root == moved / "cache/rumble-roses-xx");
  assert(cv::GetFlagByName("mods_root") == (moved / "data/rumble-roses-xx/mods").string());
  assert(cv::GetFlagByName("log_file") == (moved / "cache/rumble-roses-xx/logs/RumbleRosesReX.log").string());
  assert(cv::SavedValues() == saved);
  cv::Apply("game_data_root", (base / "explicit-native-override").string(), cv::Source::kCommandLine);
  paths = resolve();
  assert(paths.game_data_root == base / "explicit-native-override");
  assert(cv::SavedValues().at("game_data_root") == paths.game_data_root.string());
  std::cout << "PASS: actual header Linux path contract (seven scenarios, including save/relocation)\n";
}
"""


@unittest.skipUnless(sys.platform == "linux", "Linux path hook")
class LinuxPathTests(unittest.TestCase):
    def test_actual_app_header_resolves_writable_paths_and_preserves_overrides(self):
        compiler = shlex.split(os.environ.get("CXX", "g++"))
        if not compiler or not shutil.which(compiler[0]):
            self.skipTest("a C++23 compiler is required; set CXX or install g++")
        with tempfile.TemporaryDirectory(prefix="rrxx-path-contract-") as directory:
            temp = Path(directory)
            probe = temp / "probe.cpp"
            probe.write_text("int main() {}\n")
            result = subprocess.run(
                [*compiler, "-std=c++23", str(probe), "-o", str(temp / "probe")],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode:
                self.skipTest("CXX cannot compile C++23: " + result.stderr.strip())
            include = temp / "include"
            include.mkdir()
            (include / "stub.h").write_text(SDK_FIXTURE)
            for header in (
                "audio/audio_driver.h", "cvar.h", "filesystem.h", "rex_app.h",
                "runtime.h", "system/gpu_plugin.h", "input/input_system.h", "logging.h",
            ):
                path = include / "rex" / header
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#include <stub.h>\n')
            source = temp / "contract.cpp"
            source.write_text(CONTRACT)
            executable = temp / "contract"
            result = subprocess.run(
                [*compiler, "-std=c++23", "-I" + str(include), "-I" + str(ROOT / "src"),
                 str(source), "-o", str(executable)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run(
                [str(executable), str(temp / "storage")],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("save/relocation", result.stdout)


if __name__ == "__main__":
    unittest.main()
