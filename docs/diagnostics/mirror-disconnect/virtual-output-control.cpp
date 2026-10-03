// Diagnostic only: exercise mirror teardown in a private nested compositor.
#include <cstdlib>
#include <stdexcept>
#include <sstream>
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/debug/HyprCtl.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <aquamarine/backend/Backend.hpp>

static PHLMONITOR virtualMonitor(const std::string& name) {
    const auto mon = State::monitorState()->query().includeDisabled(true).name(name).run();
    if (!mon || !mon->m_createdByUser || !mon->m_output || mon->m_output->getBackend()->type() != Aquamarine::AQ_BACKEND_WAYLAND)
        return nullptr;
    return mon;
}

static std::string control(eHyprCtlOutputFormat, std::string request) {
    std::istringstream args(request);
    std::string        command, action, name;
    args >> command >> action;
    if (action == "remove") {
        while (args >> name) {
            const auto mon = virtualMonitor(name);
            if (!mon)
                return "Expected a virtual output";
            mon->m_output->destroy();
        }
        return "ok";
    }

    args >> name;
    const auto mon = virtualMonitor(name);
    if (!mon)
        return "Expected a virtual output";
    if (action == "mirrors")
        return std::to_string(mon->m_mirrors.size());
    if (action == "disabled-mirror") {
        // Reproduce the observed disabled/mirrored state without depending on
        // DRM-specific mode events. Use the compositor's real mirror method.
        std::string sourceName;
        args >> sourceName;
        const auto source = virtualMonitor(sourceName);
        if (mon->m_enabled || !source || !source->m_enabled || source->isMirror())
            return "Expected a disabled output and an enabled mirror source";
        mon->setMirror(sourceName);
        return mon->isMirror() ? "ok" : "Mirror source unavailable";
    }
    if (action == "null-source") {
        // An expired weak reference resolves to null, as in the captured core.
        // Destroy synchronously so rendering never sees this injected entry.
        if (!mon->m_enabled || mon->isMirror())
            return "Expected an enabled independent source";
        mon->m_mirrors.insert(mon->m_mirrors.begin(), PHLMONITORREF{});
        mon->m_output->destroy();
        return "ok";
    }
    return "Unknown test action";
}

APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    const auto test = std::getenv("HYPERTILE_MIRROR_TEST");
    if (!test || std::string(test) != "1")
        throw std::runtime_error("This diagnostic requires an isolated mirror test compositor");
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
        throw std::runtime_error("ABI mismatch");
    for (const auto& mon : State::monitorState()->allMonitors()) {
        if (!mon->m_createdByUser || !mon->m_output || mon->m_output->getBackend()->type() == Aquamarine::AQ_BACKEND_DRM)
            throw std::runtime_error("Refusing a compositor with physical outputs");
    }
    if (!HyprlandAPI::registerHyprCtlCommand(handle, {"hypertile-test", false, control}))
        throw std::runtime_error("Could not register virtual output control");
    return {"hypertile-virtual-output-control", "Isolated mirror disconnect regression", "Hypertile", "1"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    ;
}
