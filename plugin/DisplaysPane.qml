import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Displays.js" as Displays
import "Wallpaper.js" as Wallpaper
import "Readability.js" as Readability

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
    property alias wallpaperEditor: wallpaperEditor
    property bool wallpaperMode: false
    onWallpaperModeChanged: inspector.contentY = 0
    // The pane opens from the rail's corner; docked right, the tabs keep
    // the rail's place and the window actions move to the other end.
    property bool dockLeft: true
    property bool workspacePreferencesExpanded: false
    property bool positionExpanded: false
    // The "scroll for more" strip at the foot of the inspector.
    readonly property int scrollHint: Math.round(overlay.uiCaption * 2.4)
    property bool dirty: false
    // A control holding input the draft has not received yet: a half-typed
    // field or an open list. The periodic refresh waits for it.
    property var engaged: null
    // The last catalog as text. An identical answer leaves the catalog and
    // the draft alone, so lists keep their place between refreshes.
    property string catalogText: ""
    property bool closeAfterRevert: false
    property bool confirmingDiscard: false
    property string identifyConnector: ""
    property string error: ""
    property string notice: ""
    property string previousSource: ""
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
    readonly property var selectedMirrorSource: catalog ? Displays.mirrorSource(catalog.displays, liveDisplay) : null
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
            label: "The default layout" + (overlay.defaultLayout ? " · " + String(overlay.defaultLayout).replace(/^lua:/, "") : ""),
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
        else if (y + item.height > inspector.contentY + inspector.height - scrollHint)
            inspector.contentY = Math.min(Math.max(0, inspector.contentHeight - inspector.height), y + item.height - inspector.height + scrollHint);
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
        var fields = {};
        fields[key] = value;
        var next = Displays.updateDisplay(draft, selectedIndex, fields);
        if (!next) return;
        confirmingDiscard = false;
        draft = next;
        dirty = true;
    }
    function setMode(mode) {
        if (!selectedDisplay || pending || busy || !mode) return;
        var next = Displays.updateDisplay(draft, selectedIndex, mode);
        if (!next) return;
        confirmingDiscard = false;
        draft = next;
        dirty = true;
    }
    function removeSelectedDisplay() {
        if (!selectedDisplay || busy || pending || queryProcess.running)
            return;
        var reason = Displays.removalError(draft, selectedDisplay);
        if (reason) { error = reason; return; }
        confirmingDiscard = false;
        run(["remove-display", selectedDisplay.id]);
    }
    function removedDisplay(identity) {
        var selectedId = selectedDisplay ? selectedDisplay.id : null;
        draft = Displays.forgetDisplay(draft, identity);
        var kept = draft.displays.findIndex(function(d) { return d.id === selectedId; });
        selectedIndex = kept >= 0 ? kept : Math.min(selectedIndex, Math.max(0, draft.displays.length - 1));
        matchingConnector = "";
        workspaceChoice = null;
        customWorkspace = "";
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
    function useDisplay(connector) {
        if (busy || pending || dirty || wallpaperEditor.dirty || queryProcess.running || !catalog)
            return;
        var display = catalog.displays.find(function(d) { return d.connector === connector; });
        if (!Displays.canUseDisplay(catalog.displays, display))
            return;
        confirmingDiscard = false;
        run(["use-display", connector]);
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
        name = Displays.workspaceKey(name);
        if (!name || !selectedDisplay || !Displays.validWorkspace(name))
            return;
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
            // A preview reverts in place; Escape again closes the pane.
            if (pending)
                revert();
            else
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
        interval: pane.pending ? 1000 : 2000
        running: pane.visible
        repeat: true
        onTriggered: {
            pane.clock = Date.now() / 1000;
            if (pane.pending || !(pane.dirty || pane.engaged))
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
                // Input may have started after this query was launched. The
                // next poll can refresh it after editing; previews still need
                // their safety controls and countdown immediately.
                if (pane.engaged && !pane.pending && !value.pending)
                    return;
                if (queryOutput.text !== pane.catalogText) {
                    pane.catalogText = queryOutput.text;
                    pane.catalog = value;
                }
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
                    var selectedId = pane.selectedDisplay ? pane.selectedDisplay.id : null;
                    var fresh = {
                        version: 1,
                        displays: Displays.clone(value.displays || []),
                        workspaces: Displays.clone(preferences.workspaces || {})
                    };
                    if (JSON.stringify(fresh) !== JSON.stringify(pane.draft)) {
                        pane.draft = fresh;
                        // Connected displays list first, so a reconnect can reorder
                        // the catalog; the selection follows the display, not its slot.
                        var kept = pane.draft.displays.findIndex(function (d) {
                            return d.id === selectedId;
                        });
                        pane.selectedIndex = kept >= 0 ? kept : Math.min(pane.selectedIndex, Math.max(0, pane.draft.displays.length - 1));
                    }
                }
                // An output that fell asleep, from here or elsewhere, must not keep the overlay.
                pane.overlay.placeDisplayConfirmation();
            } catch (e) {
                pane.error = "The display service returned an unreadable response.";
            }
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
            if (code !== 0) {
                pane.error = pane.serviceError(commandOutput.text, commandError.text, "The display change failed. Previous settings are being restored.");
                if (command[2] === "preview" && pane.dirty)
                    pane.error = "Preview failed. The controls still show your unsaved edits. Choose Discard to show current settings.\n" + pane.error;
            } else {
                try {
                    var result = JSON.parse(commandOutput.text);
                    if (result.pending)
                        pane.pending = result.pending;
                    else if (result.token)
                        pane.pending = result;
                    pane.notice = result.message || "";
                    if (result.previous_source)
                        pane.previousSource = result.previous_source;
                    if (result.removed)
                        pane.removedDisplay(result.removed);
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
            // Process.running settles after the exit signal; refresh on the
            // next turn so immediate actions do not leave a stale catalog.
            Qt.callLater(function () { pane.refresh(); });
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
    // One line of explanation under a control.
    component Note: Label {
        width: parent ? parent.width : implicitWidth
        color: pane.muted
        font.pixelSize: pane.overlay.uiCaption
    }
    // A small bold caption over a control.
    component Caption: Label {
        font.bold: true
    }
    // The overlay's button (KitButton): `primary` marks the one call to
    // action; `selected` marks the current tab or display. Focusable, so
    // Tab reaches it and Enter or Space presses it.
    component Action: KitButton {
        overlay: pane.overlay
        foreground: pane.fg
        focusable: true
        onActiveFocusChanged: if (activeFocus)
            pane.revealInspectorControl(this)
    }
    // A labelled switch row from the same kit.
    component Switch: Toggle {
        width: parent ? parent.width : implicitWidth
        radius: pane.overlay.radiusControl
        rounded: true
        foreground: pane.fg
        accent: pane.overlay.accent
        fontFamily: pane.overlay.fontFamily
        titleSize: pane.overlay.uiFontSmall
        descriptionSize: pane.overlay.uiCaption
        opacity: enabled ? 1 : 0.45
        Accessible.role: Accessible.CheckBox
        Accessible.name: label
        Accessible.checked: checked
        onActiveFocusChanged: if (activeFocus)
            pane.reveal(this)
    }
    // A collapsible group heading: ▸ Position.
    component Disclosure: Action {
        property bool expanded: false
        width: parent ? parent.width : implicitWidth
        leftAlign: true
        bordered: false
        text: (expanded ? "▾  " : "▸  ") + Accessible.name
        Accessible.description: expanded ? "Expanded" : "Collapsed"
    }
    component Entry: Controls.TextField {
        property string accessibleLabel: placeholderText
        Accessible.name: accessibleLabel
        onActiveFocusChanged: {
            if (activeFocus)
                pane.reveal(this);
            else if (pane.engaged === this)
                pane.engaged = null;
        }
        onTextEdited: pane.engaged = this
        onEditingFinished: if (pane.engaged === this)
            pane.engaged = null
        color: pane.fg
        placeholderTextColor: pane.muted
        selectByMouse: true
        font.family: pane.overlay.fontFamily
        font.pixelSize: pane.overlay.uiFontSmall
        padding: Style.spacing.controlPaddingX
        background: Rectangle {
            radius: pane.overlay.radiusControl
            color: Util.alpha(pane.fg, .04)
            border.width: parent.activeFocus ? 2 : 1
            border.color: parent.activeFocus ? pane.overlay.accent : Util.alpha(pane.fg, .25)
        }
    }
    // The kit's Dropdown draws at the bar's text size; the overlay scales its
    // type with the screen, so its choices stay a ComboBox styled to match.
    component Choice: Controls.ComboBox {
        id: choice
        property string accessibleLabel: ""
        Accessible.name: accessibleLabel
        onActiveFocusChanged: if (activeFocus)
            pane.reveal(this)
        font.family: pane.overlay.fontFamily
        font.pixelSize: pane.overlay.uiFontSmall
        padding: Style.spacing.controlPaddingX
        contentItem: Label {
            text: choice.displayText
            rightPadding: pane.overlay.uiFont
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
            x: choice.width - width - Style.spacing.xl
            anchors.verticalCenter: parent.verticalCenter
            text: "▾"
            color: pane.muted
        }
        delegate: Controls.ItemDelegate {
            required property int index
            width: choice.width
            padding: Style.spacing.controlPaddingX
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
            y: choice.height + Style.spacing.xs
            width: choice.width
            padding: Style.spacing.xs
            implicitHeight: Math.min(pane.height * .55, choices.contentHeight + Style.spacing.xs * 2)
            onOpened: pane.engaged = choice
            onClosed: if (pane.engaged === choice)
                pane.engaged = null
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
            // Where the rail's tabs were: the pane grows from the rail's corner.
            Row {
                id: navigation
                x: pane.dockLeft ? 0 : Math.max(0, parent.width - pane.overlay.railWidth + pane.overlay.uiPad + pane.gap)
                spacing: Style.spacing.xxs
                Action {
                    text: "Layouts"
                    horizontalPadding: 4
                    bordered: false
                    enabled: !pane.pending && !pane.busy
                    onClicked: pane.leave(false)
                }
                Action {
                    text: "Scenes"
                    horizontalPadding: 4
                    bordered: false
                    enabled: !pane.pending && !pane.busy
                    onClicked: pane.leave(true)
                }
                Action {
                    text: "Displays"
                    horizontalPadding: 4
                    bordered: false
                    selected: true
                }
            }
            Row {
                id: windowActions
                x: pane.dockLeft ? parent.width - width : 0
                spacing: Style.spacing.md
                Action {
                    text: identifyTimer.running ? "Identifying…" : "Identify displays"
                    tooltipText: "Show each screen's number on that screen for a few seconds"
                    Accessible.description: tooltipText
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
                    tooltipText: "Esc"
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
                spacing: Style.spacing.xl
                Label {
                    text: "Arrange your displays"
                    font.pixelSize: pane.overlay.uiFont * 1.4
                    font.bold: true
                }
                Label {
                    width: parent.width
                    text: pane.wallpaperMode ? "Select a screen to set its wallpaper." : pane.canArrange ? "Drag screens to line up their edges. Select one to change it." : "Select a screen to change it."
                    color: pane.muted
                }
                Rectangle {
                    id: diagram
                    width: parent.width
                    height: Math.max(150, parent.height - displayChips.height - diagramHint.height - pane.overlay.uiFont * 6)
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
                            radius: pane.overlay.radiusControl
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
                                width: parent.width - Style.spacing.xxl
                                spacing: Style.spacing.sm
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
                                anchors.bottomMargin: Style.spacing.xl
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                visible: pane.wallpaperMode && screen.height > pane.overlay.uiFont * 5
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
                    id: displayChips
                    width: parent.width
                    spacing: Style.spacing.md
                    Repeater {
                        model: pane.displayOrder
                        Action {
                            required property int modelData
                            readonly property int index: modelData
                            readonly property var entry: pane.draft.displays[index]
                            text: pane.numberOf(index) + " · " + entry.connector + (!entry.connected ? " · disconnected" : !entry.enabled ? " · disabled" : entry.mirror_of ? " · mirrors " + pane.numberOf(pane.draft.displays.findIndex(function (d) {
                                            return d.id === entry.mirror_of;
                                        })) : Displays.mirrorSource(pane.draft.displays, entry) ? " · in use" : pane.isAsleep(entry) ? " · asleep" : "")
                            tooltipText: Displays.displayName(entry)
                            selected: index === pane.selectedIndex
                            onClicked: pane.selectedIndex = index
                        }
                    }
                }
                Note {
                    id: diagramHint
                    text: (pane.canArrange ? "Numbered left to right. Tab to a screen; arrows nudge it 1 px, Shift + arrows 10 px." : "Tab to a screen to select it.")
                }
            }
            Flickable {
                id: inspector
                width: parent.width - parent.children[0].width - parent.spacing
                height: parent.height
                contentHeight: inspectorColumn.implicitHeight + pane.scrollHint
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar {
                    policy: Controls.ScrollBar.AlwaysOn
                    width: Math.max(4, Style.spacing.sm)
                    visible: inspector.contentHeight > inspector.height
                    contentItem: Rectangle {
                        implicitWidth: Math.max(4, Style.spacing.sm)
                        radius: width / 2
                        color: Util.alpha(pane.overlay.accent, .7)
                    }
                    background: Rectangle {
                        radius: width / 2
                        color: Util.alpha(pane.fg, .08)
                    }
                }
                Rectangle {
                    parent: inspector.contentItem
                    z: 5
                    x: 0
                    y: inspector.contentY + inspector.height - height
                    width: inspector.width - Style.spacing.xxl
                    height: pane.scrollHint
                    visible: inspector.contentY + inspector.height < inspector.contentHeight - Style.spacing.lg
                    color: pane.overlay.surfaceColor
                    Note {
                        anchors.centerIn: parent
                        width: implicitWidth
                        text: "Scroll for more settings ↓"
                    }
                }
                Column {
                    id: inspectorColumn
                    width: inspector.width - Style.spacing.xxl
                    spacing: Style.spacing.xl

                    // What the inspector is about: the selected display's
                    // settings, or its wallpaper group.
                    Row {
                        id: inspectorTabs
                        spacing: Style.spacing.sm
                        Action {
                            text: "Display"
                            selected: !pane.wallpaperMode
                            Accessible.role: Accessible.RadioButton
                            Accessible.checkable: true
                            Accessible.checked: selected
                            tooltipText: "Resolution, scale, rotation and workspaces"
                            enabled: !pane.busy && !pane.pending && !wallpaperEditor.busy
                            onClicked: pane.wallpaperMode = false
                        }
                        Action {
                            text: "Wallpaper"
                            selected: pane.wallpaperMode
                            Accessible.role: Accessible.RadioButton
                            Accessible.checkable: true
                            Accessible.checked: selected
                            tooltipText: "One wallpaper per display, or one spanning several"
                            enabled: !pane.busy && !pane.pending && !wallpaperEditor.busy
                            onClicked: pane.wallpaperMode = true
                        }
                    }

                    WallpaperSettings {
                        id: wallpaperEditor
                        width: parent.width
                        visible: pane.wallpaperMode
                        overlay: pane.overlay
                        displays: pane.draft.displays
                        selectedDisplay: pane.selectedDisplay
                        blocked: pane.busy || !!pane.pending || pane.dirty
                    }

                    Column {
                        id: settings
                        visible: !pane.wallpaperMode
                        width: parent.width
                        spacing: Style.spacing.xl
                        enabled: !pane.busy && !pane.pending

                        // ---- Which display: its name, its connector, sleep.
                        Item {
                            width: parent.width
                            implicitHeight: Math.max(displayTitle.implicitHeight, sleepAction.implicitHeight)
                            Column {
                                id: displayTitle
                                anchors.left: parent.left
                                anchors.right: sleepAction.visible ? sleepAction.left : parent.right
                                anchors.rightMargin: Style.spacing.lg
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: Style.spacing.xxs
                                Label {
                                    width: parent.width
                                    text: pane.selectedDisplay ? Displays.displayName(pane.selectedDisplay) : "No display selected"
                                    font.bold: true
                                    font.pixelSize: pane.overlay.uiFont * 1.25
                                    elide: Text.ElideRight
                                    wrapMode: Text.NoWrap
                                }
                                Note {
                                    visible: !!pane.selectedDisplay
                                    text: pane.selectedDisplay ? "Display " + pane.numberOf(pane.selectedIndex) + "  ·  " + pane.selectedDisplay.connector
                                        + (pane.selectedDisplay.connected && pane.selectedDisplay.ambiguous ? "  ·  settings kept for this connection" : "") : ""
                                }
                            }
                            Action {
                                id: sleepAction
                                // One button follows the compositor's power state, so
                                // it never offers to wake a display that is already on.
                                visible: !!pane.liveDisplay && !!pane.liveDisplay.enabled
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                text: pane.selectedAsleep ? "Wake" : "Sleep"
                                tooltipText: pane.selectedAsleep ? "Turn this display back on" : "Turn this display off for now; its workspaces stay. If Hypertile is on it, it moves first. A key press wakes the last awake display."
                                Accessible.name: pane.selectedAsleep ? "Wake display" : "Sleep display"
                                Accessible.description: tooltipText
                                onClicked: {
                                    // Never go dark with the display the overlay is on: move first.
                                    if (!pane.selectedAsleep)
                                        pane.overlay.placeDisplayConfirmation(null, pane.selectedDisplay.connector);
                                    pane.run([pane.selectedAsleep ? "wake" : "sleep", pane.selectedDisplay.connector]);
                                }
                            }
                        }
                        Label {
                            width: parent.width
                            visible: pane.selectedAsleep
                            text: "Asleep. Wake it here, or press a key if no other display is awake."
                            color: pane.overlay.accent
                        }

                        // ---- A saved display that is not connected.
                        Note {
                            visible: !!pane.selectedDisplay && !pane.selectedDisplay.connected
                            text: "Disconnected. Its settings and workspaces are kept for when it returns."
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.md
                            visible: !!pane.selectedDisplay && !pane.selectedDisplay.connected && pane.matchOptions.length > 1
                            Caption { text: "Match to a connected display" }
                            Choice {
                                width: parent.width
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
                                text: "Match saved display"
                                enabled: pane.matchingConnector !== ""
                                onClicked: pane.matchSelectedDisplay()
                            }
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.md
                            visible: !!pane.selectedDisplay && !pane.selectedDisplay.connected
                            Action {
                                text: "Forget this display"
                                tooltipText: "Remove its saved settings now: monitor rules, startup workspace and placement. Workspace layouts, windows and wallpaper groups stay. A reconnected display is found again."
                                enabled: !queryProcess.running && Displays.removalError(pane.draft, pane.selectedDisplay) === ""
                                Accessible.name: "Remove saved display"
                                Accessible.description: tooltipText
                                onClicked: pane.removeSelectedDisplay()
                            }
                            Note {
                                visible: text !== ""
                                text: Displays.removalError(pane.draft, pane.selectedDisplay) || (pane.matchOptions.length > 1 ? "" : "No connected display has this identity. Reconnect it to match its settings.")
                            }
                        }

                        // ---- Use as: extended, mirrored, disabled.
                        Column {
                            width: parent.width
                            spacing: Style.spacing.md
                            Caption { text: "Use as" }
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
                                spacing: Style.spacing.md
                                visible: !!pane.selectedMirrorSource
                                Label {
                                    width: parent.width
                                    text: pane.catalog ? Displays.mirrorStatus(pane.catalog.displays, pane.liveDisplay, pane.numbering) : ""
                                    color: pane.overlay.accent
                                }
                                Flow {
                                    width: parent.width
                                    spacing: Style.spacing.md
                                    Action {
                                        text: pane.liveDisplay && pane.selectedMirrorSource && pane.liveDisplay.id === pane.selectedMirrorSource.id ? "This display is in use" : "Use this display"
                                        primary: enabled
                                        enabled: !pane.dirty && !wallpaperEditor.dirty && !queryProcess.running && !!pane.catalog && Displays.canUseDisplay(pane.catalog.displays, pane.liveDisplay)
                                        tooltipText: "Size the shared desktop for this display; saved at once"
                                        Accessible.description: tooltipText
                                        onClicked: pane.useDisplay(pane.liveDisplay.connector)
                                    }
                                    Action {
                                        text: "Switch back to " + pane.previousSource
                                        visible: pane.previousSource !== "" && !!pane.catalog && !!pane.selectedMirrorSource && Displays.mirrorSource(pane.catalog.displays, pane.catalog.displays.find(function(d) { return d.connector === pane.previousSource; })) === pane.selectedMirrorSource
                                        enabled: !pane.dirty && !wallpaperEditor.dirty && !queryProcess.running && !!pane.catalog && Displays.canUseDisplay(pane.catalog.displays, pane.catalog.displays.find(function(d) { return d.connector === pane.previousSource; }))
                                        onClicked: pane.useDisplay(pane.previousSource)
                                    }
                                }
                                Note {
                                    text: pane.dirty || wallpaperEditor.dirty ? "Keep or discard your other edits before switching displays." : "Windows fit the active display; the others show a scaled copy. Switching saves at once."
                                }
                            }
                            Note {
                                visible: pane.selectedMirrors
                                text: "Follows display " + (pane.selectedDisplay ? pane.numberOf(pane.draft.displays.findIndex(function (d) {
                                    return d.id === pane.selectedDisplay.mirror_of;
                                })) : "") + "'s workspaces and layout. Its own settings come back with Extended."
                            }
                        }

                        // ---- Resolution, scale, rotation.
                        Column {
                            width: parent.width
                            spacing: Style.spacing.md
                            Caption { text: "Resolution and refresh rate" }
                            Choice {
                                width: parent.width
                                accessibleLabel: "Resolution and refresh rate"
                                model: Displays.modeChoices(pane.selectedDisplay)
                                textRole: "label"
                                displayText: Displays.currentModeLabel(pane.selectedDisplay)
                                onActivated: function (index) {
                                    var choice = model[index];
                                    var mode = {width: choice.width, height: choice.height, refresh: choice.refresh, mode_policy: choice.mode_policy};
                                    pane.setMode(mode);
                                }
                            }
                            Note {
                                visible: !!pane.selectedDisplay && !!pane.selectedDisplay.mode_policy && pane.selectedDisplay.mode_policy !== "fixed"
                                text: pane.selectedDisplay ? "Now " + Displays.modeLabel(pane.selectedDisplay) + "; follows the display's modes." : ""
                            }
                            Label {
                                width: parent.width
                                visible: !!pane.selectedDisplay && pane.selectedDisplay.mode_available === false
                                text: "The saved mode is unavailable. Choose one to turn this display on."
                                color: pane.overlay.accent
                            }
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.md
                            Caption { text: "Scale" }
                            Row {
                                id: scaleButtons
                                width: parent.width
                                spacing: Style.spacing.sm
                                readonly property var options: Displays.scaleOptions(pane.selectedDisplay)
                                Repeater {
                                    model: scaleButtons.options
                                    Action {
                                        required property var modelData
                                        width: (scaleButtons.width - scaleButtons.spacing * (scaleButtons.options.length - 1)) / scaleButtons.options.length
                                        horizontalPadding: Style.spacing.xs
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
                            spacing: Style.spacing.md
                            Caption { text: "Rotation" }
                            Choice {
                                width: parent.width
                                accessibleLabel: "Display rotation"
                                model: ["Normal", "90°", "180°", "270°", "Flipped", "Flipped 90°", "Flipped 180°", "Flipped 270°"]
                                currentIndex: pane.selectedDisplay ? pane.selectedDisplay.transform || 0 : 0
                                onActivated: function(index) { pane.setDisplay("transform", index); }
                            }
                        }

                        // ---- Position: dragging the diagram is the usual way.
                        Disclosure {
                            Accessible.name: "Position"
                            expanded: pane.positionExpanded
                            tooltipText: "Exact X and Y in logical pixels"
                            onClicked: pane.positionExpanded = !pane.positionExpanded
                        }
                        Row {
                            visible: pane.positionExpanded
                            width: parent.width
                            spacing: Style.spacing.xl
                            enabled: !!pane.selectedDisplay && !pane.selectedMirrors
                            Repeater {
                                model: ["x", "y"]
                                Column {
                                    required property string modelData
                                    width: (parent.width - parent.spacing) / 2
                                    spacing: Style.spacing.md
                                    Caption {
                                        text: modelData.toUpperCase() + " position"
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

                        // ---- Workspaces: which one shows here, which one at
                        // startup, and the layouts and placement for this display.
                        Disclosure {
                            visible: !!pane.selectedDisplay && pane.selectedDisplay.enabled && !pane.selectedMirrors
                            Accessible.name: "Workspaces"
                            expanded: pane.workspacePreferencesExpanded
                            tooltipText: "Show a workspace here, the startup workspace, this display's default layout and which workspaces live here"
                            onClicked: pane.workspacePreferencesExpanded = !pane.workspacePreferencesExpanded
                        }
                        Column {
                            width: parent.width
                            spacing: Style.spacing.xl
                            visible: pane.workspacePreferencesExpanded && !!pane.selectedDisplay && pane.selectedDisplay.enabled && !pane.selectedMirrors
                            Column {
                                width: parent.width
                                spacing: Style.spacing.md
                                Caption { text: "Show a workspace here" }
                                Row {
                                    width: parent.width
                                    spacing: Style.spacing.md
                                    Choice {
                                        width: parent.width - showWorkspaceAction.width - parent.spacing
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
                                        text: "Show"
                                        tooltipText: "Switch now; the workspace moves here if it is on another display"
                                        Accessible.name: "Show the selected workspace on this display"
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
                                Switch {
                                    label: "Start on this workspace"
                                    description: "At login this display shows it. Saved with Keep changes."
                                    enabled: pane.validSelectedWorkspace
                                    checked: !!pane.selectedDisplay && pane.selectedDisplay.initial_workspace === pane.selectedWorkspace
                                    onClicked: if (enabled) pane.setDisplay("initial_workspace", checked ? null : pane.selectedWorkspace)
                                }
                                Note {
                                    visible: !!pane.selectedDisplay && !!pane.selectedDisplay.initial_workspace && pane.selectedDisplay.initial_workspace !== pane.selectedWorkspace
                                    text: "Starts on workspace " + (pane.selectedDisplay ? String(pane.selectedDisplay.initial_workspace || "").replace(/^name:/, "") : "")
                                }
                            }
                            Column {
                                width: parent.width
                                spacing: Style.spacing.md
                                Caption { text: "Default layout on this display" }
                                Choice {
                                    width: parent.width
                                    accessibleLabel: "Default layout on this display"
                                    model: pane.layoutOptions
                                    textRole: "label"
                                    currentIndex: Math.max(0, pane.layoutOptions.findIndex(function (l) {
                                        return l.value === (pane.selectedDisplay ? pane.selectedDisplay.default_layout || null : null);
                                    }))
                                    onActivated: function (index) {
                                        pane.setDisplay("default_layout", pane.layoutOptions[index].value);
                                    }
                                }
                                Note { text: "For workspaces here without a layout of their own, new ones included." }
                            }
                            Column {
                                width: parent.width
                                spacing: Style.spacing.md
                                Caption { text: "Workspaces that live here" }
                                Repeater {
                                    model: pane.selectedAssignments()
                                    Row {
                                        required property string modelData
                                        width: settings.width
                                        spacing: Style.spacing.md
                                        Label {
                                            width: pane.overlay.uiFont * 6
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: "Workspace " + modelData.replace(/^name:/, "")
                                            elide: Text.ElideRight
                                            wrapMode: Text.NoWrap
                                        }
                                        Choice {
                                            width: parent.width - pane.overlay.uiFont * 6 - removeAssignment.width - parent.spacing * 2
                                            anchors.verticalCenter: parent.verticalCenter
                                            accessibleLabel: "Layout for workspace " + modelData.replace(/^name:/, "")
                                            model: [
                                                {
                                                    label: "Display default",
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
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: "Remove"
                                            Accessible.name: "Remove the display placement for workspace " + modelData.replace(/^name:/, "")
                                            onClicked: {
                                                var next = Displays.clone(pane.draft);
                                                delete next.workspaces[modelData].monitor;
                                                pane.draft = next;
                                                pane.dirty = true;
                                            }
                                        }
                                    }
                                }
                                Row {
                                    id: assignmentRow
                                    width: parent.width
                                    spacing: Style.spacing.md
                                    readonly property bool validEntry: Displays.validWorkspace(Displays.workspaceKey(workspaceField.text))
                                    Entry {
                                        id: workspaceField
                                        width: parent.width - addAssignment.width - parent.spacing
                                        placeholderText: "Number or workspace name"
                                        onAccepted: if (assignmentRow.validEntry) {
                                            pane.setAssignment(text, null, true);
                                            text = "";
                                        }
                                    }
                                    Action {
                                        id: addAssignment
                                        text: "Add"
                                        Accessible.name: "Place this workspace on this display"
                                        enabled: assignmentRow.validEntry
                                        onClicked: {
                                            pane.setAssignment(workspaceField.text, null, true);
                                            workspaceField.text = "";
                                        }
                                    }
                                }
                                Label {
                                    width: parent.width
                                    visible: workspaceField.text.trim() !== "" && !assignmentRow.validEntry
                                    text: "Use a number from 1, or a name made of letters, digits and . _ - :"
                                    color: pane.overlay.accent
                                    font.pixelSize: pane.overlay.uiCaption
                                }
                                Note { text: "Keep changes moves these workspaces here and remembers it for new ones. A scene keeps the layout it needs." }
                            }
                        }
                    }
                }
            }
        }
        Rectangle {
            id: footer
            width: parent.width
            height: Math.max(pane.overlay.uiFont * 3.4, footerText.implicitHeight + Style.spacing.xxl * 2)
            radius: pane.overlay.radiusControl
            color: pane.confirmingDiscard ? Util.alpha(Color.urgent, .1) : Util.alpha(pane.pending ? pane.overlay.accent : pane.fg, .06)
            Row {
                id: footerActions
                anchors.right: parent.right
                anchors.rightMargin: Style.spacing.xxl
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.spacing.md
                Action {
                    id: discardAction
                    visible: pane.confirmingDiscard
                    text: "Discard"
                    foreground: Color.urgent
                    accent: Color.urgent
                    tooltipText: "D"
                    Accessible.description: "Close and drop the unsaved display changes (D)"
                    onClicked: pane.discardAndClose()
                }
                Action {
                    id: keepEditingAction
                    visible: pane.confirmingDiscard
                    text: "Keep editing"
                    primary: true
                    tooltipText: "Esc"
                    Accessible.description: "Return to the unsaved changes (Esc)"
                    onClicked: pane.keepEditing()
                }
                Action {
                    visible: !pane.pending && !pane.confirmingDiscard
                    text: "Refresh"
                    tooltipText: "Read the connected displays again"
                    Accessible.description: tooltipText
                    enabled: !pane.busy
                    onClicked: pane.refresh()
                }
                Action {
                    visible: !pane.confirmingDiscard
                    text: pane.pending ? "Revert" : "Discard"
                    tooltipText: pane.pending ? "Put the previous settings back now (Esc)" : "Drop the edits that are not previewed yet"
                    Accessible.description: tooltipText
                    enabled: !pane.busy && (pane.dirty || !!pane.pending)
                    onClicked: pane.revert()
                }
                Action {
                    id: keepAction
                    visible: !pane.confirmingDiscard
                    text: pane.pending ? "Keep changes" : "Preview changes"
                    primary: enabled
                    tooltipText: pane.pending ? "Enter" : "Try the changes for 15 seconds before keeping them"
                    enabled: !pane.busy && !wallpaperEditor.dirty && !wallpaperEditor.busy && (pane.dirty || !!pane.pending)
                    onClicked: pane.pending ? pane.run(["keep", pane.pending.token]) : pane.preview()
                }
            }
            Label {
                id: footerText
                anchors.left: parent.left
                anchors.leftMargin: Style.spacing.xxl
                anchors.right: footerActions.left
                anchors.rightMargin: Style.spacing.xxl
                anchors.verticalCenter: parent.verticalCenter
                color: pane.error !== "" ? Readability.textColor(Color.urgent, pane.overlay.surfaceColor, 1) : pane.fg
                text: pane.confirmingDiscard ? "Close and discard the unsaved display changes? Nothing has been applied." : pane.error || (pane.busy ? "Applying…" : pane.pending ? "Keep these display settings? Enter keeps, Esc reverts. Reverting in " + pane.remaining + " seconds." : pane.notice || (pane.dirty ? "Ready to preview. You get 15 seconds to keep the changes." : "Display changes preview first, then you keep or revert them."))
            }
        }
    }
}
