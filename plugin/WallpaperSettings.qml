import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Dialogs
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Displays.js" as Displays
import "Readability.js" as Readability
import "Wallpaper.js" as Wallpaper

// The Displays inspector's Wallpaper view: the selected display's wallpaper
// group. Three either/or choices (its own wallpaper or a span across
// displays; the theme's image or a custom one; fill or fit), then Apply.
// Applying saves at once; it is not part of the display Preview and Keep.
Column {
    id: root
    required property var overlay
    required property var displays
    required property var selectedDisplay
    property bool blocked: false
    property var saved: ({version: 1, groups: []})
    property var draft: ({version: 1, groups: []})
    property bool loaded: false
    property string error: ""
    property string notice: ""
    readonly property bool dirty: JSON.stringify(saved) !== JSON.stringify(draft)
    readonly property bool busy: process.running
    readonly property string output: selectedDisplay ? selectedDisplay.connector : ""
    readonly property var group: Wallpaper.groupFor(draft, output)
    readonly property bool usable: !!selectedDisplay && !selectedDisplay.mirror_of
    // Apply waits until the group can be saved, and says what is missing.
    readonly property string incomplete: group.mode === "span" && group.outputs.length < 2 ? "Choose at least one more display to span." : group.image === "" ? "Choose an image file, or use the theme wallpaper." : ""
    spacing: Style.spacing.xl
    enabled: !busy && !blocked
    signal applied
    function edit(key, value) {
        var next = Object.assign({}, group);
        next[key] = value;
        if (key === "mode" && value === "repeat") next.outputs = [output];
        draft = Wallpaper.setGroup(draft, output, next);
        notice = "";
    }
    function member(name, checked) {
        var members = group.outputs.filter(function (o) { return o !== name; });
        if (checked) members.push(name);
        edit("outputs", members);
    }
    function refresh() {
        if (busy) return;
        process.command = [overlay.ctl, "display", "wallpaper"];
        process.running = true;
    }
    function discard() { draft = JSON.parse(JSON.stringify(saved)); error = ""; }
    function apply() {
        if (busy || blocked || !loaded || incomplete) return;
        process.command = [overlay.ctl, "display", "wallpaper", "--json", JSON.stringify({settings: draft, previous: saved})];
        process.running = true;
    }
    Component.onCompleted: refresh()
    Process {
        id: process
        stdout: StdioCollector { id: outputText; waitForEnd: true }
        stderr: StdioCollector { id: errorText; waitForEnd: true }
        onExited: function(code) {
            try {
                var result = JSON.parse(outputText.text);
                if (code !== 0) { root.error = result.error || "Could not apply wallpaper."; return; }
                root.saved = result.settings;
                root.draft = JSON.parse(JSON.stringify(result.settings));
                root.loaded = true;
                root.error = "";
                root.notice = result.message || "";
                if (command.length > 3) root.applied();
            } catch (e) { root.error = errorText.text.trim() || "Could not read wallpaper settings."; }
        }
    }
    component Label: Text {
        width: parent ? parent.width : implicitWidth
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: root.overlay.foreground
        font.family: root.overlay.fontFamily
        font.pixelSize: root.overlay.uiFontSmall
    }
    component Note: Label {
        color: root.overlay.mutedForeground
        font.pixelSize: root.overlay.uiCaption
    }
    component Caption: Label {
        font.bold: true
    }
    component Action: KitButton {
        overlay: root.overlay
        focusable: true
    }
    // Two exclusive choices side by side; the current one reads as pressed.
    component Pair: Row {
        id: pair
        property var options: []        // [{ label, value, hint }]
        property var value
        signal picked(var value)
        spacing: Style.spacing.sm
        Repeater {
            model: pair.options
            Action {
                required property var modelData
                text: modelData.label
                tooltipText: modelData.hint || ""
                selected: pair.value === modelData.value
                Accessible.role: Accessible.RadioButton
                Accessible.checkable: true
                Accessible.checked: selected
                onClicked: if (pair.value !== modelData.value) pair.picked(modelData.value)
            }
        }
    }

    Column {
        width: parent.width
        spacing: Style.spacing.xxs
        Label {
            text: root.selectedDisplay ? Displays.displayName(root.selectedDisplay) : "No display selected"
            font.bold: true
            font.pixelSize: root.overlay.uiFont * 1.25
            elide: Text.ElideRight
            wrapMode: Text.NoWrap
        }
        Note { visible: root.output !== ""; text: root.output + "  ·  wallpaper" }
    }
    Note { visible: !root.usable; text: "A mirrored display shows its source's wallpaper." }
    Column {
        width: parent.width
        spacing: Style.spacing.xl
        visible: root.usable
        enabled: root.loaded

        Column {
            width: parent.width
            spacing: Style.spacing.md
            Caption { text: "Covers" }
            Pair {
                options: [{ label: "This display", value: "repeat", hint: "Its own wallpaper" }, { label: "Span displays", value: "span", hint: "One image stretched across several displays" }]
                value: root.group.mode
                onPicked: function(v) { root.edit("mode", v) }
            }
            Flow {
                visible: root.group.mode === "span"
                width: parent.width
                spacing: Style.spacing.sm
                Repeater {
                    model: root.displays.filter(function (d) { return !d.mirror_of; })
                    Action {
                        required property var modelData
                        readonly property bool member: root.group.outputs.indexOf(modelData.connector) >= 0
                        text: (member ? "✓ " : "") + modelData.connector + (!modelData.connected ? " · disconnected" : !modelData.enabled ? " · disabled" : "")
                        tooltipText: modelData.connector === root.output ? "The selected display is always in its span" : (member ? "Leave the span" : "Join the span; it leaves its old group")
                        selected: member
                        enabled: modelData.connector !== root.output
                        Accessible.role: Accessible.CheckBox
                        Accessible.checkable: true
                        Accessible.checked: member
                        onClicked: root.member(modelData.connector, !member)
                    }
                }
            }
        }

        Column {
            width: parent.width
            spacing: Style.spacing.md
            Caption { text: "Image" }
            Pair {
                options: [{ label: "Theme wallpaper", value: "theme", hint: "Follows the theme" }, { label: "Custom image", value: "custom", hint: "Stays the same when the theme changes" }]
                value: root.group.image === null ? "theme" : "custom"
                onPicked: function(v) { root.edit("image", v === "theme" ? null : "") }
            }
            Row {
                visible: root.group.image !== null
                width: parent.width
                spacing: Style.spacing.sm
                TextField {
                    id: imageField
                    width: parent.width - chooseImage.width - parent.spacing
                    text: root.group.image || ""
                    placeholderText: "Image file path"
                    foreground: root.overlay.foreground
                    accent: root.overlay.accent
                    font.family: root.overlay.fontFamily
                    font.pixelSize: root.overlay.uiFontSmall
                    Accessible.name: "Wallpaper image file"
                    Component.onCompleted: background.radius = root.overlay.radiusControl
                    onTextEdited: root.edit("image", text)
                    anchors.verticalCenter: parent.verticalCenter
                }
                Action {
                    id: chooseImage
                    text: "Choose…"
                    Accessible.name: "Choose image"
                    onClicked: fileDialog.open()
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }

        Column {
            width: parent.width
            spacing: Style.spacing.md
            Caption { text: "Fit" }
            Pair {
                options: [{ label: "Fill", value: "crop", hint: "Fills the screen; the edges may be cropped" }, { label: "Fit", value: "fit", hint: "Shows the whole image; borders may show" }]
                value: root.group.fit === "fit" ? "fit" : "crop"
                onPicked: function(v) { root.edit("fit", v) }
            }
        }

        Label { visible: root.incomplete !== ""; text: root.incomplete; color: root.overlay.accent }
        Flow {
            width: parent.width
            spacing: Style.spacing.sm
            Action { text: "Apply wallpaper"; primary: enabled; tooltipText: "Saves at once. The first time, the shell reloads briefly."; enabled: root.dirty && root.incomplete === ""; onClicked: root.apply() }
            Action { text: "Discard"; tooltipText: "Drop the wallpaper edits"; enabled: root.dirty; onClicked: root.discard() }
            Action { text: "Refresh"; tooltipText: "Read the saved wallpaper settings again"; enabled: !root.dirty; onClicked: root.refresh() }
        }
    }
    Label {
        text: root.error || root.notice
        visible: text !== ""
        color: root.error ? Readability.textColor(Commons.Color.urgent, root.overlay.surfaceColor, 1) : root.overlay.foreground
    }
    Note { text: root.blocked ? "Keep or discard the display changes before editing the wallpaper." : "Applies at once and stays through theme changes." }
    // Inside the overlay's layer surface, like the layout import and export
    // dialogs: a native dialog would open behind the fullscreen overlay.
    FileDialog {
        id: fileDialog
        parentWindow: root.Window.window
        options: FileDialog.DontUseNativeDialog
        popupType: Controls.Popup.Item
        title: "Choose wallpaper image"
        nameFilters: ["Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif)"]
        onAccepted: root.edit("image", decodeURIComponent(String(selectedFile).replace(/^file:\/\//, "")))
    }
}
