// RumbleRosesReX - ReXGlue Recompiled Project
//
// Customize your app by overriding virtual hooks from rex::ReXApp.

#pragma once

#include <cstdlib>

#if defined(__linux__)
#include <pwd.h>
#include <unistd.h>
#endif

#include <rex/audio/audio_driver.h>
#include <rex/cvar.h>
#include <rex/filesystem.h>
#include <rex/rex_app.h>
#include <rex/runtime.h>
#include <rex/system/gpu_plugin.h>

#include <rex/input/input_system.h>
#include <rex/logging.h>

REXCVAR_DECLARE(std::string, gpu_backend);
REXCVAR_DECLARE(bool, pause_on_focus_loss);

class RumbleRosesXxApp : public rex::ReXApp {
 public:
  using rex::ReXApp::ReXApp;

  static std::unique_ptr<rex::ui::WindowedApp> Create(
      rex::ui::WindowedAppContext& ctx) {
    return std::unique_ptr<RumbleRosesXxApp>(new RumbleRosesXxApp(ctx, "RumbleRosesReX",
        PPCImageConfig));
  }

  // Override virtual hooks for customization:
  // void OnPostInitLogging() override {}
  void OnPreSetup(rex::RuntimeConfig& config) override {
    // SDK v0.10 moved Xenos GPU emulation into the runtime-loaded rexgpu-xenos
    // plugin; pick the backend inside it from our gpu_backend cvar.
    if (!config.graphics) {
      config.graphics = rex::system::LoadGpuPlugin("xenos", REXCVAR_GET(gpu_backend));
      if (!config.graphics) {
        // Let ReXApp retry with any backend and show its fatal dialog on failure.
        config.gpu_plugin = "xenos";
      }
    }
  }
  // Alt-tab: mute audio and hide the pad from the game (no thread suspend).
  void OnWindowFocusChanged(bool focused) override {
    const bool block = !focused && REXCVAR_GET(pause_on_focus_loss);
    rex::audio::g_audio_muted.store(block);
    rex::input::g_input_blocked.store(block);
    REXLOG_INFO("Window {}: audio {} / pad {}", focused ? "focused" : "unfocused",
                block ? "muted" : "on", block ? "ignored" : "active");
  }
  // void OnLoadXexImage(std::string& xex_image) override {}
  // void OnPostSetup() override {}
  // void OnCreateDialogs(rex::ui::ImGuiDrawer* drawer) override {}
  // void OnShutdown() override {}
  void OnConfigurePaths(rex::PathConfig& paths) override {
#if defined(__linux__)
    // An AppImage is read-only. Keep configuration, saves, mods and caches in
    // writable XDG directories, including when the game is launched directly.
    std::filesystem::path home;
    if (const auto* value = std::getenv("HOME"); value && *value)
      home = value;
    if (home.empty()) {
      if (const auto* user = getpwuid(getuid()); user && user->pw_dir)
        home = user->pw_dir;
    }
    auto xdg_dir = [&home](const char* name, const std::filesystem::path& fallback) {
      if (const auto* value = std::getenv(name); value && *value) {
        auto path = rex::to_path(value);
        if (path.is_absolute())
          return path;
      }
      return home / fallback;
    };
    const auto data = xdg_dir("XDG_DATA_HOME", ".local/share") / "rumble-roses-xx";
    const auto config = xdg_dir("XDG_CONFIG_HOME", ".config") / "rumble-roses-xx";
    const auto cache = xdg_dir("XDG_CACHE_HOME", ".cache") / "rumble-roses-xx";
    paths.config_path = config / "RumbleRosesReX.toml";

    std::filesystem::path game = data / "assets";
    if (const auto* value = std::getenv("RRXX_GAME_DIR"); value && *value)
      game = rex::to_path(value);
    // Derived paths are defaults, not user settings. The SDK saves every cvar
    // that differs from its default; leaving these as runtime overrides would
    // persist absolute mount/sidecar paths and break portable relocation.
    // This hook runs during initialization, before GPU plugins register cvars.
    auto path_default = [](const char* name, const std::filesystem::path& path) {
      const auto value = rex::path_to_utf8(path);
      for (auto& entry : rex::cvar::GetRegistry()) {
        if (entry.name != name)
          continue;
        entry.default_value = value;
        if (entry.source == rex::cvar::Source::kDefault || entry.getter().empty()) {
          entry.setter(value);
          entry.source = rex::cvar::Source::kDefault;
        }
        break;
      }
    };
    // The SDK resolves its path defaults before this hook. Load the user's
    // config now and resolve them again; command-line cvars retain precedence.
    rex::cvar::LoadConfig(paths.config_path);
    path_default("game_data_root", game);
    path_default("user_data_root", data / "saves");
    path_default("mods_root", data / "mods");
    path_default("cache_root", cache);
    path_default("log_file", cache / "logs" / "RumbleRosesReX.log");
    auto configured_path = [](const char* name, const std::filesystem::path& fallback) {
      const auto value = rex::cvar::GetFlagByName(name);
      return value.empty() ? fallback : rex::to_path(value);
    };
    paths.game_data_root = configured_path("game_data_root", game);
    paths.user_data_root = configured_path("user_data_root", data / "saves");
    paths.cache_root = configured_path("cache_root", cache);
    paths.update_data_root = configured_path("update_data_root", paths.update_data_root);
    paths.metadata_root = configured_path("metadata_root", paths.metadata_root);
    const auto mods = configured_path("mods_root", data / "mods");

    for (const auto& directory : {config, paths.user_data_root, paths.cache_root, mods,
                                  cache / "logs"}) {
      std::error_code ec;
      std::filesystem::create_directories(directory, ec);
      if (ec)
        REXLOG_WARN("Cannot create directory {}: {}", directory.string(), ec.message());
    }
    return;
#endif
    if (!paths.game_data_root.empty())
      return;

    const auto exe_dir = rex::filesystem::GetExecutableFolder();
    for (const auto& candidate : {
             exe_dir / "assets",
             exe_dir / ".." / ".." / ".." / "assets",
             exe_dir / ".." / ".." / "assets",
             std::filesystem::current_path() / "assets",
         }) {
      std::error_code ec;
      auto resolved = std::filesystem::weakly_canonical(candidate, ec);
      if (!ec && std::filesystem::is_directory(resolved)) {
        paths.game_data_root = resolved;
        return;
      }
    }
  }
};
