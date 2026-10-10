import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Controls.Material 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    property var themeObj: null
    property var t: themeObj

    //: Which provider's credentials the AI card is showing. Only one set of
    //: fields is visible at a time; all of them stay bound to their own
    //: settings, so switching tabs never discards anything.
    property int providerTab: 0

    function providerTabForEngine(engineName) {
        switch (engineName) {
            case "openai":
            case "deepseek":        return 0
            case "gemini":          return 1
            case "hy_mt2":          return 2
            case "local_llm":
            case "ollama":
            case "local":
            case "lmstudio":        return 3
            case "deepl":
            case "libretranslate":  return 4
            default:                return root.providerTab
        }
    }

    // Open on whichever provider is actually in use, rather than always OpenAI.
    Component.onCompleted: {
        if (typeof settingsBackend !== "undefined") {
            root.lastKnownEngine = settingsBackend.engine
            root.providerTab = providerTabForEngine(settingsBackend.engine)
        }
    }
    //: settingsChanged is a single shared signal for every setting, so follow the
    //: engine only when the engine itself actually changed. Otherwise typing in a
    //: field would snap the user back off the provider they were inspecting.
    property string lastKnownEngine: ""
    Connections {
        target: typeof settingsBackend !== "undefined" ? settingsBackend : null
        function onSettingsChanged() {
            if (settingsBackend.engine !== root.lastKnownEngine) {
                root.lastKnownEngine = settingsBackend.engine
                root.providerTab = providerTabForEngine(settingsBackend.engine)
            }
        }
    }

    // ---- Reusable Card ----
    component AppCard: Rectangle {
        color: t ? t.bg3 : "#22222f"
        border.color: t ? t.border1 : "#2e2e3e"
        border.width: 1; radius: 12
    }

    // ---- Input Field ----
    component InputField: ColumnLayout {
        id: inputComp
        property string label: ""
        property string text: ""
        property string placeholder: ""
        property bool isPassword: false
        signal editingFinished(string newText)
        spacing: t ? t.spaceXS : 4
        Layout.fillWidth: true

        Text {
            text: inputComp.label
            font.pixelSize: 11
            font.bold: true
            color: t ? t.textSecondary : "#9090b8"
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 34
            radius: 8
            color: t ? t.bg4 : "#2a2a3a"
            border.color: txtInput.activeFocus ? (t ? t.accent : "#7c6cf8") : (t ? t.border2 : "#3d3d55")
            border.width: 1

            TextField {
                id: txtInput
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                text: inputComp.text
                placeholderText: inputComp.placeholder
                echoMode: inputComp.isPassword ? TextInput.Password : TextInput.Normal
                color: t ? t.textPrimary : "#f0f0ff"
                placeholderTextColor: t ? t.textMuted : "#55556a"
                font.pixelSize: t ? t.fontSizeSM : 12
                background: Item {}
                onEditingFinished: inputComp.editingFinished(text)
            }
        }
    }

    // ---- Multi-line Prompt Field ----
    component PromptField: ColumnLayout {
        id: promptComp
        property string label: ""
        property string text: ""
        property string placeholder: ""
        property int minHeight: 160
        signal editingFinished(string newText)
        spacing: t ? t.spaceXS : 4
        Layout.fillWidth: true

        Text {
            text: promptComp.label
            font.pixelSize: 11
            font.bold: true
            color: t ? t.textSecondary : "#9090b8"
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: promptComp.minHeight
            radius: 8
            color: t ? t.bg4 : "#2a2a3a"
            border.color: promptArea.activeFocus ? (t ? t.accent : "#7c6cf8") : (t ? t.border2 : "#3d3d55")
            border.width: 1

            ScrollView {
                anchors.fill: parent
                anchors.margins: 8
                clip: true

                TextArea {
                    id: promptArea
                    text: promptComp.text
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    color: t ? t.textPrimary : "#f0f0ff"
                    font.pixelSize: t ? t.fontSizeSM : 12
                    font.family: "Consolas, Menlo, monospace"
                    background: Item {}
                    onActiveFocusChanged: {
                        if (!activeFocus) promptComp.editingFinished(text)
                    }

                    // Explicit hint instead of placeholderText: it must disappear
                    // the moment there is any content, including content restored
                    // from settings rather than typed.
                    Text {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.right: parent.right
                        visible: promptArea.text.length === 0 && !promptArea.activeFocus
                        text: promptComp.placeholder
                        wrapMode: Text.Wrap
                        color: t ? t.textMuted : "#55556a"
                        font.pixelSize: t ? t.fontSizeSM : 12
                        font.family: promptArea.font.family
                    }
                }
            }
        }
    }

    // ---- Styled Slider Row ----
    component StyledSlider: RowLayout {
        id: sliderRow
        property string label: ""
        property real from: 0; property real to: 100; property real step: 1
        property real value: 0
        property string unit: ""
        //: When true the value box is a text field, so a precise number can be
        //: typed instead of dragged to (large ranges are hard to hit exactly).
        property bool editable: false
        signal moved(real val)
        spacing: 16; Layout.fillWidth: true

        Text {
            text: sliderRow.label
            font.pixelSize: t ? t.fontSizeMD : 13; font.bold: true; color: t ? t.textPrimary : "#f0f0ff"
            Layout.preferredWidth: 230
        }
        Slider {
            Layout.preferredWidth: 260
            from: sliderRow.from; to: sliderRow.to; stepSize: sliderRow.step
            value: sliderRow.value
            Material.theme: Material.Dark; Material.accent: t ? t.accent : "#7c6cf8"
            onMoved: sliderRow.moved(value)
        }
        TextField {
            visible: sliderRow.editable
            implicitWidth: 90; implicitHeight: 32
            horizontalAlignment: TextInput.AlignHCenter
            font.pixelSize: 12; font.bold: true
            color: t ? t.accentLight : "#a89bf9"
            selectByMouse: true
            //: Digits only. Not IntValidator: Qt treats an over-range number like
            //: 999999 as "Intermediate", lets it be typed, and then never emits
            //: editingFinished for it - so the box showed 999999 while nothing
            //: was saved. Range is enforced in commit() instead.
            validator: RegularExpressionValidator { regularExpression: /^[0-9]{0,7}$/ }
            text: Math.round(sliderRow.value)
            Material.theme: Material.Dark; Material.accent: t ? t.accent : "#7c6cf8"
            function commit() {
                var n = parseInt(text, 10)
                if (isNaN(n)) n = Math.round(sliderRow.value)
                n = Math.max(sliderRow.from, Math.min(sliderRow.to, n))
                sliderRow.moved(n)
                // Re-bind so the box shows the clamped, saved value and keeps
                // following the slider afterwards.
                text = Qt.binding(function() { return Math.round(sliderRow.value) })
            }
            onEditingFinished: commit()
            onActiveFocusChanged: if (!activeFocus) commit()
        }
        Rectangle {
            visible: !sliderRow.editable
            implicitWidth: 68; implicitHeight: 28; radius: 6
            color: t ? t.bg4 : "#2a2a3a"
            border.color: t ? t.border2 : "#3d3d55"; border.width: 1
            Text {
                anchors.centerIn: parent
                text: Math.round(sliderRow.value) + (sliderRow.unit ? (" " + sliderRow.unit) : "")
                font.pixelSize: 12; font.bold: true
                color: t ? t.accentLight : "#a89bf9"
            }
        }
        Item { Layout.fillWidth: true }
    }

    // ---- Toggle Row ----
    component ToggleRow: RowLayout {
        id: toggleRowComp
        property string label: ""
        property string desc: ""
        property bool checked: false
        signal toggled(bool val)
        spacing: t ? t.spaceMD : 12; Layout.fillWidth: true

        ColumnLayout {
            Layout.fillWidth: true; spacing: 2
            Text { text: toggleRowComp.label; font.pixelSize: t ? t.fontSizeMD : 13; color: t ? t.textPrimary : "#f0f0ff" }
            Text { text: toggleRowComp.desc; font.pixelSize: 11; color: t ? t.textSecondary : "#9090b8"; opacity: 0.85; visible: text.length > 0 }
        }

        Rectangle {
            width: 42; height: 24; radius: 12
            color: toggleRowComp.checked ? (t ? t.accent : "#7c6cf8") : (t ? t.bg4 : "#2a2a3a")
            border.color: toggleRowComp.checked ? "transparent" : (t ? t.border2 : "#3d3d55")
            border.width: 1
            Behavior on color { ColorAnimation { duration: t ? t.animFast : 130 } }
            Rectangle {
                width: 18; height: 18; radius: 9; anchors.verticalCenter: parent.verticalCenter
                x: toggleRowComp.checked ? parent.width - width - 3 : 3
                color: toggleRowComp.checked ? "white" : (t ? t.textMuted : "#55556a")
                Behavior on x     { NumberAnimation { duration: t ? t.animFast : 130; easing.type: Easing.OutQuad } }
                Behavior on color { ColorAnimation   { duration: t ? t.animFast : 130 } }
            }
            MouseArea {
                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                onClicked: { toggleRowComp.checked = !toggleRowComp.checked; toggleRowComp.toggled(toggleRowComp.checked) }
            }
        }
    }

    // ---- Styled ComboBox (mirrors HomeTab.qml's StyledCombo) ----
    component StyledCombo: ComboBox {
        id: styledCombo
        Material.theme: Material.Dark
        implicitHeight: 36
        background: Rectangle {
            color: styledCombo.popup.visible ? (t ? t.bg4 : "#2a2a3a") : (styledCombo.hovered ? (t ? t.bgHover : "#32324a") : (t ? t.bg4 : "#22222f"))
            border.color: styledCombo.popup.visible ? (t ? t.accent : "#7c6cf8") : (t ? t.border2 : "#3d3d55")
            border.width: 1; radius: 8
            Behavior on color { ColorAnimation { duration: t ? t.animFast : 130 } }
            Behavior on border.color { ColorAnimation { duration: t ? t.animFast : 130 } }
        }
        contentItem: Text {
            leftPadding: 12; rightPadding: styledCombo.indicator.width + 8
            text: styledCombo.displayText; color: t ? t.textPrimary : "#f0f0ff"
            font.pixelSize: t ? t.fontSizeMD : 13; verticalAlignment: Text.AlignVCenter
        }
        indicator: Text {
            x: styledCombo.width - width - 10; y: (styledCombo.height - height) / 2
            text: "▾"; color: t ? t.textSecondary : "#9090b8"; font.pixelSize: 11
            rotation: styledCombo.popup.visible ? 180 : 0
            Behavior on rotation { NumberAnimation { duration: 150 } }
        }
        popup: Popup {
            y: styledCombo.height + 4; width: styledCombo.width
            implicitHeight: contentItem.implicitHeight; padding: 4
            background: Rectangle {
                color: t ? t.bg3 : "#22222f"; border.color: t ? t.border2 : "#3d3d55"
                border.width: 1; radius: t ? t.radiusMD : 10
            }
            contentItem: ListView {
                clip: true; implicitHeight: Math.min(contentHeight, 280)
                model: styledCombo.delegateModel
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            }
        }
        delegate: ItemDelegate {
            width: styledCombo.width - 8
            highlighted: styledCombo.highlightedIndex === index
            contentItem: Text {
                text: modelData; font.pixelSize: t ? t.fontSizeMD : 13; leftPadding: 8
                color: highlighted ? "white" : (t ? t.textSecondary : "#9090b8")
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                color: highlighted ? (t ? t.accentGlow : "#1c1c30") : "transparent"; radius: t ? t.radiusSM : 6
            }
        }
    }

    readonly property var uiLangList: localeManager.availableLanguages()
    readonly property var uiLangCodes: root.uiLangList.map(function(l) { return l.code })
    readonly property var uiLangNames: root.uiLangList.map(function(l) { return l.name })
    function uiLangCodeToIndex(code) {
        for (var i = 0; i < root.uiLangCodes.length; i++)
            if (root.uiLangCodes[i] === code) return i
        return 0
    }

    // =========================================================
    ScrollView {
        id: scrollView
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: scrollView.availableWidth
            spacing: 0

            // Header
            Rectangle {
                Layout.fillWidth: true; implicitHeight: 68
                color: t ? t.bg2 : "#1a1a24"
                Rectangle { width: parent.width; height: 1; anchors.bottom: parent.bottom; color: t ? t.border1 : "#2e2e3e" }
                RowLayout {
                    anchors { fill: parent; leftMargin: 28 }
                    Text { text: localeManager.strings.settings.title; font.pixelSize: 20; font.bold: true; color: t ? t.textPrimary : "#f0f0ff" }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true; Layout.margins: 28; spacing: t ? t.spaceLG : 16

                // ===== CARD: Interface Language =====
                AppCard {
                    Layout.fillWidth: true
                    implicitHeight: langCardCol.implicitHeight + 36
                    ColumnLayout {
                        id: langCardCol
                        anchors { fill: parent; margins: 20 }
                        spacing: 14
                        RowLayout {
                            spacing: t ? t.spaceSM : 8
                            Rectangle { width: 4; height: 16; radius: 2; color: t ? t.accent : "#7c6cf8" }
                            Text { text: localeManager.strings.settings.ui_language_card_title; font.pixelSize: 14; font.bold: true; color: t ? t.textPrimary : "#f0f0ff" }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: t ? t.border1 : "#2e2e3e" }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 16
                            Text {
                                text: localeManager.strings.settings.ui_language_desc
                                font.pixelSize: t ? t.fontSizeSM : 12; color: t ? t.textSecondary : "#9090b8"
                                wrapMode: Text.WordWrap; Layout.fillWidth: true
                            }
                            StyledCombo {
                                id: uiLangCombo
                                Layout.preferredWidth: 260
                                model: root.uiLangNames
                                currentIndex: root.uiLangCodeToIndex(localeManager.currentLanguage)
                                onActivated: (index) => { localeManager.setLanguage(root.uiLangCodes[index]) }
                            }
                        }
                    }
                }

                // ===== CARD: Engine & Performance =====
                AppCard {
                    Layout.fillWidth: true
                    implicitHeight: engCardCol.implicitHeight + 40
                    ColumnLayout {
                        id: engCardCol
                        anchors { fill: parent; margins: 20 }
                        spacing: t ? t.spaceLG : 16
                        RowLayout {
                            spacing: t ? t.spaceSM : 8
                            Rectangle { width: 4; height: 16; radius: 2; color: t ? t.accent : "#7c6cf8" }
                            Text { text: localeManager.strings.settings.card_engine_title; font.pixelSize: 14; font.bold: true; color: t ? t.textPrimary : "#f0f0ff" }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: t ? t.border1 : "#2e2e3e" }
                        StyledSlider {
                            label: localeManager.strings.settings.batch_size_label; from: 1; to: 100; step: 1
                            value: settingsBackend.batchSize
                            onMoved: (val) => { settingsBackend.batchSize = Math.round(val) }
                        }
                        StyledSlider {
                            label: localeManager.strings.settings.concurrent_requests_label; from: 1; to: 20; step: 1
                            value: settingsBackend.concurrentRequests
                            onMoved: (val) => { settingsBackend.concurrentRequests = Math.round(val) }
                        }
                        StyledSlider {
                            label: localeManager.strings.settings.max_tokens_label
                            from: 0; to: 100000; step: 512
                            editable: true
                            value: settingsBackend.localLlmMaxTokens
                            onMoved: (val) => { settingsBackend.localLlmMaxTokens = Math.round(val) }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: settingsBackend.localLlmMaxTokens === 0
                                  ? localeManager.strings.settings.max_tokens_auto_hint
                                  : localeManager.strings.settings.max_tokens_manual_hint
                            wrapMode: Text.Wrap
                            font.pixelSize: 11
                            color: t ? t.textMuted : "#55556a"
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: t ? t.border1 : "#2e2e3e" }

                        ToggleRow {
                            label: localeManager.strings.settings.glossary_autofill_label
                            desc: localeManager.strings.settings.glossary_autofill_desc
                            checked: settingsBackend.glossaryAutofill
                            onToggled: (val) => { settingsBackend.glossaryAutofill = val }
                        }

                        PromptField {
                            label: localeManager.strings.settings.skip_regex_label
                            text: settingsBackend.skipRegex
                            placeholder: localeManager.strings.settings.skip_regex_placeholder
                            minHeight: 110
                            onEditingFinished: (newText) => { settingsBackend.skipRegex = newText }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: localeManager.strings.settings.skip_regex_desc
                            wrapMode: Text.Wrap
                            font.pixelSize: 11
                            color: t ? t.textMuted : "#55556a"
                        }

                        Text {
                            Layout.fillWidth: true
                            text: localeManager.strings.settings.throughput_hint
                            wrapMode: Text.Wrap
                            font.pixelSize: 11
                            color: t ? t.textMuted : "#55556a"
                        }

                        ToggleRow {
                            label: localeManager.strings.settings.multi_endpoint_label
                            desc: localeManager.strings.settings.multi_endpoint_desc
                            checked: settingsBackend.useMultiEndpoint
                            onToggled: (val) => { settingsBackend.useMultiEndpoint = val }
                        }
                        ToggleRow {
                            label: localeManager.strings.settings.lingva_fallback_label
                            desc: localeManager.strings.settings.lingva_fallback_desc
                            checked: settingsBackend.enableLingvaFallback
                            onToggled: (val) => { settingsBackend.enableLingvaFallback = val }
                        }
                    }
                }

                // ===== CARD: AI & Provider Credentials =====
                AppCard {
                    Layout.fillWidth: true
                    implicitHeight: aiCardCol.implicitHeight + 40
                    ColumnLayout {
                        id: aiCardCol
                        anchors { fill: parent; margins: 20 }
                        spacing: t ? t.spaceLG : 16
                        RowLayout {
                            spacing: t ? t.spaceSM : 8
                            Rectangle { width: 4; height: 16; radius: 2; color: t ? t.accentLight : "#a89bf9" }
                            Text { text: localeManager.strings.settings.card_ai_title; font.pixelSize: 14; font.bold: true; color: t ? t.textPrimary : "#f0f0ff" }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: t ? t.border1 : "#2e2e3e" }

                        Text {
                            text: localeManager.strings.settings.provider_select_label
                            font.pixelSize: 11; font.bold: true
                            color: t ? t.textSecondary : "#9090b8"
                        }
                        StyledCombo {
                            Layout.fillWidth: true
                            model: [
                                localeManager.strings.settings.section_openai,
                                localeManager.strings.settings.section_gemini,
                                localeManager.strings.settings.section_hy_mt2,
                                localeManager.strings.settings.section_local_llm,
                                localeManager.strings.settings.section_deepl + " / " + localeManager.strings.settings.section_libretranslate
                            ]
                            currentIndex: root.providerTab
                            onActivated: (index) => { root.providerTab = index }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: t ? t.border1 : "#2e2e3e" }
                        ColumnLayout {
                            id: provOpenAI
                            Layout.fillWidth: true
                            spacing: t ? t.spaceMD : 12
                            visible: root.providerTab === 0
                            // OpenAI / DeepSeek
                            Text { text: localeManager.strings.settings.section_openai; font.pixelSize: t ? t.fontSizeSM : 12; font.bold: true; color: t ? t.accentLight : "#a89bf9" }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: t ? t.spaceMD : 12
                                InputField {
                                    label: localeManager.strings.settings.api_key_label
                                    text: settingsBackend.openaiApiKey
                                    placeholder: "sk-..."
                                    isPassword: true
                                    onEditingFinished: (newText) => { settingsBackend.openaiApiKey = newText }
                                }
                                InputField {
                                    label: localeManager.strings.settings.model_name_label
                                    text: settingsBackend.openaiModel
                                    placeholder: "gpt-4o-mini"
                                    onEditingFinished: (newText) => { settingsBackend.openaiModel = newText }
                                }
                            }
                            InputField {
                                label: localeManager.strings.settings.openai_base_url_label
                                text: settingsBackend.openaiBaseUrl
                                placeholder: "https://api.openai.com/v1"
                                onEditingFinished: (newText) => { settingsBackend.openaiBaseUrl = newText }
                            }
                        }
                        ColumnLayout {
                            id: provGemini
                            Layout.fillWidth: true
                            spacing: t ? t.spaceMD : 12
                            visible: root.providerTab === 1
                            // Google Gemini
                            Text { text: localeManager.strings.settings.section_gemini; font.pixelSize: t ? t.fontSizeSM : 12; font.bold: true; color: t ? t.accentLight : "#a89bf9" }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: t ? t.spaceMD : 12
                                InputField {
                                    label: localeManager.strings.settings.api_key_label
                                    text: settingsBackend.geminiApiKey
                                    placeholder: "AIzaSy..."
                                    isPassword: true
                                    onEditingFinished: (newText) => { settingsBackend.geminiApiKey = newText }
                                }
                                InputField {
                                    label: localeManager.strings.settings.model_name_label
                                    text: settingsBackend.geminiModel
                                    placeholder: "gemini-2.0-flash"
                                    onEditingFinished: (newText) => { settingsBackend.geminiModel = newText }
                                }
                            }
                        }
                        ColumnLayout {
                            id: provHyMt2
                            Layout.fillWidth: true
                            spacing: t ? t.spaceMD : 12
                            visible: root.providerTab === 2
                            // Local LLM
                            Text { text: "Hy-MT2 (Local)"; font.pixelSize: t ? t.fontSizeSM : 12; font.bold: true; color: t ? t.accentLight : "#a89bf9" }
                            Component.onCompleted: settingsBackend.refreshHyMt2Models()
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: t ? t.spaceMD : 12
                                InputField {
                                    label: localeManager.strings.settings.base_url_label
                                    text: settingsBackend.hyMt2Url
                                    placeholder: "http://127.0.0.1:1234/v1"
                                    onEditingFinished: (newText) => { settingsBackend.hyMt2Url = newText }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                StyledCombo {
                                    Layout.fillWidth: true
                                    model: [localeManager.strings.settings.model_name_label].concat(settingsBackend.hyMt2Models)
                                    currentIndex: settingsBackend.hyMt2Models.indexOf(settingsBackend.hyMt2Model) + 1
                                    onActivated: (index) => { settingsBackend.hyMt2Model = index > 0 ? settingsBackend.hyMt2Models[index - 1] : "" }
                                }
                                Button { text: "↻"; onClicked: settingsBackend.refreshHyMt2Models() }
                                Text { text: settingsBackend.hyMt2ModelStatus; color: t ? t.textSecondary : "#9090b8"; font.pixelSize: 11 }
                            }
                            StyledSlider {
                                label: "Hy-MT2 workers"; from: 1; to: 8; step: 1
                                value: settingsBackend.hyMt2Workers
                                onMoved: (val) => { settingsBackend.hyMt2Workers = Math.round(val) }
                            }
                            InputField {
                                label: "Translation style"
                                text: settingsBackend.hyMt2Style
                                placeholder: "e.g. natural, consistent, high-fantasy RPG register"
                                onEditingFinished: (newText) => { settingsBackend.hyMt2Style = newText }
                            }
                        }
                        ColumnLayout {
                            id: provLocal
                            Layout.fillWidth: true
                            spacing: t ? t.spaceMD : 12
                            visible: root.providerTab === 3
                            // Local LLM
                            Text { text: localeManager.strings.settings.section_local_llm; font.pixelSize: t ? t.fontSizeSM : 12; font.bold: true; color: t ? t.accentLight : "#a89bf9" }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: t ? t.spaceMD : 12
                                InputField {
                                    label: localeManager.strings.settings.base_url_label
                                    text: settingsBackend.localLlmUrl
                                    placeholder: "http://localhost:8080/v1"
                                    onEditingFinished: (newText) => { settingsBackend.localLlmUrl = newText }
                                }
                                InputField {
                                    label: localeManager.strings.settings.model_name_label
                                    text: settingsBackend.localLlmModel
                                    placeholder: "(leave empty for llama.cpp)"
                                    onEditingFinished: (newText) => { settingsBackend.localLlmModel = newText }
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: localeManager.strings.settings.local_llm_model_hint
                                wrapMode: Text.Wrap
                                font.pixelSize: 11
                                color: t ? t.textMuted : "#55556a"
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: t ? t.spaceMD : 12

                                Text {
                                    text: localeManager.strings.settings.local_llm_prompt_mode_label
                                    font.pixelSize: 11
                                    font.bold: true
                                    color: t ? t.textSecondary : "#9090b8"
                                }
                                StyledCombo {
                                    id: promptModeCombo
                                    Layout.preferredWidth: 220
                                    model: [
                                        localeManager.strings.settings.local_llm_prompt_mode_append,
                                        localeManager.strings.settings.local_llm_prompt_mode_override
                                    ]
                                    currentIndex: settingsBackend.localLlmPromptMode === "override" ? 1 : 0
                                    onActivated: (index) => {
                                        settingsBackend.localLlmPromptMode = index === 1 ? "override" : "append"
                                    }
                                }
                                CheckBox {
                                    text: localeManager.strings.settings.local_llm_debug_dump_label
                                    checked: settingsBackend.localLlmDebugDump
                                    font.pixelSize: t ? t.fontSizeSM : 12
                                    onToggled: { settingsBackend.localLlmDebugDump = checked }
                                }
                                Item { Layout.fillWidth: true }
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: settingsBackend.localLlmPromptMode === "override"
                                text: localeManager.strings.settings.local_llm_prompt_override_warning
                                wrapMode: Text.Wrap
                                font.pixelSize: 11
                                color: t ? t.warning : "#e0b050"
                            }

                            PromptField {
                                label: localeManager.strings.settings.local_llm_prompt_label
                                text: settingsBackend.localLlmPrompt
                                placeholder: localeManager.strings.settings.local_llm_prompt_placeholder
                                onEditingFinished: (newText) => { settingsBackend.localLlmPrompt = newText }
                            }
                        }
                        ColumnLayout {
                            id: provDeepL
                            Layout.fillWidth: true
                            spacing: t ? t.spaceMD : 12
                            visible: root.providerTab === 4
                            // DeepL & LibreTranslate
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: t ? t.spaceLG : 16
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: t ? t.spaceSM : 8
                                    Text { text: localeManager.strings.settings.section_deepl; font.pixelSize: t ? t.fontSizeSM : 12; font.bold: true; color: t ? t.accentLight : "#a89bf9" }
                                    InputField {
                                        label: localeManager.strings.settings.api_key_label
                                        text: settingsBackend.deeplApiKey
                                        placeholder: "xxxxxxxx-xxxx-..."
                                        isPassword: true
                                        onEditingFinished: (newText) => { settingsBackend.deeplApiKey = newText }
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: t ? t.spaceSM : 8
                                    Text { text: localeManager.strings.settings.section_libretranslate; font.pixelSize: t ? t.fontSizeSM : 12; font.bold: true; color: t ? t.accentLight : "#a89bf9" }
                                    InputField {
                                        label: localeManager.strings.settings.server_url_label
                                        text: settingsBackend.libretranslateUrl
                                        placeholder: "http://localhost:5000"
                                        onEditingFinished: (newText) => { settingsBackend.libretranslateUrl = newText }
                                    }
                                }
                            }
                        }
                    }
                }

                // ===== CARD: Format & Protection =====
                AppCard {
                    Layout.fillWidth: true
                    implicitHeight: fmtCardCol.implicitHeight + 40
                    ColumnLayout {
                        id: fmtCardCol
                        anchors { fill: parent; margins: 20 }
                        spacing: t ? t.spaceLG : 16
                        RowLayout {
                            spacing: t ? t.spaceSM : 8
                            Rectangle { width: 4; height: 16; radius: 2; color: t ? t.success : "#4ade80" }
                            Text { text: localeManager.strings.settings.card_format_title; font.pixelSize: 14; font.bold: true; color: t ? t.textPrimary : "#f0f0ff" }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: t ? t.border1 : "#2e2e3e" }
                        ToggleRow {
                            label: localeManager.strings.settings.auto_wordwrap_label
                            desc: localeManager.strings.settings.auto_wordwrap_desc
                            checked: settingsBackend.autoWordwrap
                            onToggled: (val) => { settingsBackend.autoWordwrap = val }
                        }
                        StyledSlider {
                            label: localeManager.strings.settings.standard_dialogue_limit_label; from: 25; to: 80; step: 1
                            value: settingsBackend.wordwrapLimitStandard
                            onMoved: (val) => { settingsBackend.wordwrapLimitStandard = Math.round(val) }
                        }
                        ToggleRow {
                            label: localeManager.strings.settings.translate_notes_label
                            desc: localeManager.strings.settings.translate_notes_desc
                            checked: settingsBackend.translateNotes
                            onToggled: (val) => { settingsBackend.translateNotes = val }
                        }
                        ToggleRow {
                            label: localeManager.strings.settings.plugin_js_ui_label
                            desc: localeManager.strings.settings.plugin_js_ui_desc
                            checked: settingsBackend.pluginJsUiExtraction
                            onToggled: (val) => { settingsBackend.pluginJsUiExtraction = val }
                        }
                    }
                }

                // ===== CARD: Safety & Cache =====
                AppCard {
                    Layout.fillWidth: true
                    implicitHeight: safeCardCol.implicitHeight + 40
                    ColumnLayout {
                        id: safeCardCol
                        anchors { fill: parent; margins: 20 }
                        spacing: t ? t.spaceLG : 16
                        RowLayout {
                            spacing: t ? t.spaceSM : 8
                            Rectangle { width: 4; height: 16; radius: 2; color: t ? t.warning : "#facc15" }
                            Text { text: localeManager.strings.settings.card_safety_title; font.pixelSize: 14; font.bold: true; color: t ? t.textPrimary : "#f0f0ff" }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: t ? t.border1 : "#2e2e3e" }
                        ToggleRow {
                            label: localeManager.strings.settings.backup_label
                            desc: localeManager.strings.settings.backup_desc
                            checked: settingsBackend.backupEnabled
                            onToggled: (val) => { settingsBackend.backupEnabled = val }
                        }
                        ToggleRow {
                            label: localeManager.strings.settings.cache_label
                            desc: localeManager.strings.settings.cache_desc
                            checked: settingsBackend.useCache
                            onToggled: (val) => { settingsBackend.useCache = val }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Item { Layout.fillWidth: true }
                            Rectangle {
                                implicitWidth: 160; implicitHeight: 34; radius: 8
                                color: clearMouse.pressed ? Qt.rgba(248, 113, 113, 0.25) : (clearMouse.containsMouse ? Qt.rgba(248, 113, 113, 0.15) : Qt.rgba(248, 113, 113, 0.08))
                                border.color: Qt.rgba(248, 113, 113, 0.4); border.width: 1
                                Behavior on color { ColorAnimation { duration: 130 } }
                                Text { anchors.centerIn: parent; text: localeManager.strings.settings.clear_cache_button; font.pixelSize: t ? t.fontSizeSM : 12; color: t ? t.danger : "#f87171" }
                                MouseArea {
                                    id: clearMouse; anchors.fill: parent; hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor; onClicked: appBackend.clearCache()
                                }
                            }
                        }
                    }
                }

                Item { height: 20 }
            }
        }
    }
}
