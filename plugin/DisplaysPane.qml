import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import "Displays.js" as Displays

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
    onSelectedIndexChanged: matchingConnector = ""
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
    property bool dirty: false
    property bool closeAfterRevert: false
    property bool takeover: false
    property string error: ""
    property string notice: ""
    property var pending: null
    property string focusedPreviewToken: ""
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
    readonly property int remaining: pending ? Math.max(0, Math.ceil(Number(pending.deadline || pending.expires_at || 0) - clock)) : 0
    readonly property color fg: overlay.foreground
    readonly property color muted: overlay.mutedForeground
    readonly property real gap: overlay.uiPad
    readonly property var arrangement: Displays.extent(draft.displays)
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
    function reveal(item) {
        var y = item.mapToItem(settings, 0, 0).y;
        if (y < inspector.contentY)
            inspector.contentY = Math.max(0, y);
        else if (y + item.height > inspector.contentY + inspector.height - 36)
            inspector.contentY = Math.min(Math.max(0, inspector.contentHeight - inspector.height), y + item.height - inspector.height + 36);
    }
    function identify() {
        identifyTimer.restart();
    }
    function refresh() {
        if (!queryProcess.running && !busy)
            queryProcess.running = true;
    }
    function setDisplay(key, value) {
        if (!selectedDisplay || pending || busy)
            return;
        var next = Displays.clone(draft);
        next.displays[selectedIndex][key] = value;
        draft = next;
        dirty = true;
    }
    function setPosition(index, x, y) {
        var next = Displays.clone(draft);
        next.displays[index].x = Math.round(x);
        next.displays[index].y = Math.round(y);
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
        if (takeover)
            args.push("--takeover");
        run(args);
    }
    function revert() {
        if (pending)
            run(["revert", pending.token]);
        else {
            dirty = false;
            refresh();
        }
    }
    function requestClose() {
        if (pending) {
            closeAfterRevert = true;
            revert();
            notice = "Reverting display changes before closing.";
        } else
            closeRequested();
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
            visible: identifyTimer.running
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
            Rectangle {
                anchors.fill: parent
                radius: pane.overlay.radiusCard
                color: pane.overlay.surfaceColor
                border.color: pane.overlay.accent
                border.width: 2
                Column {
                    anchors.centerIn: parent
                    spacing: 8
                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: String(pane.draft.displays.findIndex(function (d) {
                            return d.connector === modelData.name;
                        }) + 1)
                        font.pixelSize: 42
                        font.bold: true
                    }
                    Label {
                        text: modelData.name
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
        wrapMode: Text.WordWrap
    }
    component Action: Controls.Button {
        id: action
        property bool primary: false
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
            color: Util.alpha(pane.overlay.accent, action.primary ? .23 : action.hovered ? .13 : .05)
            border.width: action.activeFocus ? 2 : 1
            border.color: action.activeFocus || action.primary ? pane.overlay.accent : Util.alpha(pane.fg, .25)
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
                spacing: 8
                Action {
                    text: "Layouts"
                    enabled: !pane.pending && !pane.busy
                    onClicked: pane.leave(false)
                }
                Action {
                    text: "Scenes"
                    enabled: !pane.pending && !pane.busy
                    onClicked: pane.leave(true)
                }
                Action {
                    text: "Displays"
                    primary: true
                }
            }
            Row {
                id: windowActions
                anchors.right: parent.right
                spacing: 8
                Action {
                    text: "Wake all"
                    enabled: !pane.busy
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
                    text: "Drag screens to align their edges. Select a screen to adjust its settings."
                    color: pane.muted
                }
                Rectangle {
                    id: diagram
                    width: parent.width
                    height: Math.max(190, parent.height - 190)
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
                            visible: modelData.connected && modelData.enabled
                            x: (logical.x - diagram.extent.x) * diagram.factor + (diagram.width - diagram.extent.w * diagram.factor) / 2
                            y: (logical.y - diagram.extent.y) * diagram.factor + (diagram.height - diagram.extent.h * diagram.factor) / 2
                            width: Math.max(16, logical.w * diagram.factor)
                            height: Math.max(16, logical.h * diagram.factor)
                            radius: 8
                            color: Util.alpha(pane.overlay.accent, index === pane.selectedIndex ? .25 : .07)
                            border.color: index === pane.selectedIndex ? pane.overlay.accent : Util.alpha(pane.fg, .45)
                            border.width: activeFocus ? 3 : 2
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: "Display " + (index + 1) + ", " + modelData.connector
                            Keys.onPressed: function (event) {
                                var dx = event.key === Qt.Key_Left ? -1 : event.key === Qt.Key_Right ? 1 : 0;
                                var dy = event.key === Qt.Key_Up ? -1 : event.key === Qt.Key_Down ? 1 : 0;
                                if ((dx || dy) && !pane.pending && !pane.busy) {
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
                                    text: String(screen.index + 1)
                                    font.pixelSize: Math.min(pane.overlay.uiFont * 1.5, screen.height * .45)
                                    font.bold: true
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                Label {
                                    width: parent.width
                                    text: screen.modelData.connector
                                    visible: screen.height > pane.overlay.uiFont * 3.8 && screen.width > pane.overlay.uiFont * 5
                                    font.pixelSize: pane.overlay.uiCaption
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                    wrapMode: Text.NoWrap
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                                property point origin
                                property point startPosition
                                onPressed: function (mouse) {
                                    screen.forceActiveFocus();
                                    pane.selectedIndex = screen.index;
                                    diagram.frozenExtent = Displays.clone(pane.arrangement);
                                    origin = mapToItem(diagram, mouse.x, mouse.y);
                                    startPosition = Qt.point(screen.logical.x, screen.logical.y);
                                }
                                onPositionChanged: function (mouse) {
                                    if (!pressed || pane.pending || pane.busy)
                                        return;
                                    var p = mapToItem(diagram, mouse.x, mouse.y);
                                    var snapped = Displays.snap(pane.draft.displays, screen.index, startPosition.x + (p.x - origin.x) / diagram.factor, startPosition.y + (p.y - origin.y) / diagram.factor, 12 / diagram.factor);
                                    pane.setPosition(screen.index, snapped.x, snapped.y);
                                }
                                onReleased: diagram.frozenExtent = null
                                onCanceled: diagram.frozenExtent = null
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
                        model: pane.draft.displays.length
                        Action {
                            readonly property var modelData: pane.draft.displays[index]
                            required property int index
                            text: (index + 1) + " · " + modelData.connector + (!modelData.connected ? " · disconnected" : !modelData.enabled ? " · disabled" : "")
                            primary: index === pane.selectedIndex
                            onClicked: pane.selectedIndex = index
                        }
                    }
                }
                Label {
                    width: parent.width
                    color: pane.muted
                    text: "Keyboard: Tab to a display, arrows move 1 px, Shift + arrows move 10 px. Positions use logical pixels."
                    font.pixelSize: pane.overlay.uiCaption
                }
            }
            Flickable {
                id: inspector
                width: parent.width - parent.children[0].width - parent.spacing
                height: parent.height
                contentHeight: settings.implicitHeight + 36
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
                Column {
                    id: settings
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
                        text: pane.selectedDisplay && pane.selectedDisplay.explicit_match ? "This connector is explicitly matched for this configuration." : "These displays share an identity. Match this connector deliberately before applying."
                        color: pane.overlay.accent
                    }
                    Action {
                        visible: !!pane.selectedDisplay && pane.selectedDisplay.connected && !!pane.selectedDisplay.ambiguous
                        text: (pane.selectedDisplay && pane.selectedDisplay.explicit_match ? "Matched · " : "Match to ") + (pane.selectedDisplay ? pane.selectedDisplay.connector : "")
                        primary: !!pane.selectedDisplay && !!pane.selectedDisplay.explicit_match
                        onClicked: pane.setDisplay("explicit_match", true)
                    }
                    Row {
                        spacing: 8
                        Action {
                            text: pane.selectedDisplay && pane.selectedDisplay.enabled ? "Disable display" : "Enable display"
                            enabled: !!pane.selectedDisplay && pane.selectedDisplay.connected
                            onClicked: pane.setDisplay("enabled", !pane.selectedDisplay.enabled)
                        }
                        Action {
                            text: "Identify"
                            enabled: !!pane.selectedDisplay && pane.selectedDisplay.connected
                            onClicked: identifyTimer.restart()
                        }
                    }
                    Row {
                        spacing: 8
                        Action {
                            text: "Sleep display"
                            enabled: !!pane.selectedDisplay && pane.selectedDisplay.enabled
                            onClicked: pane.run(["sleep", pane.selectedDisplay.connector])
                        }
                        Action {
                            text: "Wake"
                            enabled: !!pane.selectedDisplay && pane.selectedDisplay.connected
                            onClicked: pane.run(["wake", pane.selectedDisplay.connector])
                        }
                    }
                    Label {
                        width: parent.width
                        text: "Sleep is temporary and keeps workspaces in place. Press a keyboard key to wake."
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
                    Row {
                        width: parent.width
                        spacing: 12
                        Column {
                            width: (parent.width - 12) / 2
                            spacing: 6
                            Label {
                                text: "Scale"
                                font.bold: true
                            }
                            Entry {
                                width: parent.width
                                accessibleLabel: "Display scale"
                                text: pane.selectedDisplay ? String(Math.round(pane.selectedDisplay.scale * 10000) / 10000) : "1"
                                validator: DoubleValidator {
                                    bottom: 0.25
                                    top: 8
                                    decimals: 4
                                }
                                onEditingFinished: if (acceptableInput && Number(text) !== Math.round(pane.selectedDisplay.scale * 10000) / 10000)
                                    pane.setDisplay("scale", Number(text))
                            }
                        }
                        Column {
                            width: (parent.width - 12) / 2
                            spacing: 6
                            Label {
                                text: "Rotation"
                                font.bold: true
                            }
                            Choice {
                                width: parent.width
                                accessibleLabel: "Display rotation"
                                model: ["Normal", "90°", "180°", "270°", "Flipped", "Flipped 90°", "Flipped 180°", "Flipped 270°"]
                                currentIndex: pane.selectedDisplay ? pane.selectedDisplay.transform || 0 : 0
                                onActivated: function (index) {
                                    pane.setDisplay("transform", index);
                                }
                            }
                        }
                    }
                    Row {
                        width: parent.width
                        spacing: 12
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
                        text: "Initial workspace"
                        font.bold: true
                    }
                    Entry {
                        width: parent.width
                        accessibleLabel: "Initial workspace"
                        placeholderText: "Automatic"
                        text: pane.selectedDisplay ? pane.selectedDisplay.initial_workspace || "" : ""
                        onEditingFinished: pane.setDisplay("initial_workspace", text.trim() || null)
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
                                text: "Workspace " + modelData.replace(/^name:/, "")
                            }
                            Row {
                                width: parent.width
                                spacing: 8
                                Choice {
                                    width: parent.width - 82
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
                                    text: "Remove"
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
                            width: parent.width - 70
                            placeholderText: "Number or workspace name"
                            onAccepted: {
                                pane.setAssignment(text, null, true);
                                text = "";
                            }
                        }
                        Action {
                            text: "Add"
                            enabled: workspaceField.text.trim() !== ""
                            onClicked: {
                                pane.setAssignment(workspaceField.text, null, true);
                                workspaceField.text = "";
                            }
                        }
                    }
                    Label {
                        width: parent.width
                        text: "Applying moves existing workspaces and remembers placement for future workspaces. Active scenes keep their required layout; replace the scene from Layouts to change it."
                        color: pane.muted
                        font.pixelSize: pane.overlay.uiCaption
                    }
                    Label {
                        width: parent.width
                        visible: !!pane.catalog && (pane.catalog.conflicts || []).length > 0
                        text: "Existing configuration rules conflict:\n" + (pane.catalog ? (pane.catalog.conflicts || []).map(function (c) {
                                return typeof c === 'string' ? c : c.message || (c.path ? c.path + ":" + c.line + " · " + c.text : JSON.stringify(c));
                            }).join("\n") : "")
                        color: pane.overlay.accent
                    }
                    Controls.CheckBox {
                        visible: !!pane.catalog && (pane.catalog.conflicts || []).length > 0
                        checked: pane.takeover
                        onToggled: pane.takeover = checked
                        text: "Let Hypertile manage these display settings"
                        contentItem: Label {
                            text: parent.text
                            leftPadding: parent.indicator.width + 8
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }
        }
        Rectangle {
            id: footer
            width: parent.width
            height: Math.max(64, footerText.implicitHeight + 24)
            radius: pane.overlay.radiusControl
            color: Util.alpha(pane.pending ? pane.overlay.accent : pane.fg, .06)
            Row {
                id: footerActions
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                Action {
                    text: pane.pending ? "Revert" : "Reset"
                    enabled: !pane.busy && (pane.dirty || !!pane.pending)
                    onClicked: pane.revert()
                }
                Action {
                    id: keepAction
                    text: pane.pending ? "Keep changes" : "Preview changes"
                    primary: true
                    enabled: !pane.busy && (pane.dirty || !!pane.pending)
                    onClicked: pane.pending ? pane.run(["keep", pane.pending.token]) : pane.preview()
                }
                Action {
                    visible: !pane.pending
                    text: "Refresh"
                    enabled: !pane.busy
                    onClicked: pane.refresh()
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
                text: pane.error || (pane.busy ? "Applying…" : pane.pending ? "Keep these display settings? Reverting in " + pane.remaining + " seconds." : pane.notice || (pane.dirty ? "Changes are ready to preview. You will have 15 seconds to keep them." : "Changes are saved only after you choose Keep changes."))
            }
        }
    }
}
