import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Dialogs
import Quickshell.Io
import qs.Commons
import "Wallpaper.js" as Wallpaper

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
    readonly property string incomplete: group.mode === "span" && group.outputs.length < 2 ? "Check at least one more display to span the wallpaper across." : group.image === "" ? "Choose an image file, or use the current theme wallpaper." : ""
    spacing: 12
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
        width: parent.width
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: root.overlay.foreground
        font.family: root.overlay.fontFamily
        font.pixelSize: root.overlay.uiFontSmall
    }
    component Button: Controls.Button {
        font.family: root.overlay.fontFamily
        font.pixelSize: root.overlay.uiFontSmall
        padding: 10
        contentItem: Label { text: parent.text; horizontalAlignment: Text.AlignHCenter }
        background: Rectangle {
            radius: root.overlay.radiusControl
            color: Util.alpha(root.overlay.foreground, parent.hovered ? .12 : .05)
            border.width: parent.activeFocus ? 2 : 1
            border.color: parent.activeFocus ? root.overlay.accent : Util.alpha(root.overlay.foreground, .25)
        }
    }
    component Check: Controls.CheckBox {
        width: parent.width
        font.family: root.overlay.fontFamily
        font.pixelSize: root.overlay.uiFontSmall
        contentItem: Label {
            text: parent.text
            leftPadding: parent.indicator.width + parent.spacing
            verticalAlignment: Text.AlignVCenter
        }
    }
    Label { text: "Wallpaper · " + root.output; font.bold: true; font.pixelSize: root.overlay.uiFont * 1.25 }
    Label { text: "Span selected displays, or keep this display independent. Each group can follow the theme or use its own image."; color: root.overlay.mutedForeground }
    Label { visible: !root.usable; text: "Mirrored displays share their source display’s wallpaper." }
    Column {
        width: parent.width
        spacing: 10
        visible: root.usable
        enabled: root.loaded
        Check {
            text: "Span wallpaper across a group"
            checked: root.group.mode === "span"
            onClicked: root.edit("mode", checked ? "span" : "repeat")
        }
        Label {
            visible: root.group.mode === "repeat"
            text: "Independent display. Using the theme image on independent displays repeats the wallpaper on each screen."
            color: root.overlay.mutedForeground
        }
        Column {
            width: parent.width
            spacing: 4
            visible: root.group.mode === "span"
            Label { text: "Displays in this group"; font.bold: true }
            Repeater {
                model: root.displays.filter(function (d) { return !d.mirror_of; })
                Check {
                    required property var modelData
                    text: modelData.connector + (!modelData.connected ? " · disconnected" : !modelData.enabled ? " · disabled" : "")
                    checked: root.group.outputs.indexOf(modelData.connector) >= 0
                    enabled: modelData.connector !== root.output
                    onClicked: root.member(modelData.connector, checked)
                }
            }
            Label { text: "Adding a display moves it from its previous wallpaper group. Disconnected members rejoin when available."; color: root.overlay.mutedForeground }
        }
        Check {
            text: "Use the current theme wallpaper"
            checked: root.group.image === null
            onClicked: root.edit("image", checked ? null : "")
        }
        Column {
            width: parent.width
            spacing: 8
            visible: root.group.image !== null
            Controls.TextField {
                width: parent.width
                text: root.group.image || ""
                placeholderText: "Image file path"
                Accessible.name: "Wallpaper image file"
                color: root.overlay.foreground
                font.family: root.overlay.fontFamily
                selectByMouse: true
                onTextEdited: root.edit("image", text)
            }
            Button { text: "Choose image…"; onClicked: fileDialog.open() }
            Label { text: "This image stays fixed when the theme changes."; color: root.overlay.mutedForeground }
        }
        Check {
            text: "Fit entire image (may leave black borders)"
            checked: root.group.fit === "fit"
            onClicked: root.edit("fit", checked ? "fit" : "crop")
        }
        Label { text: "Otherwise, the image fills the display or group, cropping the edges as needed."; color: root.overlay.mutedForeground }
        Label { visible: root.incomplete !== ""; text: root.incomplete; color: root.overlay.accent }
        Row {
            spacing: 8
            Button { text: "Apply wallpaper"; enabled: root.dirty && root.incomplete === ""; onClicked: root.apply() }
            Button { text: "Reset"; enabled: root.dirty; onClicked: root.discard() }
            Button { text: "Refresh"; enabled: !root.dirty; onClicked: root.refresh() }
        }
    }
    Label { text: root.error || root.notice; visible: text !== ""; color: root.error ? "#ff8888" : root.overlay.foreground }
    Label { text: root.blocked ? "Finish or reset your display changes before editing wallpaper." : "Apply wallpaper saves immediately. First-time setup or a renderer update briefly reloads the shell. Groups persist across theme changes."; color: root.overlay.mutedForeground }
    FileDialog {
        id: fileDialog
        title: "Choose wallpaper image"
        nameFilters: ["Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif)"]
        onAccepted: root.edit("image", decodeURIComponent(String(selectedFile).replace(/^file:\/\//, "")))
    }
}
