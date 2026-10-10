import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Controls.Material 2.15
import QtQuick.Layouts 1.15
import "../components"
import "../js/I18n.js" as I18n

Item {
    id: root
    property var themeObj: null
    property var t: themeObj

    // Reusable Card container
    component AppCard: Rectangle {
        color: t ? t.bg3 : "#22222f"
        border.color: t ? t.border1 : "#2e2e3e"
        border.width: 1
        radius: 12
    }

    property int animDotCount: 0
    Timer {
        interval: 400
        running: editorBackend.isScanning
        repeat: true
        onTriggered: root.animDotCount = (root.animDotCount + 1) % 4
    }
    function getAnimatedDots() {
        return animDotCount === 1 ? "." : (animDotCount === 2 ? ".." : (animDotCount === 3 ? "..." : ""))
    }

    //: Entry the "Translate with" menu will act on. Set on right-click, because
    //: the menu is shared by every row rather than instantiated per delegate.
    property int contextEntryId: -1

    Menu {
        id: translateWithMenu
        Material.theme: Material.Dark

        MenuItem {
            enabled: false
            height: 30
            contentItem: Text {
                text: localeManager.strings.editor.translate_with_title
                font.pixelSize: 11
                font.bold: true
                color: t ? t.textSecondary : "#9090b8"
                verticalAlignment: Text.AlignVCenter
            }
        }
        MenuSeparator {}

        MenuItem {
            text: localeManager.strings.editor.paste_translation_next + "   (Ctrl+Shift+V)"
            enabled: root.contextEntryId > 0 && root.selectedIds.length <= 1
            onTriggered: root.pasteAndAdvance(root.contextEntryId)
        }
        MenuItem {
            text: root.selectedIds.length > 1
                  ? I18n.format(localeManager.strings.editor.retranslate_many, {count: root.selectedIds.length})
                  : localeManager.strings.editor.retranslate_one
            enabled: !editorBackend.singleTranslateRunning
                     && root.actionTargets(root.contextEntryId).length > 0
            onTriggered: {
                var ids = root.actionTargets(root.contextEntryId)
                editorBackend.translateEntriesWith(ids, "")
            }
        }
        MenuItem {
            text: root.selectedIds.length > 1
                  ? I18n.format(localeManager.strings.editor.restore_many, {count: root.selectedIds.length})
                  : localeManager.strings.editor.restore_one
            enabled: root.actionTargets(root.contextEntryId).length > 0
            onTriggered: {
                var ids = root.actionTargets(root.contextEntryId)
                var n = editorBackend.revertEntries(ids)
                root.clearSelection()
                root.showNotice(I18n.format(localeManager.strings.editor.restore_done, {count: n}))
            }
        }
        MenuItem {
            text: localeManager.strings.editor.select_all_page
            onTriggered: root.selectedIds = editorBackend.currentPageEntryIds()
        }
        MenuItem {
            text: localeManager.strings.editor.clear_selection
            enabled: root.selectedIds.length > 0
            onTriggered: root.clearSelection()
        }

        MenuSeparator {}

        MenuItem {
            enabled: false
            height: 26
            contentItem: Text {
                text: localeManager.strings.editor.translate_with_keyless_hint
                font.pixelSize: 10
                color: t ? t.textMuted : "#55556a"
                verticalAlignment: Text.AlignVCenter
            }
        }

        //: A Repeater parents its items to the Menu's content item, which makes
        //: Qt complain that it cannot stack them ("must be a sibling") and can
        //: leave them out of order. Instantiator + insertItem is the supported
        //: way to build menu entries from a model.
        Instantiator {
            model: editorBackend.singleTranslateEngines
            onObjectAdded: (index, object) => translateWithMenu.addItem(object)
            onObjectRemoved: (index, object) => translateWithMenu.removeItem(object)
            delegate: MenuItem {
                text: modelData.available
                      ? modelData.name
                      : modelData.name + "  " + localeManager.strings.editor.translate_with_setup
                enabled: !editorBackend.singleTranslateRunning
                onTriggered: {
                    if (root.contextEntryId <= 0)
                        return
                    if (modelData.available) {
                        var ids = root.actionTargets(root.contextEntryId)
                        if (ids.length === 1)
                            root.selectRow(ids[0])
                        editorBackend.translateEntriesWith(ids, modelData.id)
                        return
                    }
                    // No key yet: send them to the provider, then take the paste.
                    keyDialog.engineId = modelData.id
                    keyDialog.engineName = modelData.name
                    keyDialog.setupUrl = modelData.setupUrl
                    keyDialog.keyText = editorBackend.clipboardApiKeyCandidate(modelData.id)
                    keyDialog.errorText = ""
                    if (modelData.setupUrl !== "")
                        appBackend.openUrl(modelData.setupUrl)
                    keyDialog.open()
                }
            }
        }

    }

    Connections {
        target: editorBackend
        function onSingleTranslateFinished(entryId, ok, message) {
            root.showNotice(ok
                ? localeManager.strings.editor.translate_with_done + " " + message
                : localeManager.strings.editor.translate_with_failed + " " + message)
        }
    }
    property string singleTranslateNotice: ""
    Timer {
        id: singleTranslateNoticeTimer
        interval: 4000
        onTriggered: root.singleTranslateNotice = ""
    }

    // Floating result banner for right-click translations. Kept above the
    // editor content so it reads the same whichever row was acted on.
    Rectangle {
        z: 100
        visible: root.singleTranslateNotice !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        implicitWidth: noticeText.implicitWidth + 28
        implicitHeight: 34
        radius: 8
        color: t ? t.bg4 : "#2a2a3a"
        border.color: t ? t.accent : "#7c6cf8"
        border.width: 1
        Text {
            id: noticeText
            anchors.centerIn: parent
            text: root.singleTranslateNotice
            font.pixelSize: 12
            color: t ? t.textPrimary : "#f0f0ff"
        }
    }

    Popup {
        id: keyDialog
        property string engineId: ""
        property string engineName: ""
        property string setupUrl: ""
        property string keyText: ""
        property string errorText: ""

        width: 460
        implicitHeight: keyCol.implicitHeight + 48
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape
        anchors.centerIn: Overlay.overlay

        background: Rectangle {
            radius: 14
            color: t ? t.bg2 : "#1a1a24"
            border.color: t ? t.border2 : "#3d3d55"
            border.width: 1
        }

        ColumnLayout {
            id: keyCol
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14

            Text {
                text: localeManager.strings.editor.key_dialog_title + " " + keyDialog.engineName
                font.pixelSize: 14; font.bold: true
                color: t ? t.textPrimary : "#f0f0ff"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
            Text {
                text: localeManager.strings.editor.key_dialog_body
                font.pixelSize: 11
                color: t ? t.textSecondary : "#9090b8"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 34
                radius: 8
                color: t ? t.bg4 : "#2a2a3a"
                border.color: t ? t.border2 : "#3d3d55"
                border.width: 1
                TextField {
                    id: keyField
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    text: keyDialog.keyText
                    placeholderText: localeManager.strings.editor.key_dialog_placeholder
                    color: t ? t.textPrimary : "#f0f0ff"
                    placeholderTextColor: t ? t.textMuted : "#55556a"
                    font.pixelSize: 12
                    background: Item {}
                    onTextChanged: keyDialog.keyText = text
                }
            }

            Text {
                visible: keyDialog.errorText !== ""
                text: keyDialog.errorText
                font.pixelSize: 11
                color: t ? t.danger : "#f87171"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Button {
                    text: localeManager.strings.editor.key_dialog_paste
                    onClicked: {
                        var c = editorBackend.clipboardApiKeyCandidate(keyDialog.engineId)
                        if (c !== "") { keyField.text = c; keyDialog.errorText = "" }
                        else keyDialog.errorText = localeManager.strings.editor.key_dialog_clipboard_empty
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: localeManager.strings.common.cancel
                    onClicked: keyDialog.close()
                }
                Button {
                    text: localeManager.strings.common.confirm
                    enabled: keyDialog.keyText.length > 0
                    onClicked: {
                        var res = editorBackend.saveApiKeyFor(keyDialog.engineId, keyDialog.keyText)
                        if (res.ok) {
                            keyDialog.close()
                            root.singleTranslateNotice = res.message
                            singleTranslateNoticeTimer.restart()
                        } else {
                            keyDialog.errorText = res.message
                        }
                    }
                }
            }
        }
    }

    //: Ids of rows picked out by click-drag, Ctrl+click or Shift+click. Empty
    //: means "no multi-selection" and actions fall back to the right-clicked row.
    property var selectedIds: []
    property int dragAnchorIndex: -1
    property bool dragSelecting: false
    property bool dragMoved: false

    function isRowSelected(entryId) {
        return root.selectedIds.indexOf(entryId) !== -1
    }

    function clearSelection() {
        root.selectedIds = []
        root.dragAnchorIndex = -1
        root.dragSelecting = false
        root.dragMoved = false
    }

    function toggleSelection(entryId) {
        var ids = root.selectedIds.slice()
        var at = ids.indexOf(entryId)
        if (at === -1) ids.push(entryId)
        else ids.splice(at, 1)
        root.selectedIds = ids
    }

    //: Range select across the visible page, by row order rather than id, so a
    //: filtered view selects what the user actually sees between the two clicks.
    function selectIndexRange(a, b) {
        var page = editorBackend.currentPageEntryIds()
        if (a > b) { var t = a; a = b; b = t }
        a = Math.max(0, a)
        b = Math.min(page.length - 1, b)
        if (b < a) { root.selectedIds = []; return }
        var next = page.slice(a, b + 1)
        // Re-assigning an identical array still churns every delegate binding.
        if (next.length !== root.selectedIds.length ||
            next[0] !== root.selectedIds[0] ||
            next[next.length - 1] !== root.selectedIds[root.selectedIds.length - 1])
            root.selectedIds = next
    }

    //: Row index under a point given in stringListView coordinates, or -1.
    function rowIndexAt(viewX, viewY) {
        return stringListView.indexAt(
            stringListView.contentX + viewX,
            stringListView.contentY + viewY)
    }

    //: Rows the next action applies to: the multi-selection if there is one,
    //: otherwise just the row under the cursor.
    function actionTargets(fallbackId) {
        if (root.selectedIds.length > 0)
            return root.selectedIds
        return fallbackId > 0 ? [fallbackId] : []
    }

    //: Report a slot result. Uses the app-wide toast like every other editor
    //: action, and falls back to the in-view banner if the toast is not in scope,
    //: so an action can never appear to do nothing.
    function reportResult(res, title) {
        var message = (res && res.message) ? res.message : "No result returned."
        var ok = !!(res && res.ok)
        if (typeof toast !== "undefined") {
            toast.show(ok ? "success" : "warning", title, message)
        } else {
            root.showNotice(message)
        }
        console.log("[Editor] " + title + ": " + message)
    }

    function showNotice(text) {
        root.singleTranslateNotice = text
        singleTranslateNoticeTimer.restart()
    }

    //: Takes the clipboard as the translation for `entryId`, then jumps to the
    //: next untranslated row so a browser round-trip is two keystrokes, not six.
    function pasteAndAdvance(entryId) {
        if (entryId <= 0)
            return
        var res = editorBackend.pasteTranslationForEntry(entryId)
        root.showNotice(res.message)
        if (res.ok && res.nextId > 0) {
            root.selectRow(res.nextId)
            root.contextEntryId = res.nextId
        }
    }

    Shortcut {
        sequence: "Ctrl+A"
        context: Qt.WindowShortcut
        onActivated: root.selectedIds = editorBackend.currentPageEntryIds()
    }

    Shortcut {
        sequence: "Escape"
        context: Qt.WindowShortcut
        onActivated: root.clearSelection()
    }

    Shortcut {
        sequence: "Ctrl+Shift+V"
        context: Qt.WindowShortcut
        onActivated: {
            var id = editorBackend.selectedEntry && editorBackend.selectedEntry.id
                     ? editorBackend.selectedEntry.id : root.contextEntryId
            root.pasteAndAdvance(id)
        }
    }

    function selectRow(entryId) {
        if (editorBackend.selectedEntry && editorBackend.selectedEntry.id && typeof transTextArea !== "undefined" && transTextArea.userEdited && transTextArea.text !== (editorBackend.selectedEntry.translated_text || "")) {
            editorBackend.updateSelectedTranslation(transTextArea.text)
            transTextArea.userEdited = false
        }
        editorBackend.selectEntryById(entryId)
    }

    function changePage(newPage) {
        if (editorBackend.selectedEntry && editorBackend.selectedEntry.id && typeof transTextArea !== "undefined" && transTextArea.userEdited && transTextArea.text !== (editorBackend.selectedEntry.translated_text || "")) {
            editorBackend.updateSelectedTranslation(transTextArea.text)
        }
        editorBackend.setPage(newPage)
    }

    // Commit any text still sitting in the detail editor (not yet applied via
    // Ctrl+Enter / row change) so a direct Save never silently drops it.
    readonly property bool hasPendingEdit: !!(editorBackend.selectedEntry && editorBackend.selectedEntry.id)
        && transTextArea.userEdited && transTextArea.text !== (editorBackend.selectedEntry.translated_text || "")

    function flushPendingEdit() {
        if (editorBackend.selectedEntry && editorBackend.selectedEntry.id && typeof transTextArea !== "undefined" && transTextArea.userEdited && transTextArea.text !== (editorBackend.selectedEntry.translated_text || "")) {
            editorBackend.updateSelectedTranslation(transTextArea.text)
        }
    }

    // Allow dragging and dropping game folder or Game.exe anywhere on Editor tab
    DropArea {
        id: dropArea
        anchors.fill: parent
        onDropped: (drop) => {
            if (drop.hasUrls && drop.urls.length > 0) {
                // Hand the raw URL to Python: QUrl.toLocalFile() handles
                // Windows (file:///D:/x) and POSIX (file:///home/x) correctly.
                editorBackend.setProjectPath(drop.urls[0].toString())
            }
        }
    }

    Connections {
        target: editorBackend
        function onSaveFinished(success, message) {
            if (typeof toast !== "undefined") {
                toast.show(success ? "success" : "error", success ? localeManager.strings.editor.save_success_title : localeManager.strings.editor.save_error_title, message)
            }
        }
        function onBatchReplaceFinished(count, message) {
            if (typeof toast !== "undefined") {
                toast.show(count > 0 ? "success" : "info", localeManager.strings.editor.batch_replace_toast_title, message)
            }
        }
        function onSelectedEntryChanged() {
            if (typeof transTextArea !== "undefined") {
                transTextArea.text = editorBackend.selectedEntry.translated_text || ""
            }
        }
        function onScanFinished(success, message, count) {
            if (!success && message) {
                if (typeof toast !== "undefined") {
                    toast.show("warning", localeManager.strings.editor.toast_title_generic, message)
                }
            }
        }
        function onAutoTranslateFinished(success, message) {
            if (typeof toast !== "undefined") {
                toast.show(
                    success ? "success" : "error",
                    localeManager.strings.editor.auto_translate_toast_title,
                    message
                )
            }
        }
    }

    BatchReplaceDialog {
        id: replaceDialog
        themeObj: t
        onReplaceRequested: (search, replace, fileScope, matchCase) => {
            editorBackend.batchReplace(search, replace, fileScope, "all", matchCase)
        }
    }

    AutoTranslateDialog {
        id: autoTranslateDialog
        themeObj: t
        onStartRequested: (options) => {
            editorBackend.startAutoTranslateWithOptions(options)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12

        // =====================================================
        // HEADER & ACTION BAR
        // =====================================================
        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            ColumnLayout {
                spacing: 2
                Text {
                    text: localeManager.strings.editor.header_title
                    font.pixelSize: 18
                    font.bold: true
                    color: t ? t.textPrimary : "#ffffff"
                }
                Text {
                    text: !editorBackend.projectPath
                        ? localeManager.strings.editor.status_no_project
                        : (editorBackend.isScanning
                            ? (editorBackend.scanProgressText ? (editorBackend.scanProgressText + " (" + editorBackend.scanProgressCurrent + "%)") : (localeManager.strings.editor.status_scanning + getAnimatedDots()))
                            : (editorBackend.isAutoTranslating
                                ? editorBackend.autoTranslateStatus
                                : (editorBackend.projectLoaded
                                    ? (editorBackend.totalProjectCount > 0
                                        ? I18n.format(localeManager.strings.editor.status_loaded, {count: editorBackend.totalCount, total: editorBackend.totalProjectCount, modified: editorBackend.unsavedCount})
                                        : localeManager.strings.editor.status_no_data)
                                    : localeManager.strings.editor.status_waiting)))
                    font.pixelSize: 12
                    color: (editorBackend.isScanning || editorBackend.isAutoTranslating) ? "#ffaa00" : (t ? t.textSecondary : "#9a9ab2")
                }
            }

            Item { Layout.fillWidth: true }

            // Rescan Button
            TactileButton {
                label: editorBackend.scanAttempted ? localeManager.strings.editor.rescan_button : (localeManager.strings.editor.load_project_button || "Load Project")
                variant: "ghost"
                enabled_: !editorBackend.isScanning && !appBackend.isRunning && !editorBackend.isAutoTranslating && editorBackend.projectPath.length > 0
                onClicked: editorBackend.loadProject(editorBackend.scanAttempted)
            }

            // Auto Translate All button
            TactileButton {
                label: editorBackend.isAutoTranslating
                    ? I18n.format(localeManager.strings.editor.auto_translate_cancel_button, {progress: editorBackend.autoTranslateProgress})
                    : (localeManager.strings.editor.auto_translate_all_button + (editorBackend.untranslatedCount > 0 ? " (" + editorBackend.untranslatedCount + ")" : ""))
                variant: editorBackend.isAutoTranslating ? "warning" : "accent"
                enabled_: editorBackend.projectLoaded && !editorBackend.isScanning && !appBackend.isRunning
                onClicked: {
                    if (editorBackend.isAutoTranslating) {
                        editorBackend.cancelAutoTranslate()
                    } else {
                        autoTranslateDialog.openDialog()
                    }
                }
            }

            // Batch Replace Button
            TactileButton {
                label: localeManager.strings.editor.batch_replace_button
                variant: "ghost"
                enabled_: editorBackend.projectLoaded && !editorBackend.isScanning && !editorBackend.isAutoTranslating && !appBackend.isRunning
                onClicked: replaceDialog.openWith(editorBackend.selectedFile)
            }

            //: Export / import the translation dictionary. Translations live in
            //: the app's data directory, not the game folder, so without this a
            //: fresh copy of the game cannot be patched on another machine.
            TactileButton {
                label: localeManager.strings.editor.export_translations_button
                variant: "ghost"
                enabled_: editorBackend.projectLoaded && !editorBackend.isScanning && !editorBackend.isAutoTranslating
                onClicked: {
                    root.flushPendingEdit()
                    var res = editorBackend.exportTranslations("", true)
                    root.reportResult(res, localeManager.strings.editor.export_translations_button)
                }
            }

            TactileButton {
                label: localeManager.strings.editor.import_translations_button
                variant: "ghost"
                enabled_: editorBackend.projectLoaded && !editorBackend.isScanning && !editorBackend.isAutoTranslating
                onClicked: {
                    var res = editorBackend.importTranslations("", false)
                    root.reportResult(res, localeManager.strings.editor.import_translations_button)
                }
            }

            // Save Changes Button
            TactileButton {
                label: editorBackend.unsavedCount > 0
                    ? I18n.format(localeManager.strings.editor.save_button_with_count, {count: editorBackend.unsavedCount})
                    : localeManager.strings.editor.save_button
                variant: editorBackend.unsavedCount > 0 ? "accent" : "ghost"
                enabled_: (editorBackend.hasUnsavedChanges || root.hasPendingEdit) && !editorBackend.isScanning && !editorBackend.isAutoTranslating && !appBackend.isRunning
                onClicked: {
                    root.flushPendingEdit()
                    editorBackend.saveChanges()
                }
            }
        }

        // Auto-translate progress bar (visible only while running)
        Rectangle {
            Layout.fillWidth: true
            height: editorBackend.isAutoTranslating ? 6 : 0
            Behavior on height { NumberAnimation { duration: 200 } }
            radius: 3
            color: t ? t.border1 : "#2e2e3e"
            clip: true
            visible: height > 0

            Rectangle {
                width: parent.width * (editorBackend.autoTranslateProgress / 100)
                height: parent.height
                radius: parent.radius
                color: "#ffaa00"
                Behavior on width { NumberAnimation { duration: 300 } }
            }
        }

        // =====================================================
        // ACTIVE GAME PROJECT BAR & SELECTOR
        // =====================================================
        AppCard {
            Layout.fillWidth: true
            implicitHeight: editorBackend.isScanning ? 76 : 56
            Behavior on implicitHeight { NumberAnimation { duration: 200 } }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 12

                Rectangle {
                    width: 36; height: 36; radius: 8
                    color: editorBackend.isScanning 
                        ? Qt.rgba(255, 170, 0, 0.15)
                        : (editorBackend.projectLoaded ? Qt.rgba(124, 108, 248, 0.2) : Qt.rgba(255, 255, 255, 0.05))
                    border.color: editorBackend.isScanning
                        ? "#ffaa00"
                        : (editorBackend.projectLoaded ? Qt.rgba(124, 108, 248, 0.4) : (t ? t.border1 : "#2e2e3e"))
                    border.width: 1

                    Text {
                        id: gameIconText
                        anchors.centerIn: parent
                        text: editorBackend.isScanning ? "🔄" : (editorBackend.projectLoaded ? "🎮" : "📂")
                        font.pixelSize: 16

                        RotationAnimator on rotation {
                            running: editorBackend.isScanning
                            from: 0
                            to: 360
                            duration: 1000
                            loops: Animation.Infinite
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    RowLayout {
                        spacing: 8
                        Text {
                            text: editorBackend.projectName ? editorBackend.projectName : localeManager.strings.editor.no_game_folder_selected
                            font.pixelSize: 13
                            font.bold: true
                            color: t ? t.textPrimary : "#ffffff"
                            elide: Text.ElideRight
                        }

                        // Animated Status Badge with pulse
                        Rectangle {
                            id: statusBadge
                            height: 20
                            width: badgeText.implicitWidth + 14
                            radius: 10
                            color: editorBackend.isScanning
                                ? Qt.rgba(255, 170, 0, 0.18)
                                : (editorBackend.projectLoaded
                                    ? Qt.rgba(76, 175, 80, 0.15)
                                    : Qt.rgba(244, 67, 54, 0.15))
                            border.color: editorBackend.isScanning
                                ? "#ffaa00"
                                : (editorBackend.projectLoaded ? "#4caf50" : "#f44336")
                            border.width: 1
                            visible: editorBackend.projectPath.length > 0

                            SequentialAnimation on opacity {
                                running: editorBackend.isScanning
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.45; duration: 600; easing.type: Easing.InOutQuad }
                                NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutQuad }
                            }

                            Text {
                                id: badgeText
                                anchors.centerIn: parent
                                text: editorBackend.isScanning
                                    ? (localeManager.strings.editor.scanning_badge + getAnimatedDots())
                                    : (editorBackend.projectLoaded
                                        ? I18n.format(localeManager.strings.editor.text_count_badge, {count: editorBackend.totalProjectCount})
                                        : localeManager.strings.editor.no_data_badge)
                                font.pixelSize: 10
                                font.bold: true
                                color: parent.border.color
                            }
                        }
                    }

                    Text {
                        text: editorBackend.projectPath
                            ? editorBackend.projectPath
                            : localeManager.strings.editor.drop_placeholder
                        font.pixelSize: 11
                        color: t ? t.textMuted : "#777790"
                        elide: Text.ElideMiddle
                        Layout.fillWidth: true
                    }

                    // Live Animated Progress Bar
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        visible: editorBackend.isScanning

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: editorBackend.scanProgressText || localeManager.strings.editor.parsing_files
                                font.pixelSize: 10
                                font.bold: true
                                color: "#ffaa00"
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                            }
                            Text {
                                text: editorBackend.scanProgressCurrent + "%"
                                font.pixelSize: 10
                                font.bold: true
                                color: "#ffaa00"
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            height: 4
                            radius: 2
                            color: Qt.rgba(255, 255, 255, 0.08)
                            clip: true

                            Rectangle {
                                height: parent.height
                                radius: 2
                                width: Math.max(6, parent.width * (Math.max(editorBackend.scanProgressCurrent, 5) / 100))
                                color: "#ffaa00"
                                Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }

                                Rectangle {
                                    anchors.fill: parent
                                    color: Qt.rgba(255, 255, 255, 0.4)
                                    SequentialAnimation on opacity {
                                        loops: Animation.Infinite
                                        running: editorBackend.isScanning
                                        NumberAnimation { from: 0.1; to: 0.8; duration: 450 }
                                        NumberAnimation { from: 0.8; to: 0.1; duration: 450 }
                                    }
                                }
                            }
                        }
                    }
                }

                TactileButton {
                    label: localeManager.strings.editor.select_game_button
                    variant: "accent"
                    enabled_: !editorBackend.isScanning && !appBackend.isRunning
                    onClicked: editorBackend.selectGameFolder()
                }
            }
        }

        // =====================================================
        // TWO-TIER FILTER TOOLBAR
        // =====================================================
        AppCard {
            Layout.fillWidth: true
            implicitHeight: filterCol.implicitHeight + 16

            ColumnLayout {
                id: filterCol
                anchors { fill: parent; margins: 10 }
                spacing: 8

                // Tier 1: Category Chips
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Repeater {
                        model: editorBackend.categories
                        delegate: Rectangle {
                            height: 28
                            implicitWidth: catLabel.implicitWidth + 20
                            radius: 14
                            property bool isSelected: editorBackend.selectedCategory === modelData.key

                            color: isSelected 
                                ? (t ? t.accent : "#7c6cf8") 
                                : (catMouse.containsMouse ? (t ? t.bgHover : "#32324a") : (t ? t.bg4 : "#2a2a3a"))
                            border.color: isSelected ? "transparent" : (t ? t.border1 : "#2e2e3e")
                            border.width: 1

                            Text {
                                id: catLabel
                                anchors.centerIn: parent
                                text: localeManager.strings.editor.category_labels[modelData.key] || modelData.label
                                font.pixelSize: 11
                                font.bold: isSelected
                                color: isSelected ? "#ffffff" : (t ? t.textSecondary : "#bbbbd0")
                            }

                            MouseArea {
                                id: catMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: editorBackend.setSelectedCategory(modelData.key)
                            }
                        }
                    }
                }

                // Tier 2: Search Field, File Dropdown, and Status Filter Chips
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    // Search input
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 200
                        height: 34
                        radius: 8
                        color: t ? t.bg2 : "#1a1a24"
                        border.color: searchInput.activeFocus ? (t ? t.accent : "#7c6cf8") : (t ? t.border1 : "#2e2e3e")

                        RowLayout {
                            anchors { fill: parent; leftMargin: 8; rightMargin: 8 }
                            spacing: 6

                            Text { text: "🔍"; font.pixelSize: 12; opacity: 0.6 }

                            TextInput {
                                id: searchInput
                                Layout.fillWidth: true
                                verticalAlignment: TextInput.AlignVCenter
                                color: t ? t.textPrimary : "#ffffff"
                                font.pixelSize: 12
                                selectByMouse: true
                                text: editorBackend.searchQuery
                                onTextChanged: searchDebounce.restart()

                                Text {
                                    text: localeManager.strings.editor.search_placeholder
                                    color: t ? t.textMuted : "#666677"
                                    font.pixelSize: 12
                                    visible: !searchInput.text && !searchInput.activeFocus
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }

                            Text {
                                text: "✕"
                                font.pixelSize: 11
                                color: t ? t.textMuted : "#777790"
                                visible: searchInput.text.length > 0
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        searchInput.text = ""
                                        editorBackend.setSearchQuery("")
                                    }
                                }
                            }
                        }

                        Timer {
                            id: searchDebounce
                            interval: 200
                            repeat: false
                            onTriggered: editorBackend.setSearchQuery(searchInput.text)
                        }
                    }

                    // File ComboBox
                    ComboBox {
                        id: fileCombo
                        implicitWidth: 170
                        height: 34
                        model: editorBackend.fileList.map((f, i) => i === 0 ? localeManager.strings.editor.all_files_label : f)

                        currentIndex: {
                            var idx = editorBackend.fileList.indexOf(editorBackend.selectedFile)
                            return idx >= 0 ? idx : 0
                        }
                        onActivated: (index) => {
                            var selected = editorBackend.fileList[index]
                            editorBackend.setSelectedFile(selected === "All Files" ? "all" : selected)
                        }

                        background: Rectangle {
                            color: t ? t.bg4 : "#2a2a3a"
                            border.color: t ? t.border2 : "#3d3d55"
                            border.width: 1
                            radius: 8
                        }
                        contentItem: Text {
                            text: fileCombo.displayText
                            color: t ? t.textPrimary : "#ffffff"
                            font.pixelSize: 12
                            leftPadding: 8
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }

                    // Status Chips
                    RowLayout {
                        spacing: 4

                        Repeater {
                            model: [
                                { key: "all", label: localeManager.strings.common.all },
                                { key: "translated", label: localeManager.strings.editor.status_chip_translated + " (" + editorBackend.translatedCount + ")" },
                                { key: "modified", label: localeManager.strings.editor.status_chip_modified + " (" + editorBackend.modifiedCount + ")" },
                                { key: "warnings", label: localeManager.strings.editor.status_chip_warnings + " (" + editorBackend.warningCount + ")" },
                                { key: "untranslated", label: localeManager.strings.editor.status_chip_untranslated + " (" + editorBackend.untranslatedCount + ")" }
                            ]
                            delegate: Rectangle {
                                height: 28
                                implicitWidth: statusLabel.implicitWidth + 14
                                radius: 6
                                property bool isSelected: editorBackend.selectedStatus === modelData.key

                                color: isSelected 
                                    ? (t ? t.accentGlow : "#3a346e") 
                                    : (statusMouse.containsMouse ? (t ? t.bgHover : "#32324a") : (t ? t.bg4 : "#2a2a3a"))
                                border.color: isSelected ? (t ? t.accent : "#7c6cf8") : (t ? t.border1 : "#2e2e3e")
                                border.width: 1

                                Text {
                                    id: statusLabel
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    font.pixelSize: 11
                                    color: isSelected ? (t ? t.accentLight : "#c4b5fd") : (t ? t.textSecondary : "#bbbbd0")
                                }

                                MouseArea {
                                    id: statusMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: editorBackend.setSelectedStatus(modelData.key)
                                }
                            }
                        }
                    }
                }
            }
        }

        // =====================================================
        // MASTER: VIRTUALIZED STRING LIST (SPLIT TOP AREA)
        // =====================================================
        AppCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // Table Header
                Rectangle {
                    Layout.fillWidth: true
                    height: 32
                    color: t ? t.bg4 : "#2a2a3a"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 8

                        Text { Layout.preferredWidth: 24; text: "●"; font.pixelSize: 11; color: t ? t.textMuted : "#666677" }
                        Text { Layout.preferredWidth: 120; text: localeManager.strings.editor.col_file; font.pixelSize: 11; font.bold: true; color: t ? t.textSecondary : "#bbbbd0"; elide: Text.ElideRight }
                        Text { Layout.preferredWidth: 90; text: localeManager.strings.editor.col_category; font.pixelSize: 11; font.bold: true; color: t ? t.textSecondary : "#bbbbd0"; elide: Text.ElideRight }
                        Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: localeManager.strings.editor.col_original; font.pixelSize: 11; font.bold: true; color: t ? t.textSecondary : "#bbbbd0"; elide: Text.ElideRight }
                        Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: localeManager.strings.editor.col_translation; font.pixelSize: 11; font.bold: true; color: t ? t.textSecondary : "#bbbbd0"; elide: Text.ElideRight }
                    }
                }

                // Table Content List
                ListView {
                    id: stringListView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: editorBackend.tableModel
                    clip: true

                    //: Frozen while a row sweep is in progress, so dragging selects
                    //: instead of flicking the list. Bound rather than assigned, so
                    //: it restores itself the moment the sweep ends however it ends.
                    interactive: !root.dragSelecting

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }

                    // Informative Empty State Container
                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: 12
                        visible: editorBackend.totalCount === 0 || !editorBackend.projectLoaded
                        width: Math.min(parent.width - 40, 480)

                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: !editorBackend.projectPath
                                ? "📂"
                                : editorBackend.isScanning
                                    ? "🔄"
                                : (!editorBackend.projectLoaded
                                    ? (editorBackend.scanAttempted ? "⚠️" : "📂")
                                    : (editorBackend.totalProjectCount === 0 ? "⚠️" : "🔍"))
                            font.pixelSize: 36
                        }

                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            font.bold: true
                            font.pixelSize: 15
                            color: t ? t.textPrimary : "#ffffff"
                            text: !editorBackend.projectPath
                                ? localeManager.strings.editor.empty_no_folder_title
                                : editorBackend.isScanning
                                    ? localeManager.strings.editor.status_scanning
                                : (!editorBackend.projectLoaded && !editorBackend.scanAttempted
                                    ? (localeManager.strings.editor.empty_not_loaded_title || "Project not loaded")
                                    : (!editorBackend.projectLoaded || editorBackend.totalProjectCount === 0
                                    ? localeManager.strings.editor.empty_no_data_title
                                    : localeManager.strings.editor.empty_no_match_title)
                                    )
                        }

                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            font.pixelSize: 12
                            color: t ? t.textMuted : "#777790"
                            text: !editorBackend.projectPath
                                ? localeManager.strings.editor.empty_no_folder_desc
                                : editorBackend.isScanning
                                    ? editorBackend.scanProgressText
                                : (!editorBackend.projectLoaded && !editorBackend.scanAttempted
                                    ? (localeManager.strings.editor.empty_not_loaded_desc || "Use Load Project to scan the selected folder.")
                                    : (!editorBackend.projectLoaded || editorBackend.totalProjectCount === 0
                                    ? I18n.format(localeManager.strings.editor.empty_no_data_desc, {path: editorBackend.projectPath})
                                    : localeManager.strings.editor.empty_no_match_desc)
                                    )
                        }

                        Item { height: 4 }

                        TactileButton {
                            Layout.alignment: Qt.AlignHCenter
                            visible: !editorBackend.isScanning
                            label: (!editorBackend.projectLoaded && editorBackend.projectPath && !editorBackend.scanAttempted)
                                ? (localeManager.strings.editor.load_project_button || "Load Project")
                                : ((!editorBackend.projectLoaded || editorBackend.totalProjectCount === 0)
                                ? localeManager.strings.editor.select_game_folder_button
                                : localeManager.strings.editor.clear_filters_button
                                )
                            variant: "accent"
                            onClicked: {
                                if (!editorBackend.projectLoaded && editorBackend.projectPath && !editorBackend.scanAttempted) {
                                    editorBackend.loadProject(false)
                                } else if (!editorBackend.projectLoaded || editorBackend.totalProjectCount === 0) {
                                    editorBackend.selectGameFolder()
                                } else {
                                    if (typeof searchInput !== "undefined") {
                                        searchInput.text = ""
                                    }
                                    editorBackend.setSearchQuery("")
                                    editorBackend.setSelectedCategory("all")
                                    editorBackend.setSelectedFile("all")
                                    editorBackend.setSelectedStatus("all")
                                }
                            }
                        }
                    }

                    delegate: Rectangle {
                        id: rowDelegate
                        width: stringListView.width
                        height: 38
                        //: Exposed so the drag handler can ask itemAt() which row it is over.
                        property int rowEntryId: model.entryId
                        property bool isSelected: editorBackend.selectedEntry.id === model.entryId
                        property bool inMultiSelection: root.isRowSelected(model.entryId)

                        color: inMultiSelection
                            ? (t ? t.accentGlow : "#38326b")
                            : (isSelected
                                ? (t ? t.accentGlow : "#38326b")
                                : (rowMouse.containsMouse ? (t ? t.bgHover : "#28283a") : "transparent"))

                        // A left edge marker distinguishes a multi-row pick from the
                        // single row currently open in the editor panes.
                        Rectangle {
                            visible: rowDelegate.inMultiSelection
                            width: 3
                            height: parent.height
                            color: t ? t.accent : "#7c6cf8"
                        }

                        Rectangle {
                            width: parent.width; height: 1
                            color: t ? t.border1 : "#2e2e3e"
                            anchors.bottom: parent.bottom
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 8

                            // Status Dot
                            Rectangle {
                                Layout.preferredWidth: 24
                                Layout.alignment: Qt.AlignVCenter
                                width: 8; height: 8; radius: 4
                                color: {
                                    if (model.hasWarning) return "#f59e0b" // warning orange
                                    if (model.isModified) return "#38bdf8" // modified cyan
                                    if (model.translatedText && model.translatedText !== model.originalText) return "#10b981" // translated green
                                    return "#6b7280" // untranslated grey
                                }
                            }

                            // File Name
                            Text {
                                Layout.preferredWidth: 120
                                text: model.fileName
                                font.pixelSize: 11
                                color: t ? t.textSecondary : "#bbbbd0"
                                elide: Text.ElideMiddle
                            }

                            // Category Badge
                            Rectangle {
                                Layout.preferredWidth: 90
                                Layout.alignment: Qt.AlignVCenter
                                height: 20; radius: 4
                                color: t ? t.bg4 : "#2a2a3a"
                                Text {
                                    anchors.centerIn: parent
                                    text: (localeManager.strings.editor.category_labels && localeManager.strings.editor.category_labels[model.category]) || model.categoryLabel
                                    font.pixelSize: 10
                                    color: t ? t.textMuted : "#888899"
                                    elide: Text.ElideRight
                                }
                            }

                            // Original Text Preview
                            Text {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                text: model.originalText.replace(/\n/g, " ↵ ")
                                font.pixelSize: 12
                                color: t ? t.textPrimary : "#ffffff"
                                elide: Text.ElideRight
                            }

                            // Translated Text Preview
                            Text {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                text: model.translatedText.replace(/\n/g, " ↵ ")
                                font.pixelSize: 12
                                color: model.isModified 
                                    ? (t ? t.accentLight : "#c4b5fd") 
                                    : (t ? t.textSecondary : "#bbbbd0")
                                font.bold: model.isModified
                                elide: Text.ElideRight
                            }
                        }

                        MouseArea {
                            id: rowMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            acceptedButtons: Qt.LeftButton | Qt.RightButton

                            //: Without this the ListView's Flickable takes the mouse
                            //: grab once the drag passes its threshold: the list
                            //: scrolls under the cursor AND this MouseArea stops
                            //: receiving events, so onReleased never fires and the
                            //: sweep stayed armed after the button came up.
                            preventStealing: true

                            //: Windows list-view semantics: plain click selects one
                            //: row, Ctrl+click toggles, Shift+click extends, and a
                            //: press-and-drag sweeps a range. The row is opened in
                            //: the editor on release, not on press, so dragging out
                            //: of a row does not also load it.
                            onPressed: (mouse) => {
                                if (mouse.button === Qt.RightButton) {
                                    root.contextEntryId = model.entryId
                                    if (!root.isRowSelected(model.entryId))
                                        root.clearSelection()
                                    translateWithMenu.popup()
                                    return
                                }

                                root.contextEntryId = model.entryId

                                if (mouse.modifiers & Qt.ControlModifier) {
                                    root.toggleSelection(model.entryId)
                                    root.dragAnchorIndex = index
                                    root.dragSelecting = false
                                    return
                                }
                                if (mouse.modifiers & Qt.ShiftModifier) {
                                    if (root.dragAnchorIndex < 0)
                                        root.dragAnchorIndex = index
                                    root.selectIndexRange(root.dragAnchorIndex, index)
                                    root.dragSelecting = false
                                    return
                                }

                                root.dragAnchorIndex = index
                                root.dragSelecting = true
                                root.dragMoved = false
                                root.selectedIds = [model.entryId]
                            }

                            onPositionChanged: (mouse) => {
                                // pressed guards the case where the button is up but
                                // a stray move still reaches this handler.
                                if (!pressed || !root.dragSelecting || root.dragAnchorIndex < 0)
                                    return
                                var pt = mapToItem(stringListView, mouse.x, mouse.y)
                                var idx = root.rowIndexAt(pt.x, pt.y)

                                // Past the top or bottom edge: extend to the end and
                                // keep scrolling, the way a real list view does.
                                if (idx < 0) {
                                    if (pt.y < 0) {
                                        stringListView.contentY = Math.max(
                                            0, stringListView.contentY - 12)
                                        idx = root.rowIndexAt(pt.x, 1)
                                    } else if (pt.y > stringListView.height) {
                                        stringListView.contentY = Math.min(
                                            Math.max(0, stringListView.contentHeight - stringListView.height),
                                            stringListView.contentY + 12)
                                        idx = root.rowIndexAt(pt.x, stringListView.height - 1)
                                    }
                                }
                                if (idx < 0)
                                    return
                                root.dragMoved = true
                                root.selectIndexRange(root.dragAnchorIndex, idx)
                            }

                            onReleased: (mouse) => {
                                if (mouse.button !== Qt.LeftButton)
                                    return
                                var swept = root.dragSelecting && root.dragMoved
                                root.dragSelecting = false
                                root.dragMoved = false
                                if (swept)
                                    return   // keep the swept range
                                // A click that never moved: open this row and drop
                                // the multi-selection.
                                root.clearSelection()
                                root.selectRow(model.entryId)
                            }

                            //: The grab can still be lost (window deactivates, a
                            //: dialog opens). Disarm here too, or the next mouse
                            //: move would carry on extending a selection the user
                            //: already finished.
                            onCanceled: {
                                root.dragSelecting = false
                                root.dragMoved = false
                            }
                        }
                    }
                }

                // =====================================================
                // PAGINATION CONTROLLER
                // =====================================================
                Rectangle {
                    Layout.fillWidth: true
                    height: 38
                    color: t ? t.bg4 : "#252535"
                    border.color: t ? t.border1 : "#2e2e3e"
                    border.width: 1

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 8

                        Text {
                            text: I18n.format(localeManager.strings.editor.pagination_label, {count: editorBackend.totalCount, page: editorBackend.currentPage, total: editorBackend.totalPages})
                            font.pixelSize: 11
                            color: t ? t.textMuted : "#888899"
                        }

                        Item { Layout.fillWidth: true }

                        // First Page
                        TactileButton {
                            label: "⏮"
                            variant: "ghost"
                            implicitHeight: 28
                            implicitWidth: 32
                            enabled_: editorBackend.currentPage > 1
                            onClicked: root.changePage(1)
                        }

                        // Prev Page
                        TactileButton {
                            label: "◀"
                            variant: "ghost"
                            implicitHeight: 28
                            implicitWidth: 32
                            enabled_: editorBackend.currentPage > 1
                            onClicked: root.changePage(editorBackend.currentPage - 1)
                        }

                        Text {
                            text: editorBackend.currentPage
                            font.pixelSize: 12
                            font.bold: true
                            color: t ? t.accent : "#7c6cf8"
                            leftPadding: 6; rightPadding: 6
                        }

                        // Next Page
                        TactileButton {
                            label: "▶"
                            variant: "ghost"
                            implicitHeight: 28
                            implicitWidth: 32
                            enabled_: editorBackend.currentPage < editorBackend.totalPages
                            onClicked: root.changePage(editorBackend.currentPage + 1)
                        }

                        // Last Page
                        TactileButton {
                            label: "⏭"
                            variant: "ghost"
                            implicitHeight: 28
                            implicitWidth: 32
                            enabled_: editorBackend.currentPage < editorBackend.totalPages
                            onClicked: root.changePage(editorBackend.totalPages)
                        }

                        // Page Size
                        ComboBox {
                            implicitWidth: 90
                            height: 28
                            model: localeManager.strings.editor.page_size_options
                            currentIndex: editorBackend.pageSize === 50 ? 0 : (editorBackend.pageSize === 100 ? 1 : 2)
                            onActivated: (idx) => {
                                var sizes = [50, 100, 200]
                                editorBackend.setPageSize(sizes[idx])
                            }
                            background: Rectangle {
                                color: t ? t.bg3 : "#22222f"
                                border.color: t ? t.border1 : "#2e2e3e"
                                radius: 6
                            }
                            contentItem: Text {
                                text: parent.displayText
                                color: t ? t.textPrimary : "#ffffff"
                                font.pixelSize: 11
                                leftPadding: 6
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }
            }
        }

        // =====================================================
        // DETAIL: MULTI-LINE EDITING DRAWER (BOTTOM SECTION)
        // =====================================================
        AppCard {
            id: detailCard
            Layout.fillWidth: true
            height: 235
            visible: editorBackend.selectedEntry.id !== undefined && editorBackend.selectedEntry.id > 0
            property int liveLineCount: (typeof transTextArea !== "undefined" && transTextArea.text) ? ((transTextArea.text.match(/\n/g) || []).length + 1) : 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                // Detail Top Info Row
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: (editorBackend.selectedEntry.file_name || "") + " ➔ " + (editorBackend.selectedEntry.json_path || "")
                        font.pixelSize: 11
                        font.bold: true
                        color: t ? t.textSecondary : "#bbbbd0"
                    }

                    Item { Layout.fillWidth: true }

                    // Line Counter
                    Rectangle {
                        height: 20
                        implicitWidth: lineCountText.implicitWidth + 12
                        radius: 4
                        color: (detailCard.liveLineCount > 4) ? "#ef4444" : (t ? t.bg4 : "#2a2a3a")
                        Text {
                            id: lineCountText
                            anchors.centerIn: parent
                            text: I18n.format(localeManager.strings.editor.line_counter, {count: detailCard.liveLineCount})
                            font.pixelSize: 10
                            font.bold: true
                            color: (detailCard.liveLineCount > 4) ? "#ffffff" : (t ? t.textMuted : "#888899")
                        }
                    }

                    // Warning Badge
                    Rectangle {
                        height: 20
                        implicitWidth: warnText.implicitWidth + 12
                        radius: 4
                        color: "#f59e0b"
                        visible: Boolean(editorBackend.selectedEntry.has_warning)
                        Text {
                            id: warnText
                            anchors.centerIn: parent
                            text: "⚠️ " + (editorBackend.selectedEntry.warning_msg || localeManager.strings.editor.escape_code_warning_fallback)
                            font.pixelSize: 10
                            font.bold: true
                            color: "#ffffff"
                        }
                    }
                }

                // Pre-Context (Previous line if dialogue sequence)
                Text {
                    text: localeManager.strings.editor.prev_context_prefix + (editorBackend.selectedEntry.prev_context || "").replace(/\n/g, " ")
                    font.pixelSize: 11
                    font.italic: true
                    color: t ? t.textMuted : "#666677"
                    visible: Boolean(editorBackend.selectedEntry.prev_context)
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                // Clickable Code Chips (Full width above dual editor panes)
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    visible: (editorBackend.selectedEntry.escape_codes || []).length > 0

                    Text {
                        text: localeManager.strings.editor.add_code_label
                        font.pixelSize: 10
                        color: t ? t.textMuted : "#666677"
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 4

                        Repeater {
                            model: editorBackend.selectedEntry.escape_codes || []
                            delegate: Rectangle {
                                height: 18
                                implicitWidth: chipText.implicitWidth + 8
                                radius: 3
                                color: t ? t.bg4 : "#2a2a3a"
                                border.color: t ? t.accent : "#7c6cf8"
                                border.width: 1

                                Text {
                                    id: chipText
                                    anchors.centerIn: parent
                                    text: modelData
                                    font.pixelSize: 9
                                    font.bold: true
                                    color: t ? t.accentLight : "#c4b5fd"
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        var pos = transTextArea.cursorPosition
                                        transTextArea.insert(pos, modelData)
                                        transTextArea.forceActiveFocus()
                                    }
                                }
                            }
                        }
                    }
                }

                // Dual Editor Panes (Original vs Translated)
                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 12

                    // Original Pane (Read-Only)
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.fillHeight: true
                        spacing: 4

                        // Original Text Display
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: t ? t.bg2 : "#1a1a24"
                            border.color: t ? t.border1 : "#2e2e3e"
                            radius: 8

                            ScrollView {
                                anchors.fill: parent
                                anchors.margins: 6
                                TextArea {
                                    text: editorBackend.selectedEntry.original_text || ""
                                    readOnly: true
                                    wrapMode: Text.Wrap
                                    color: t ? t.textSecondary : "#bbbbd0"
                                    font.pixelSize: 12
                                    selectByMouse: true
                                }
                            }
                        }
                    }

                    // Translated Pane (Editable)
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.fillHeight: true
                        spacing: 4

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: t ? t.bg2 : "#1a1a24"
                            border.color: transTextArea.activeFocus ? (t ? t.accent : "#7c6cf8") : (t ? t.border1 : "#2e2e3e")
                            radius: 8

                            ScrollView {
                                anchors.fill: parent
                                anchors.margins: 6
                                TextArea {
                                    id: transTextArea
                                    //: True only once the person has typed in this
                                    //: box since the row was loaded. Anything the
                                    //: backend writes (a translation landing, a
                                    //: revert, a row change) resets it, so the
                                    //: editor never writes its buffer back over a
                                    //: value it did not author.
                                    property bool userEdited: false

                                    text: editorBackend.selectedEntry.translated_text || ""
                                    onTextChanged: {
                                        if (activeFocus)
                                            userEdited = true
                                    }

                                    wrapMode: Text.Wrap
                                    color: t ? t.textPrimary : "#ffffff"
                                    font.pixelSize: 12
                                    selectByMouse: true

                                    Connections {
                                        target: editorBackend
                                        function onSelectedEntryChanged() {
                                            transTextArea.userEdited = false
                                        }
                                    }

                                    Keys.onPressed: (event) => {
                                        if (event.key === Qt.Key_Return && (event.modifiers & Qt.ControlModifier)) {
                                            editorBackend.updateSelectedTranslation(transTextArea.text)
                                            transTextArea.userEdited = false
                                            event.accepted = true
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Next Context (Succeeding line if dialogue sequence)
                Text {
                    text: localeManager.strings.editor.next_context_prefix + (editorBackend.selectedEntry.next_context || "").replace(/\n/g, " ")
                    font.pixelSize: 11
                    font.italic: true
                    color: t ? t.textMuted : "#666677"
                    visible: Boolean(editorBackend.selectedEntry.next_context)
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                // Detail Bottom Action Buttons
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: localeManager.strings.editor.ctrl_enter_tip
                        font.pixelSize: 10
                        color: t ? t.textMuted : "#666677"
                    }

                    Item { Layout.fillWidth: true }

                    // Revert Entry Button
                    TactileButton {
                        label: localeManager.strings.editor.revert_button
                        variant: "ghost"
                        implicitHeight: 26
                        onClicked: {
                            editorBackend.revertSelectedEntry()
                            transTextArea.text = editorBackend.selectedEntry.translated_text || ""
                            transTextArea.userEdited = false
                        }
                    }

                    // Apply Translation Button
                    TactileButton {
                        label: localeManager.strings.editor.apply_button
                        variant: "accent"
                        implicitHeight: 26
                        onClicked: {
                            editorBackend.updateSelectedTranslation(transTextArea.text)
                            transTextArea.userEdited = false
                        }
                    }
                }
            }
        }
    }
}
