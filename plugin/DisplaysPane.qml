import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Displays.js" as Displays
import "Wallpaper.js" as Wallpaper

Card {
    id: pane
    property var catalog: null
    property var draft: ({
            version: 1,
            displays: [],
            workspaces: {}
        })
    property int selectedIndex: 0
    property string matchingConnector: ""
    onSelectedIndexChanged: {
        matchingConnector = "";
        workspaceChoice = null;
        customWorkspace = "";
    }
    property var workspaceChoice: null
    property string customWorkspace: ""
    readonly property var workspaceOptions: Displays.workspaceOptions(catalog, draft)
    readonly property string selectedWorkspace: workspaceChoice === "" ? customWorkspace.trim() : workspaceChoice !== null ? workspaceChoice : liveDisplay && liveDisplay.active_workspace && liveDisplay.active_workspace.name ? Displays.workspaceSelector(liveDisplay.active_workspace) : "1"
    readonly property bool validSelectedWorkspace: Displays.validWorkspace(selectedWorkspace)
    readonly property bool canShowWorkspace: validSelectedWorkspace && !!liveDisplay && liveDisplay.enabled && !liveDisplay.mirror_of && liveDisplay.awake !== false && !busy && !pending
    readonly property var matchOptions: [
        {
            label: "Choose a connected display…",
            value: ""
        }
    ].concat(Displays.matchCandidates(draft, selectedIndex).map(function (display) {
        return {
            label: display.connector + " · " + (display.description || display.identity),
            value: display.connector
        };
    }))
    readonly property var textSizeStops: [9, 10, 11, 12, 14, 16, 20]
    property int pendingTextSize: -1
    readonly property real textSize: pendingTextSize >= 0 ? pendingTextSize : Style.font.baseSize
    readonly property QtObject sliderPalette: QtObject {
        readonly property color foreground: pane.fg
        readonly property color background: pane.overlay.surfaceColor
    }
    property alias wallpaperEditor: wallpaperEditor
    property bool wallpaperMode: false
    onWallpaperModeChanged: inspector.contentY = 0
    property bool workspacePreferencesExpanded: false
    property bool dirty: false
    property bool closeAfterRevert: false
    property bool confirmingDiscard: false
    property string identifyConnector: ""
    property string error: ""
    property string notice: ""
    property var pending: null
    property string focusedPreviewToken: ""
    onConfirmingDiscardChanged: if (confirmingDiscard)
        Qt.callLater(function () {
            keepEditingAction.forceActiveFocus();
        })
    onPendingChanged: {
        if (pending && pending.token !== focusedPreviewToken) {
            focusedPreviewToken = pending.token;
            Qt.callLater(function () {
                keepAction.forceActiveFocus();
            });
        } else if (!pending)
            focusedPreviewToken = "";
    }
    property double clock: Date.now() / 1000
    readonly property bool busy: commandProcess.running
    readonly property var selectedDisplay: draft.displays[selectedIndex] || null
    // Power state is read from the compositor, never from the unsaved draft.
    readonly property var liveDisplay: liveFor(selectedDisplay)
    readonly property bool selectedAsleep: isAsleep(selectedDisplay)
    // A disabled display may keep a dormant mirror target; only an enabled one mirrors.
    readonly property bool selectedMirrors: !!selectedDisplay && !!selectedDisplay.enabled && !!selectedDisplay.mirror_of
    readonly property int asleepCount: catalog ? (catalog.displays || []).filter(function (d) {
        return d.connected && d.enabled && d.awake === false;
    }).length : 0
    onVisibleChanged: {
        if (visible)
            Qt.callLater(function () {
                pane.forceActiveFocus();
            });
        else
            overlay.focusKeys();
    }
    readonly property int remaining: pending ? Math.max(0, Math.ceil(Number(pending.deadline || pending.expires_at || 0) - clock)) : 0
    readonly property color fg: overlay.foreground
    readonly property color muted: overlay.mutedForeground
    readonly property real gap: overlay.uiPad
    readonly property bool canArrange: Displays.canArrange(draft.displays)
    readonly property var arrangement: Displays.extent(draft.displays)
    // Diagram numbers come from position. A drag keeps the numbers it
    // started with so labels do not swap under the pointer mid-move.
    readonly property var liveNumbering: Displays.numbering(draft.displays)
    property var frozenNumbering: null
    readonly property var numbering: frozenNumbering || liveNumbering
    readonly property var displayOrder: Displays.order(numbering)
    function numberOf(index) { return numbering[index] || index + 1 }
    readonly property var layoutOptions: [
        {
            label: "Global fallback",
            value: null
        },
        {
            label: "Dwindle · Hyprland",
            value: "dwindle"
        },
        {
            label: "Scrolling · Hyprland",
            value: "scrolling"
        },
        {
            label: "Master · Hyprland",
            value: "master"
        }
    ].concat(overlay.layouts.map(function (l) {
        return {
            label: l.name,
            value: "lua:" + l.name
        };
    }))
    Keys.onPressed: function (event) {
        if (handleKey(event))
            event.accepted = true;
    }
    signal leave(bool scenes)
    signal closeRequested

    function serviceError(stdout, stderr, fallback) {
        try {
            var response = JSON.parse(stdout);
            if (response.error)
                return String(response.error);
        } catch (e) {}
        return String(stderr || "").trim() || fallback;
    }
    function liveFor(display) {
        if (!display || !display.connected || !catalog)
            return null;
        return (catalog.displays || []).find(function (d) {
            return d.connected && d.connector === display.connector;
        }) || null;
    }
    function isAsleep(display) {
        var live = liveFor(display);
        return !!live && !!live.enabled && live.awake === false;
    }
    function matchSelectedDisplay() {
        if (busy || pending || !selectedDisplay)
            return;
        var savedId = selectedDisplay.id;
        try {
            draft = Displays.matchSavedDisplay(draft, selectedIndex, matchingConnector);
            selectedIndex = draft.displays.findIndex(function (display) {
                return display.id === savedId;
            });
            matchingConnector = "";
            dirty = true;
            error = "";
            notice = "Connector matched. Preview to apply the retained display settings and workspace assignments.";
        } catch (e) {
            error = String(e.message || e);
        }
    }
    function revealInspectorControl(item) {
        var ancestor = item.parent;
        while (ancestor) {
            if (ancestor === settings) {
                reveal(item);
                return;
            }
            ancestor = ancestor.parent;
        }
    }
    function reveal(item) {
        var y = item.mapToItem(settings, 0, 0).y;
        if (y < inspector.contentY)
            inspector.contentY = Math.max(0, y);
        else if (y + item.height > inspector.contentY + inspector.height - 36)
            inspector.contentY = Math.min(Math.max(0, inspector.contentHeight - inspector.height), y + item.height - inspector.height + 36);
    }
    // Labels every screen with its diagram number (the selected one stands
    // out) so the numbers can be matched to the desk at a glance. A
    // connector limits it to one screen, for the CLI.
    function identify(connector) {
        identifyConnector = connector || "";
        identifyTimer.restart();
    }
    function refresh() {
        if (!queryProcess.running && !busy)
            queryProcess.running = true;
    }
    function setDisplay(key, value) {
        if (!selectedDisplay || pending || busy)
            return;
        confirmingDiscard = false;
        var previous = selectedDisplay[key];
        if (previous === value || (value === null && previous === undefined))
            return;
        var next = Displays.clone(draft);
        next.displays[selectedIndex][key] = value;
        draft = next;
        dirty = true;
    }
    function setTextSize(index) {
        if (textSizeProcess.running || index < 0 || index >= textSizeStops.length)
            return;
        pendingTextSize = textSizeStops[index];
        textSizeProcess.command = ["omarchy", "display", "text", "size", String(pendingTextSize)];
        textSizeProcess.running = true;
    }
    function setPosition(index, x, y) {
        var display = draft.displays[index];
        if (!Displays.canArrange(draft.displays) || !display || !display.connected || !display.enabled || display.mirror_of || busy || pending)
            return;
        x = Math.round(x);
        y = Math.round(y);
        if (display.x === x && display.y === y)
            return;
        var next = Displays.clone(draft);
        next.displays[index].x = x;
        next.displays[index].y = y;
        draft = next;
        dirty = true;
    }
    function run(args) {
        if (busy)
            return;
        error = "";
        notice = "";
        commandProcess.command = [overlay.ctl, "display"].concat(args);
        commandProcess.running = true;
    }
    function preview() {
        overlay.placeDisplayConfirmation(draft);
        var args = ["preview", "--json", JSON.stringify(draft)];
        run(args);
    }
    function revert() {
        confirmingDiscard = false;
        if (pending)
            run(["revert", pending.token]);
        else {
            dirty = false;
            refresh();
        }
    }
    function requestClose() {
        if (wallpaperEditor.busy) return;
        if (pending) {
            closeAfterRevert = true;
            revert();
            notice = "Reverting display changes before closing.";
        } else if (dirty || wallpaperEditor.dirty)
            confirmingDiscard = true;
        else
            closeRequested();
    }
    function discardAndClose() {
        wallpaperEditor.discard();
        confirmingDiscard = false;
        dirty = false;
        closeRequested();
    }
    function keepEditing() {
        confirmingDiscard = false;
    }
    function setAssignment(name, layout, preserveLayout) {
        name = name.trim();
        if (!name || !selectedDisplay)
            return;
        if (!/^\d+$/.test(name) && name.indexOf("name:") !== 0)
            name = "name:" + name;
        var next = Displays.clone(draft);
        if (!next.workspaces)
            next.workspaces = {};
        var old = next.workspaces[name];
        next.workspaces[name] = {
            monitor: selectedDisplay.id,
            layout: preserveLayout && old && old.layout !== undefined ? old.layout : layout
        };
        draft = next;
        dirty = true;
    }
    function selectedAssignments() {
        if (!selectedDisplay)
            return [];
        return Object.keys(draft.workspaces || {}).filter(function (k) {
            return draft.workspaces[k].monitor === selectedDisplay.id;
        });
    }
    function handleKey(event) {
        if (confirmingDiscard) {
            if (event.key === Qt.Key_Escape || event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                keepEditing();
                return true;
            }
            if (event.key === Qt.Key_D && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
                discardAndClose();
                return true;
            }
            return true;
        }
        if (event.key === Qt.Key_Escape) {
            requestClose();
            return true;
        }
        return false;
    }
    Component.onCompleted: refresh()
    Timer {
        id: identifyTimer
        interval: 4000
    }
    Variants {
        model: Quickshell.screens
        PanelWindow {
            required property var modelData
            screen: modelData
            visible: identifyTimer.running && (pane.identifyConnector === "" || pane.identifyConnector === modelData.name)
            anchors {
                top: true
            }
            margins.top: 90
            implicitWidth: 320
            implicitHeight: 140
            color: "transparent"
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.namespace: "hypertile-display-label"
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            readonly property int displayIndex: pane.draft.displays.findIndex(function (d) {
                return d.connector === modelData.name;
            })
            readonly property bool selectedScreen: !!pane.selectedDisplay && pane.selectedDisplay.connector === modelData.name
            Rectangle {
                anchors.fill: parent
                radius: pane.overlay.radiusCard
                color: selectedScreen ? Util.alpha(pane.overlay.accent, .35) : pane.overlay.surfaceColor
                border.color: pane.overlay.accent
                border.width: selectedScreen ? 4 : 2
                Column {
                    anchors.centerIn: parent
                    spacing: 6
                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: displayIndex >= 0 ? String(pane.numberOf(displayIndex)) : "?"
                        font.pixelSize: 42
                        font.bold: true
                    }
                    Label {
                        text: modelData.name + (selectedScreen ? " · selected" : "")
                        anchors.horizontalCenter: parent.horizontalCenter
                    }
                }
            }
        }
    }
    Timer {
        interval: 1000
        running: pane.visible
        repeat: true
        onTriggered: {
            pane.clock = Date.now() / 1000;
            if (pane.pending)
                pane.refresh();
        }
    }
    Process {
        id: queryProcess
        command: [pane.overlay.ctl, "display", "list", "--json"]
        stdout: StdioCollector {
            id: queryOutput
            waitForEnd: true
        }
        stderr: StdioCollector {
            id: queryError
            waitForEnd: true
        }
        onExited: function (code) {
            if (code !== 0) {
                pane.error = pane.serviceError(queryOutput.text, queryError.text, "Could not read displays. Try Refresh.");
                return;
            }
            try {
                var value = JSON.parse(queryOutput.text);
                pane.catalog = value;
                if (pane.pending && !value.pending) {
                    pane.dirty = false;
                    pane.notice = value.recovery && value.recovery.fallback ? "Preview ended. Recovered onto an available display because the previous arrangement is unavailable." : value.recovery && value.recovery.external && value.recovery.external.length ? "Preview ended. Newer external changes were preserved." : "Preview ended. Display settings refreshed.";
                    if (value.recovery && value.recovery.errors && value.recovery.errors.length)
                        pane.error = "Some settings could not be restored: " + value.recovery.errors.join("; ");
                }
                pane.pending = value.pending || null;
                if (pane.pending && !pane.dirty && pane.pending.document) {
                    var staged = Displays.clone(pane.pending.document);
                    staged.displays = staged.displays.map(function (d) {
                        var live = (value.displays || []).find(function (c) {
                            return c.id === d.id || c.connector === d.connector;
                        });
                        return Object.assign({}, live || {}, d);
                    });
                    pane.draft = staged;
                }
                if (pane.pending && !pane.overlay.displaysMode)
                    pane.overlay.showDisplays();
                if (pane.pending)
                    pane.overlay.placeDisplayConfirmation(pane.draft);
                if (!pane.dirty && !pane.pending) {
                    var preferences = value.confirmed || {};
                    pane.draft = {
                        version: 1,
                        displays: Displays.clone(value.displays || []),
                        workspaces: Displays.clone(preferences.workspaces || {})
                    };
                    pane.selectedIndex = Math.min(pane.selectedIndex, Math.max(0, pane.draft.displays.length - 1));
                }
            } catch (e) {
                pane.error = "The display service returned an unreadable response.";
            }
        }
    }
    Process {
        id: textSizeProcess
        stderr: StdioCollector { id: textSizeError; waitForEnd: true }
        onExited: function(code) {
            pane.pendingTextSize = -1;
            if (code !== 0)
                pane.error = textSizeError.text.trim() || "Could not change text size.";
        }
    }
    Process {
        id: commandProcess
        stdout: StdioCollector {
            id: commandOutput
            waitForEnd: true
        }
        stderr: StdioCollector {
            id: commandError
            waitForEnd: true
        }
        onExited: function (code) {
            if (code !== 0)
                pane.error = pane.serviceError(commandOutput.text, commandError.text, "The display change failed. Previous settings are being restored.");
            else {
                try {
                    var result = JSON.parse(commandOutput.text);
                    if (result.pending)
                        pane.pending = result.pending;
                    else if (result.token)
                        pane.pending = result;
                    pane.notice = result.message || "";
                } catch (e) {}
                if (command[2] === "sleep")
                    pane.notice = "Display asleep. Wake it from here, or press a key if no other display is awake.";
                else if (command[2] === "wake")
                    pane.notice = command.length > 3 ? "Display awake." : "All displays awake.";
                if (command[2] === "keep" || command[2] === "revert") {
                    pane.pending = null;
                    pane.dirty = false;
                    pane.notice = command[2] === "keep" ? "Display settings saved." : result && result.fallback ? "Recovered onto an available display because the previous arrangement is unavailable." : result && result.external && result.external.length ? "Restored previous settings where possible. Newer external changes were preserved." : "Previous display settings restored.";
                    if (result && result.errors && result.errors.length)
                        pane.error = "Some settings could not be restored: " + result.errors.join("; ");
                }
            }
            pane.refresh();
            if (pane.closeAfterRevert && code === 0 && command[2] === "revert") {
                pane.closeAfterRevert = false;
                pane.closeRequested();
            }
        }
    }

    component Label: Text {
        color: pane.fg
        font.family: pane.overlay.fontFamily
        font.pixelSize: pane.overlay.uiFontSmall
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
    }
    // primary marks the one call to action; selected marks the current tab or
    // display. A disabled button drops both so it never reads as a live choice.
    component Action: Controls.Button {
        id: action
        property bool primary: false
        property bool selected: false
        property bool bordered: true
        onActiveFocusChanged: if (activeFocus)
            pane.revealInspectorControl(this)
        font.family: pane.overlay.fontFamily
        font.pixelSize: pane.overlay.uiFontSmall
        padding: 10
        contentItem: Label {
            text: action.text
            color: action.enabled ? pane.fg : pane.muted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: pane.overlay.radiusControl
            color: !action.enabled ? Util.alpha(pane.fg, action.bordered ? .02 : 0) : Util.alpha(pane.overlay.accent, action.primary ? (action.hovered ? .3 : .23) : action.selected ? (action.hovered ? .19 : .14) : action.hovered ? .1 : action.bordered ? .05 : 0)
            border.width: action.activeFocus ? 2 : (action.bordered || action.selected ? 1 : 0)
            border.color: !action.enabled ? Util.alpha(pane.fg, .12) : action.activeFocus || action.primary || action.selected ? pane.overlay.accent : Util.alpha(pane.fg, .25)
        }
    }
    component Entry: Controls.TextField {
        property string accessibleLabel: placeholderText
        Accessible.name: accessibleLabel
        onActiveFocusChanged: if (activeFocus)
            pane.reveal(this)
        color: pane.fg
        placeholderTextColor: pane.muted
        selectByMouse: true
        font.family: pane.overlay.fontFamily
        font.pixelSize: pane.overlay.uiFontSmall
        padding: 10
        background: Rectangle {
            radius: pane.overlay.radiusControl
            color: Util.alpha(pane.fg, .04)
            border.width: parent.activeFocus ? 2 : 1
            border.color: parent.activeFocus ? pane.overlay.accent : Util.alpha(pane.fg, .25)
        }
    }
    component Choice: Controls.ComboBox {
        id: choice
        property string accessibleLabel: ""
        Accessible.name: accessibleLabel
        onActiveFocusChanged: if (activeFocus)
            pane.reveal(this)
        font.family: pane.overlay.fontFamily
        font.pixelSize: pane.overlay.uiFontSmall
        padding: 10
        contentItem: Label {
            text: choice.displayText
            rightPadding: 24
            elide: Text.ElideRight
            wrapMode: Text.NoWrap
        }
        background: Rectangle {
            radius: pane.overlay.radiusControl
            color: Util.alpha(pane.fg, .04)
            border.width: choice.activeFocus ? 2 : 1
            border.color: choice.activeFocus ? pane.overlay.accent : Util.alpha(pane.fg, .25)
        }
        indicator: Label {
            x: choice.width - width - 12
            anchors.verticalCenter: parent.verticalCenter
            text: "▾"
            color: pane.muted
        }
        delegate: Controls.ItemDelegate {
            required property int index
            width: choice.width
            padding: 10
            highlighted: choice.highlightedIndex === index
            contentItem: Label {
                text: choice.textAt(index)
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
            }
            background: Rectangle {
                color: parent.highlighted ? Util.alpha(pane.overlay.accent, .2) : "transparent"
            }
        }
        popup: Controls.Popup {
            y: choice.height + 4
            width: choice.width
            padding: 4
            implicitHeight: Math.min(pane.height * .55, choices.contentHeight + 8)
            contentItem: ListView {
                id: choices
                clip: true
                implicitHeight: contentHeight
                model: choice.popup.visible ? choice.delegateModel : null
                currentIndex: choice.highlightedIndex
                Controls.ScrollBar.vertical: Controls.ScrollBar {}
            }
            background: Rectangle {
                color: pane.overlay.surfaceColor
                radius: pane.overlay.radiusControl
                border.color: pane.overlay.accent
            }
        }
    }

    Column {
        anchors.fill: parent
        anchors.margins: pane.gap
        spacing: pane.gap
        Item {
            width: parent.width
            height: Math.max(navigation.implicitHeight, windowActions.implicitHeight)
            Row {
                id: navigation
                anchors.left: parent.left
                spacing: 2
                Action {
                    text: "Layouts"
                    bordered: false
                    enabled: !pane.pending && !pane.busy
                    onClicked: pane.leave(false)
                }
                Action {
                    text: "Scenes"
                    bordered: false
                    enabled: !pane.pending && !pane.busy
                    onClicked: pane.leave(true)
                }
                Action {
                    text: "Displays"
                    bordered: false
                    selected: true
                }
            }
            Row {
                id: windowActions
                anchors.right: parent.right
                spacing: 8
                Action {
                    text: identifyTimer.running ? "Identifying…" : "Identify displays"
                    Accessible.description: "Show each screen's diagram number on that screen for a few seconds"
                    enabled: !!pane.catalog && !identifyTimer.running
                    onClicked: pane.identify("")
                }
                Action {
                    text: "Wake all"
                    visible: pane.asleepCount > 0
                    enabled: !pane.busy && !pane.pending
                    onClicked: pane.run(["wake"])
                }
                Action {
                    text: "Close"
                    enabled: !pane.busy
                    onClicked: pane.requestClose()
                }
            }
        }
        Row {
            id: body
            width: parent.width
            height: parent.height - y - footer.height - pane.gap
            spacing: pane.gap
            Column {
                width: Math.max(240, parent.width * .57)
                height: parent.height
                spacing: 12
                Label {
                    text: "Arrange your displays"
                    font.pixelSize: pane.overlay.uiFont * 1.4
                    font.bold: true
                }
                Label {
                    width: parent.width
                    text: pane.wallpaperMode ? "Select a screen to configure its wallpaper group." : pane.canArrange ? "Drag screens to align their edges. Select a screen to adjust its settings." : "Select a screen to adjust its settings."
                    color: pane.muted
                }
                Rectangle {
                    id: diagram
                    width: parent.width
                    height: Math.max(150, parent.height - 340)
                    color: Util.alpha(pane.fg, .025)
                    radius: pane.overlay.radiusControl
                    border.color: Util.alpha(pane.fg, .15)
                    clip: true
                    property var frozenExtent: null
                    readonly property var extent: frozenExtent || pane.arrangement
                    readonly property real factor: Math.min((width - 70) / extent.w, (height - 70) / extent.h)
                    Repeater {
                        model: pane.draft.displays.length
                        Rectangle {
                            id: screen
                            readonly property var modelData: pane.draft.displays[index]
                            required property int index
                            readonly property var logical: Displays.bounds(modelData)
                            readonly property bool selectedGroup: index === pane.selectedIndex || (pane.selectedMirrors && pane.selectedDisplay.mirror_of === modelData.id)
                            readonly property bool asleep: pane.isAsleep(modelData)
                            readonly property var wallpaperGroup: Wallpaper.groupFor(wallpaperEditor.draft, modelData.connector)
                            readonly property bool wallpaperMember: pane.wallpaperMode && pane.selectedDisplay && Wallpaper.groupFor(wallpaperEditor.draft, pane.selectedDisplay.connector).outputs.indexOf(modelData.connector) >= 0
                            visible: modelData.connected && modelData.enabled && !modelData.mirror_of
                            opacity: asleep ? .55 : 1
                            x: (logical.x - diagram.extent.x) * diagram.factor + (diagram.width - diagram.extent.w * diagram.factor) / 2
                            y: (logical.y - diagram.extent.y) * diagram.factor + (diagram.height - diagram.extent.h * diagram.factor) / 2
                            width: Math.max(16, logical.w * diagram.factor)
                            height: Math.max(16, logical.h * diagram.factor)
                            radius: 8
                            color: Util.alpha(pane.overlay.accent, selectedGroup || wallpaperMember ? .25 : .07)
                            border.color: selectedGroup || wallpaperMember ? pane.overlay.accent : Util.alpha(pane.fg, .45)
                            border.width: activeFocus ? 3 : 2
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: "Display " + pane.numberOf(index) + ", " + modelData.connector
                            Accessible.onPressAction: {
                                pane.selectedIndex = index;
                                screen.forceActiveFocus();
                            }
                            Keys.onPressed: function (event) {
                                var dx = event.key === Qt.Key_Left ? -1 : event.key === Qt.Key_Right ? 1 : 0;
                                var dy = event.key === Qt.Key_Up ? -1 : event.key === Qt.Key_Down ? 1 : 0;
                                if ((dx || dy) && !pane.wallpaperMode && !pane.pending && !pane.busy) {
                                    pane.selectedIndex = index;
                                    pane.setPosition(index, logical.x + dx * (event.modifiers & Qt.ShiftModifier ? 10 : 1), logical.y + dy * (event.modifiers & Qt.ShiftModifier ? 10 : 1));
                                    event.accepted = true;
                                }
                                if (event.key === Qt.Key_Return || event.key === Qt.Key_Space) {
                                    pane.selectedIndex = index;
                                    event.accepted = true;
                                }
                            }
                            Column {
                                anchors.centerIn: parent
                                width: parent.width - 12
                                spacing: 4
                                Label {
                                    width: parent.width
                                    text: Displays.groupLabel(pane.draft.displays, screen.index, pane.numbering)
                                    font.pixelSize: Math.min(pane.overlay.uiFont * 1.5, screen.height * .45)
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                Label {
                                    width: parent.width
                                    text: screen.modelData.connector + (screen.asleep ? " · asleep" : "")
                                    visible: screen.height > pane.overlay.uiFont * 3.8 && screen.width > pane.overlay.uiFont * 5
                                    font.pixelSize: pane.overlay.uiCaption
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                    wrapMode: Text.NoWrap
                                }
                            }
                            Label {
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 10
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                visible: pane.wallpaperMode && screen.height > 90
                                text: screen.wallpaperGroup.mode === "span" ? "Span · " + screen.wallpaperGroup.outputs.join(" + ") : "Independent"
                                font.pixelSize: pane.overlay.uiCaption
                                elide: Text.ElideRight
                                wrapMode: Text.NoWrap
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: !pane.wallpaperMode && pane.canArrange && !pane.pending && !pane.busy ? (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor) : Qt.ArrowCursor
                                property point origin
                                property point startPosition
                                onPressed: function (mouse) {
                                    screen.forceActiveFocus();
                                    pane.selectedIndex = screen.index;
                                    if (pane.wallpaperMode || !pane.canArrange || pane.pending || pane.busy)
                                        return;
                                    diagram.frozenExtent = Displays.clone(pane.arrangement);
                                    pane.frozenNumbering = pane.liveNumbering.slice();
                                    origin = mapToItem(diagram, mouse.x, mouse.y);
                                    startPosition = Qt.point(screen.logical.x, screen.logical.y);
                                }
                                onPositionChanged: function (mouse) {
                                    if (!pressed || !pane.canArrange || !diagram.frozenExtent || pane.pending || pane.busy)
                                        return;
                                    var p = mapToItem(diagram, mouse.x, mouse.y);
                                    var snapped = Displays.snap(pane.draft.displays, screen.index, startPosition.x + (p.x - origin.x) / diagram.factor, startPosition.y + (p.y - origin.y) / diagram.factor, 12 / diagram.factor);
                                    pane.setPosition(screen.index, snapped.x, snapped.y);
                                }
                                onReleased: { diagram.frozenExtent = null; pane.frozenNumbering = null }
                                onCanceled: { diagram.frozenExtent = null; pane.frozenNumbering = null }
                            }
                        }
                    }
                    Label {
                        anchors.centerIn: parent
                        visible: !pane.catalog
                        text: "Reading connected displays…"
                        color: pane.muted
                    }
                }
                Flow {
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: pane.displayOrder
                        Action {
                            required property int modelData
                            readonly property int index: modelData
                            readonly property var entry: pane.draft.displays[index]
                            text: pane.numberOf(index) + " · " + entry.connector + (!entry.connected ? " · disconnected" : !entry.enabled ? " · disabled" : entry.mirror_of ? " · mirrors " + pane.numberOf(pane.draft.displays.findIndex(function (d) {
                                            return d.id === entry.mirror_of;
                                        })) : pane.isAsleep(entry) ? " · asleep" : "")
                            selected: index === pane.selectedIndex
                            onClicked: pane.selectedIndex = index
                        }
                    }
                }
                Label {
                    width: parent.width
                    color: pane.muted
                    text: (pane.canArrange ? "Numbered left to right, then top to bottom. Keyboard: Tab to a display, arrows move 1 px, Shift + arrows move 10 px." : "Keyboard: Tab to a display.") + " Positions use logical pixels."
                    font.pixelSize: pane.overlay.uiCaption
                }
                Action {
                    text: pane.wallpaperMode ? "Back to display settings" : "Wallpaper groups…"
                    selected: pane.wallpaperMode
                    enabled: !pane.busy && !pane.pending && !wallpaperEditor.busy
                    onClicked: pane.wallpaperMode = !pane.wallpaperMode
                }
                // Desktop text size is one setting for the whole desktop, not a
                // property of the selected display, and it applies at once rather
                // than through Preview and Keep; it lives apart from both.
                Rectangle {
                    width: parent.width
                    height: 1
                    color: Util.alpha(pane.fg, .2)
                }
                Column {
                    width: parent.width
                    spacing: 6
                    Row {
                        width: parent.width
                        Label { width: parent.width / 2; text: "Desktop text size"; font.bold: true }
                        Label {
                            width: parent.width / 2
                            horizontalAlignment: Text.AlignRight
                            text: (textSizeSlider.dragging ? pane.textSizeStops[Math.round(textSizeSlider.liveValue)] : pane.textSize) + "px"
                        }
                    }
                    PanelSlider {
                        id: textSizeSlider
                        width: parent.width
                        bar: pane.sliderPalette
                        minimum: 0
                        maximum: pane.textSizeStops.length - 1
                        step: 1
                        integer: true
                        tickCount: pane.textSizeStops.length
                        value: Displays.nearestStop(pane.textSizeStops, pane.textSize)
                        enabled: !textSizeProcess.running && !pane.busy
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Slider
                        Accessible.name: "Desktop text size"
                        onReleased: function(v) { pane.setTextSize(Math.round(v)); }
                        Keys.onPressed: function(event) {
                            var delta = event.key === Qt.Key_Left ? -1 : event.key === Qt.Key_Right ? 1 : 0;
                            if (delta) {
                                pane.setTextSize(Math.max(0, Math.min(maximum, value + delta)));
                                event.accepted = true;
                            }
                        }
                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -2
                            visible: textSizeSlider.activeFocus
                            color: "transparent"
                            border.color: pane.overlay.accent
                            radius: pane.overlay.radiusControl
                        }
                    }
                    Label {
                        width: parent.width
                        text: "Text on every display, changed at once. It is not part of Preview and Keep."
                        color: pane.muted
                        font.pixelSize: pane.overlay.uiCaption
                    }
                }
            }
            Flickable {
                id: inspector
                width: parent.width - parent.children[0].width - parent.spacing
                height: parent.height
                contentHeight: (pane.wallpaperMode ? wallpaperEditor.implicitHeight : settings.implicitHeight) + 36
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar {
                    policy: Controls.ScrollBar.AlwaysOn
                    width: 7
                    visible: inspector.contentHeight > inspector.height
                    contentItem: Rectangle {
                        implicitWidth: 7
                        radius: 3
                        color: Util.alpha(pane.overlay.accent, .7)
                    }
                    background: Rectangle {
                        radius: 3
                        color: Util.alpha(pane.fg, .08)
                    }
                }
                Rectangle {
                    parent: inspector.contentItem
                    z: 5
                    x: 0
                    y: inspector.contentY + inspector.height - height
                    width: inspector.width - 12
                    height: 32
                    visible: inspector.contentY + inspector.height < inspector.contentHeight - 8
                    color: pane.overlay.surfaceColor
                    Label {
                        anchors.centerIn: parent
                        text: "Scroll for more settings ↓"
                        color: pane.muted
                        font.pixelSize: pane.overlay.uiCaption
                    }
                }
                WallpaperSettings {
                    id: wallpaperEditor
                    width: inspector.width - 12
                    visible: pane.wallpaperMode
                    overlay: pane.overlay
                    displays: pane.draft.displays
                    selectedDisplay: pane.selectedDisplay
                    blocked: pane.busy || !!pane.pending || pane.dirty
                }
                Column {
                    id: settings
                    visible: !pane.wallpaperMode
                    width: inspector.width - 12
                    spacing: 12
                    enabled: !pane.busy && !pane.pending
                    Label {
                        width: parent.width
                        text: pane.selectedDisplay ? pane.selectedDisplay.connector : "No display selected"
                        font.bold: true
                        font.pixelSize: pane.overlay.uiFont * 1.25
                    }
                    Label {
                        width: parent.width
                        text: pane.selectedDisplay ? pane.selectedDisplay.description || "" : ""
                        color: pane.muted
                        font.pixelSize: pane.overlay.uiCaption
                    }
                    Label {
                        width: parent.width
                        visible: !!pane.selectedDisplay && !pane.selectedDisplay.connected
                        text: "Disconnected · saved settings and workspace assignments are retained."
                        color: pane.muted
                    }
                    Label {
                        width: parent.width
                        visible: pane.selectedAsleep
                        text: "Asleep · the display is off until you wake it."
                        color: pane.overlay.accent
                    }
                    Column {
                        width: parent.width
                        spacing: 8
                        visible: !!pane.selectedDisplay && !pane.selectedDisplay.connected
                        Label {
                            width: parent.width
                            text: pane.matchOptions.length > 1 ? "Match these saved settings to a connected display with the same identity." : "No connected display has this saved identity. Reconnect the display to match its settings."
                            color: pane.muted
                        }
                        Choice {
                            width: parent.width
                            visible: pane.matchOptions.length > 1
                            accessibleLabel: "Connected display to match"
                            model: pane.matchOptions
                            textRole: "label"
                            currentIndex: Math.max(0, pane.matchOptions.findIndex(function (option) {
                                return option.value === pane.matchingConnector;
                            }))
                            onActivated: function (index) {
                                pane.matchingConnector = pane.matchOptions[index].value;
                            }
                        }
                        Action {
                            visible: pane.matchOptions.length > 1
                            text: "Match saved display"
                            enabled: pane.matchingConnector !== ""
                            onClicked: pane.matchSelectedDisplay()
                        }
                    }
                    Label {
                        width: parent.width
                        visible: !!pane.selectedDisplay && pane.selectedDisplay.connected && !!pane.selectedDisplay.ambiguous
                        text: "Settings are saved for this connection: " + (pane.selectedDisplay ? pane.selectedDisplay.connector : "")
                        color: pane.muted
                    }

                    Label {
                        text: "Use as"
                        font.bold: true
                    }
                    Choice {
                        width: parent.width
                        accessibleLabel: "Use display as"
                        enabled: !!pane.selectedDisplay && pane.selectedDisplay.connected
                        model: pane.selectedDisplay ? Displays.usageOptions(pane.draft.displays, pane.selectedDisplay) : []
                        textRole: "label"
                        currentIndex: Math.max(0, model.findIndex(function (o) {
                            return o.value === (!pane.selectedDisplay.enabled ? "disabled" : pane.selectedDisplay.mirror_of || "extended");
                        }))
                        onActivated: function (index) {
                            pane.draft = Displays.setUsage(pane.draft, pane.selectedIndex, model[index].value);
                            pane.dirty = true;
                        }
                    }
                    Column {
                        width: parent.width
                        spacing: 8
                        visible: !!pane.selectedDisplay && pane.selectedDisplay.enabled && !pane.selectedMirrors
                        Label {
                            text: "Workspace"
                            font.bold: true
                        }
                        Row {
                            width: parent.width
                            spacing: 8
                            Choice {
                                width: parent.width - showWorkspaceAction.width - 8
                                accessibleLabel: "Workspace to show on this display"
                                model: pane.workspaceOptions
                                textRole: "label"
                                currentIndex: Math.max(0, model.findIndex(function (o) {
                                    return o.value === (pane.workspaceChoice === "" ? "" : pane.selectedWorkspace);
                                }))
                                onActivated: function (index) { pane.workspaceChoice = model[index].value; }
                            }
                            Action {
                                id: showWorkspaceAction
                                text: "Apply"
                                Accessible.name: "Apply selected workspace to this display"
                                enabled: pane.canShowWorkspace
                                onClicked: pane.run(["show-workspace", pane.selectedDisplay.connector, pane.selectedWorkspace])
                            }
                        }
                        Entry {
                            width: parent.width
                            visible: pane.workspaceChoice === ""
                            placeholderText: "Number or name:research"
                            text: pane.customWorkspace
                            onTextEdited: pane.customWorkspace = text
                            onAccepted: if (pane.canShowWorkspace)
                                pane.run(["show-workspace", pane.selectedDisplay.connector, pane.selectedWorkspace])
                        }
                        Controls.CheckBox {
                            width: parent.width
                            text: "Use this workspace at startup"
                            font.family: pane.overlay.fontFamily
                            font.pixelSize: pane.overlay.uiFontSmall
                            enabled: pane.validSelectedWorkspace
                            checked: !!pane.selectedDisplay && pane.selectedDisplay.initial_workspace === pane.selectedWorkspace
                            onClicked: pane.setDisplay("initial_workspace", checked ? pane.selectedWorkspace : null)
                            onActiveFocusChanged: if (activeFocus) pane.reveal(this)
                            contentItem: Label {
                                text: parent.text
                                leftPadding: parent.indicator.width + parent.spacing
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                        Label {
                            width: parent.width
                            text: "Apply switches immediately and brings the workspace here if it is on another display. Startup changes are saved with Preview changes → Keep changes."
                            color: pane.muted
                            font.pixelSize: pane.overlay.uiCaption
                        }
                        Label {
                            width: parent.width
                            visible: !!pane.selectedDisplay && !!pane.selectedDisplay.initial_workspace && pane.selectedDisplay.initial_workspace !== pane.selectedWorkspace
                            text: "Startup workspace: " + (pane.selectedDisplay ? String(pane.selectedDisplay.initial_workspace || "").replace(/^name:/, "") : "")
                            color: pane.muted
                        }
                    }
                    Label {
                        width: parent.width
                        visible: pane.selectedMirrors
                        text: "Workspaces and layout follow display " + (pane.selectedDisplay ? pane.numberOf(pane.draft.displays.findIndex(function (d) {
                                return d.id === pane.selectedDisplay.mirror_of;
                            })) : "") + ". Independent preferences are retained for Extended display. Different aspect ratios may stretch the image."
                        color: pane.muted
                    }
                    Row {
                        spacing: 8
                        Action {
                            // One button follows the compositor's power state, so
                            // it never offers to wake a display that is already on.
                            text: pane.selectedAsleep ? "Wake display" : "Sleep display"
                            enabled: !!pane.liveDisplay && !!pane.liveDisplay.enabled
                            onClicked: pane.run([pane.selectedAsleep ? "wake" : "sleep", pane.selectedDisplay.connector])
                        }
                    }
                    Label {
                        width: parent.width
                        text: pane.selectedAsleep ? "This display is asleep. Wake it here, or press a key if no other display is awake." : !!pane.liveDisplay && !!pane.liveDisplay.enabled ? "Sleep is temporary and keeps workspaces in place. Wake it from here; if it is the last awake display, a key press wakes it." : "Sleep needs a connected, enabled display."
                        color: pane.muted
                        font.pixelSize: pane.overlay.uiCaption
                    }
                    Label {
                        text: "Resolution and refresh rate"
                        font.bold: true
                    }
                    Choice {
                        width: parent.width
                        accessibleLabel: "Resolution and refresh rate"
                        model: pane.selectedDisplay ? (pane.selectedDisplay.modes || []).map(Displays.modeLabel) : []
                        displayText: pane.selectedDisplay ? pane.selectedDisplay.width + "×" + pane.selectedDisplay.height + " @ " + Number(pane.selectedDisplay.refresh).toFixed(2) + " Hz" : ""
                        onActivated: function (index) {
                            var mode = Displays.parseMode(pane.selectedDisplay.modes[index]);
                            if (mode) {
                                pane.setDisplay("width", mode.width);
                                pane.setDisplay("height", mode.height);
                                pane.setDisplay("refresh", mode.refresh);
                            }
                        }
                    }
                    Label {
                        width: parent.width
                        visible: !!pane.selectedDisplay && pane.selectedDisplay.mode_available === false
                        text: "Saved mode is unavailable. Choose a supported mode to enable this display."
                        color: pane.overlay.accent
                    }
                    Column {
                        width: parent.width
                        spacing: 6
                        Label { text: "Scale"; font.bold: true }
                        Row {
                            id: scaleButtons
                            width: parent.width
                            spacing: 4
                            readonly property var options: Displays.scaleOptions(pane.selectedDisplay)
                            Repeater {
                                model: scaleButtons.options
                                Action {
                                    required property var modelData
                                    width: (scaleButtons.width - scaleButtons.spacing * (scaleButtons.options.length - 1)) / scaleButtons.options.length
                                    padding: 4
                                    text: modelData.label
                                    selected: !!pane.selectedDisplay && Math.abs(pane.selectedDisplay.scale - modelData.value) < 0.001
                                    Accessible.name: "Display scale " + modelData.label
                                    onClicked: pane.setDisplay("scale", modelData.value)
                                }
                            }
                        }
                    }
                    Column {
                        width: parent.width
                        spacing: 6
                        Label { text: "Rotation"; font.bold: true }
                        Choice {
                            width: parent.width
                            accessibleLabel: "Display rotation"
                            model: ["Normal", "90°", "180°", "270°", "Flipped", "Flipped 90°", "Flipped 180°", "Flipped 270°"]
                            currentIndex: pane.selectedDisplay ? pane.selectedDisplay.transform || 0 : 0
                            onActivated: function(index) { pane.setDisplay("transform", index); }
                        }
                    }
                    Row {
                        width: parent.width
                        spacing: 12
                        enabled: !!pane.selectedDisplay && !pane.selectedMirrors
                        Repeater {
                            model: ["x", "y"]
                            Column {
                                required property string modelData
                                width: (parent.width - 12) / 2
                                spacing: 6
                                Label {
                                    text: modelData.toUpperCase() + " position"
                                    font.bold: true
                                }
                                Entry {
                                    width: parent.width
                                    accessibleLabel: modelData.toUpperCase() + " position"
                                    text: pane.selectedDisplay ? String(pane.selectedDisplay[modelData] || 0) : "0"
                                    validator: IntValidator {
                                        bottom: -100000
                                        top: 100000
                                    }
                                    onEditingFinished: if (acceptableInput)
                                        pane.setDisplay(modelData, Number(text))
                                }
                            }
                        }
                    }
                    Rectangle {
                        width: parent.width
                        height: 1
                        color: Util.alpha(pane.fg, .2)
                    }
                    Action {
                        width: parent.width
                        text: (pane.workspacePreferencesExpanded ? "▾ " : "▸ ") + "Workspace preferences"
                        Accessible.name: "Workspace preferences"
                        Accessible.description: pane.workspacePreferencesExpanded ? "Expanded" : "Collapsed"
                        onClicked: pane.workspacePreferencesExpanded = !pane.workspacePreferencesExpanded
                    }
                    Column {
                        width: parent.width
                        spacing: 8
                        visible: pane.workspacePreferencesExpanded
                        enabled: !!pane.selectedDisplay && !pane.selectedMirrors
                        Label {
                            text: "Default layout for this monitor"
                            font.bold: true
                        }
                        Choice {
                            width: parent.width
                            accessibleLabel: "Default layout for this monitor"
                            model: pane.layoutOptions
                            textRole: "label"
                            currentIndex: Math.max(0, pane.layoutOptions.findIndex(function (l) {
                                return l.value === (pane.selectedDisplay ? pane.selectedDisplay.default_layout || null : null);
                            }))
                            onActivated: function (index) {
                                pane.setDisplay("default_layout", pane.layoutOptions[index].value);
                            }
                        }
                        Label {
                            width: parent.width
                            text: "Applies to inheriting workspaces, including future ones. Explicit workspace layouts stay unchanged."
                            color: pane.muted
                            font.pixelSize: pane.overlay.uiCaption
                        }
                        Label {
                            text: "Workspaces on this monitor"
                            font.bold: true
                        }
                        Repeater {
                            model: pane.selectedAssignments()
                            Column {
                                required property string modelData
                                width: settings.width
                                spacing: 6
                                Label {
                                    width: parent.width
                                    text: "Workspace " + modelData.replace(/^name:/, "")
                                }
                                Row {
                                    width: parent.width
                                    spacing: 8
                                    Choice {
                                        width: parent.width - removeAssignment.width - parent.spacing
                                        accessibleLabel: "Layout for workspace " + modelData.replace(/^name:/, "")
                                        model: [
                                            {
                                                label: "Monitor default",
                                                value: null
                                            }
                                        ].concat(pane.layoutOptions.slice(1))
                                        textRole: "label"
                                        currentIndex: Math.max(0, model.findIndex(function (l) {
                                            return l.value === (pane.draft.workspaces[modelData].layout || null);
                                        }))
                                        onActivated: function (index) {
                                            pane.setAssignment(modelData, model[index].value);
                                        }
                                    }
                                    Action {
                                        id: removeAssignment
                                        text: "Remove"
                                        Accessible.name: "Remove monitor assignment for workspace " + modelData.replace(/^name:/, "")
                                        onClicked: {
                                            var next = Displays.clone(pane.draft);
                                            delete next.workspaces[modelData].monitor;
                                            pane.draft = next;
                                            pane.dirty = true;
                                        }
                                    }
                                }
                            }
                        }
                        Row {
                            width: parent.width
                            spacing: 8
                            Entry {
                                id: workspaceField
                                width: parent.width - addAssignment.width - parent.spacing
                                placeholderText: "Number or workspace name"
                                onAccepted: {
                                    pane.setAssignment(text, null, true);
                                    text = "";
                                }
                            }
                            Action {
                                id: addAssignment
                                text: "Add"
                                Accessible.name: "Assign workspace to this monitor"
                                enabled: workspaceField.text.trim() !== ""
                                onClicked: {
                                    pane.setAssignment(workspaceField.text, null, true);
                                    workspaceField.text = "";
                                }
                            }
                        }
                    }
                    Label {
                        width: parent.width
                        visible: pane.workspacePreferencesExpanded
                        text: "Applying moves existing workspaces and remembers placement for future workspaces. Active scenes keep their required layout; replace the scene from Layouts to change it."
                        color: pane.muted
                        font.pixelSize: pane.overlay.uiCaption
                    }
                    Label {
                        width: parent.width
                        text: "Keep changes saves your display configuration. Existing automatic settings are preserved unless you change them."
                        color: pane.muted
                        font.pixelSize: pane.overlay.uiCaption
                    }
                }
            }
        }
        Rectangle {
            id: footer
            width: parent.width
            height: Math.max(64, footerText.implicitHeight + 24)
            radius: pane.overlay.radiusControl
            color: pane.confirmingDiscard ? Util.alpha(Color.urgent, .1) : Util.alpha(pane.pending ? pane.overlay.accent : pane.fg, .06)
            Row {
                id: footerActions
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                Action {
                    id: discardAction
                    visible: pane.confirmingDiscard
                    text: "Discard"
                    Accessible.description: "Close and drop the unsaved display changes (D)"
                    onClicked: pane.discardAndClose()
                    contentItem: Label {
                        text: discardAction.text
                        color: Color.urgent
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Action {
                    id: keepEditingAction
                    visible: pane.confirmingDiscard
                    text: "Keep editing"
                    primary: true
                    Accessible.description: "Return to the unsaved changes (Esc)"
                    onClicked: pane.keepEditing()
                }
                Action {
                    visible: !pane.pending && !pane.confirmingDiscard
                    text: "Refresh"
                    Accessible.description: "Re-read the connected displays"
                    enabled: !pane.busy
                    onClicked: pane.refresh()
                }
                Action {
                    visible: !pane.confirmingDiscard
                    text: pane.pending ? "Revert" : "Reset"
                    enabled: !pane.busy && (pane.dirty || !!pane.pending)
                    onClicked: pane.revert()
                }
                Action {
                    id: keepAction
                    visible: !pane.confirmingDiscard
                    text: pane.pending ? "Keep changes" : "Preview changes"
                    primary: true
                    enabled: !pane.busy && !wallpaperEditor.dirty && !wallpaperEditor.busy && (pane.dirty || !!pane.pending)
                    onClicked: pane.pending ? pane.run(["keep", pane.pending.token]) : pane.preview()
                }
            }
            Label {
                id: footerText
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.right: footerActions.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                color: pane.error !== "" ? Color.urgent : pane.fg
                text: pane.confirmingDiscard ? "Close and discard the unsaved display changes? Nothing has been applied." : pane.error || (pane.busy ? "Applying…" : pane.pending ? "Keep these display settings? Reverting in " + pane.remaining + " seconds." : pane.notice || (pane.dirty ? "Changes are ready to preview. You will have 15 seconds to keep them." : "Display settings are saved with Keep changes. Apply switches workspaces immediately."))
            }
        }
    }
}
