#!/usr/bin/env python3
"""Exercise the actual Hyprland 0.56.2 onAck body, before/after the backport.

Usage: python3 verify.py /path/to/Hyprland-0.56.2
Only a C++23 compiler is needed; no running compositor is modified.
"""

import pathlib
import subprocess
import sys
import tempfile

source = (pathlib.Path(sys.argv[1]) / "src/desktop/view/Window.cpp").read_text()
start = source.index("void CWindow::onAck(uint32_t serial) {")
body = source[start : source.index("\n}\n", start) + 2]
old = "std::erase_if(m_pendingSizeAcks, [&](const auto& el) { return el.first <= SERIAL->first; });"
new = "std::erase_if(m_pendingSizeAcks, [serial](const auto& el) { return el.first <= serial; });"
assert body.count(old) == 1, "Expected the unpatched 0.56.2 acknowledgment handler"

fixture = r"""
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <optional>
#include <ranges>
#include <utility>
#include <vector>

// Only the storage accessed by onAck is modeled. The method under test is
// extracted verbatim from the compositor source supplied to this script.
struct Size {
    int x = 0, y = 0;
    bool operator==(const Size&) const = default;
};
using Entry = std::pair<uint32_t, Size>;
struct Surface {
    struct {
        Size ackedSize;
        struct { struct { bool acked = false; } bits; } updated;
    } m_pending;
    Surface* resource() { return this; }
};
struct WindowState {
    std::vector<Entry> m_pendingSizeAcks;
    std::optional<Entry> m_pendingSizeAck;
    bool m_isX11 = false;
    Surface surface;
    Surface* m_wlSurface = &surface;
};
struct OriginalWindow : WindowState { void onAck(uint32_t); };
struct FixedWindow : WindowState { void onAck(uint32_t); };
"""

tests = r"""
template<class Window> int example(const char* name) {
    Window w;
    w.m_pendingSizeAcks = {
        {100, {900, 600}}, {101, {4448, 2506}}, {101, {2218, 1246}}
    };
    w.onAck(100);
    const auto remaining = w.m_pendingSizeAcks.size();
    w.onAck(101);
    const auto size = w.surface.m_pending.ackedSize;
    std::cout << name << ": " << remaining << " future records retained; final ack "
              << size.x << "x" << size.y << " (expected 2218x1246)\n";
    return size != Size{2218, 1246};
}

template<class Window> void check(const std::vector<Entry>& input, int& cases, int& failures) {
    // Sequential, skipped, repeated, and out-of-date acknowledgments.
    for (const auto& sequence : std::vector<std::vector<uint32_t>>{
             {0, 1, 2, 3, 4, 5}, {2, 4}, {1, 1, 0, 4}, {4, 3, 5}}) {
        Window w;
        w.m_pendingSizeAcks = input;
        auto expected = input;
        Size last;
        for (auto serial : sequence) {
            std::vector<Entry> future;
            for (const auto& e : expected) {
                if (e.first <= serial) last = e.second;
                else future.push_back(e);
            }
            expected = future;
            w.onAck(serial);
            ++cases;
            if (w.m_pendingSizeAcks != expected || w.surface.m_pending.ackedSize != last)
                ++failures;
        }
    }
}

template<class Window> void enumerate(std::vector<Entry>& input, int& cases, int& failures) {
    check<Window>(input, cases, failures);
    if (input.size() == 7) return;
    for (uint32_t serial = input.empty() ? 1 : input.back().first; serial <= 4; ++serial) {
        const int n = input.size() + 1;
        input.push_back({serial, {100 * n, 60 * n}});
        enumerate<Window>(input, cases, failures);
        input.pop_back();
    }
}

int main() {
    const int originalExample = example<OriginalWindow>("0.56.2");
    const int fixedExample = example<FixedWindow>("backport");
    std::vector<Entry> input;
    int originalCases = 0, originalFailures = 0, fixedCases = 0, fixedFailures = 0;
    enumerate<OriginalWindow>(input, originalCases, originalFailures);
    enumerate<FixedWindow>(input, fixedCases, fixedFailures);
    std::cout << "0.56.2: " << originalFailures << "/" << originalCases << " failed checks\n"
              << "backport: " << fixedFailures << "/" << fixedCases << " failed checks\n";
    return !(originalExample && !fixedExample && originalFailures > 0 && fixedFailures == 0);
}
"""

program = (
    fixture
    + body.replace("CWindow::", "OriginalWindow::")
    + "\n"
    + body.replace(old, new).replace("CWindow::", "FixedWindow::")
    + tests
)
with tempfile.TemporaryDirectory(prefix="hypertile-ack-regression-") as directory:
    root = pathlib.Path(directory)
    cpp = root / "regression.cpp"
    binary = root / "regression"
    cpp.write_text(program)
    subprocess.run(["c++", "-std=c++23", "-O2", "-Wall", "-Wextra", str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
