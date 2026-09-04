// Diagnostic ONLY: run in an isolated headless compositor, never the desktop.
// Calls the compiled compositor's onAck method, then restores all touched state.
#include <cstdlib>
#include <stdexcept>
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/view/WLSurface.hpp>
#include <hyprland/src/protocols/core/Compositor.hpp>

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }
APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE) {
    const auto headless = std::getenv("HYPRLAND_HEADLESS_ONLY");
    if (!headless || std::string(headless) != "1")
        throw std::runtime_error("This diagnostic requires an isolated headless compositor");
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
        throw std::runtime_error("ABI mismatch");

    bool checked = false;
    for (const auto& w : Desktop::windowState()->windows()) {
        if (!w->m_isMapped || w->m_isX11 || w->m_class != "hypertile-backport-smoke" || !w->wlSurface() || !w->wlSurface()->resource())
            continue;
        const auto surface = w->wlSurface()->resource();
        const auto queue = w->m_pendingSizeAcks;
        const auto pending = w->m_pendingSizeAck;
        const auto size = surface->m_pending.ackedSize;
        const auto bit = surface->m_pending.updated.bits.acked;
        w->m_pendingSizeAcks = {{100, {900, 600}}, {101, {4448, 2506}}, {101, {2218, 1246}}};
        w->onAck(100);
        const bool preserved = w->m_pendingSizeAcks.size() == 2;
        w->onAck(101);
        const bool correct = surface->m_pending.ackedSize == Vector2D{2218, 1246};
        w->m_pendingSizeAcks = queue;
        w->m_pendingSizeAck = pending;
        surface->m_pending.ackedSize = size;
        surface->m_pending.updated.bits.acked = bit;
        if (!preserved || !correct)
            throw std::runtime_error("Compiled onAck lost a future size record or selected the wrong final size");
        checked = true;
    }
    if (!checked)
        throw std::runtime_error("No headless smoke-test window found");
    return {"hypertile-ack-check", "Compiled onAck regression passed", "Hypertile", "1"};
}
APICALL EXPORT void PLUGIN_EXIT() {}
