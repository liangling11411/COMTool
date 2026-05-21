try:
    import parameters,helpAbout,autoUpdate
    from Combobox import ComboBox
    import i18n
    from i18n import _, tr
    import version
    import utils, utils_ui
    from conn.base import ConnectionStatus
    from widgets import statusBar
    from widgets import EditRemarDialog
    from qta_icon_browser import selectIcon
except ImportError:
    from COMTool import parameters,helpAbout,autoUpdate, utils, utils_ui
    from COMTool.Combobox import ComboBox
    from COMTool import i18n
    from COMTool.i18n import _, tr
    from COMTool import version
    from COMTool.conn.base import ConnectionStatus
    from COMTool.widgets import statusBar
    from COMTool.widgets import EditRemarDialog
    from COMTool.qta_icon_browser import selectIcon

try:
    from base import Plugin_Base
except Exception:
    from .base import Plugin_Base

from PyQt5.QtCore import pyqtSignal,Qt, QRect, QMargins, QMimeData, QTimer
from PyQt5.QtWidgets import (QApplication, QWidget,QPushButton,QMessageBox,QDesktopWidget,QMainWindow,
                             QVBoxLayout,QHBoxLayout,QGridLayout,QTextEdit,QLabel,QRadioButton,QCheckBox,
                             QLineEdit,QGroupBox,QSplitter,QFileDialog, QScrollArea, QSpinBox, QSizePolicy,
                             QColorDialog, QFontComboBox, QDialog, QListWidget, QListWidgetItem,
                             QAbstractItemView)
from PyQt5.QtGui import QIcon,QFont,QTextCursor,QPixmap,QColor, QDrag, QTextOption, QPalette, QKeySequence
import qtawesome as qta # https://github.com/spyder-ide/qtawesome
import os, threading, time, re, json
from datetime import datetime

DEFAULT_TEXT_FONT = "Consolas"


class CustomSendItemWidget(QWidget):
    MIME_TYPE = "application/x-comtool-custom-send-index"

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.dragStartPosition = None
        self.setAcceptDrops(True)
        self.setObjectName("customSendItem")

    def startDrag(self):
        idx = self.plugin.customSendItemsLayout.indexOf(self)
        if idx < 0:
            return
        mimeData = QMimeData()
        mimeData.setData(self.MIME_TYPE, str(idx).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self.rect().center())
        drag.exec_(Qt.MoveAction)
        self.plugin.clearCustomSendDropTarget()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.MIME_TYPE):
            self.plugin.setCustomSendDropTarget(self)
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self.MIME_TYPE):
            self.plugin.setCustomSendDropTarget(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.plugin.clearCustomSendDropTarget(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(self.MIME_TYPE):
            return
        try:
            fromIdx = int(bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8"))
        except Exception:
            return
        toIdx = self.plugin.customSendItemsLayout.indexOf(self)
        self.plugin.clearCustomSendDropTarget(self)
        self.plugin.moveCustomSendItemBefore(fromIdx, toIdx)
        event.acceptProposedAction()


class CustomSendDragHandle(QPushButton):
    def __init__(self, itemWidget, parent=None):
        super().__init__("", parent)
        self.itemWidget = itemWidget
        self.dragStartPosition = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragStartPosition = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton) or self.dragStartPosition is None:
            return super().mouseMoveEvent(event)
        if (event.pos() - self.dragStartPosition).manhattanLength() < QApplication.startDragDistance():
            return
        self.itemWidget.startDrag()

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


class CustomSendColorButton(QPushButton):
    def __init__(self, plugin, itemWidget, sendButton, parent=None):
        super().__init__("", parent)
        self.plugin = plugin
        self.itemWidget = itemWidget
        self.sendButton = sendButton

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            idx = self.plugin.customSendItemsLayout.indexOf(self.itemWidget)
            self.plugin.setCustomItemColor(idx, self.itemWidget, self.sendButton, self, "")
            event.accept()
            return
        super().mouseReleaseEvent(event)


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()

class NoWheelFontComboBox(QFontComboBox):
    def wheelEvent(self, event):
        event.ignore()

class ReceiveFindDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.loading = False
        self.currentColor = "#fff176"
        self.setWindowTitle(_("Find in receive area"))
        self.resize(560, 460)

        layout = QVBoxLayout()
        self.setLayout(layout)

        layout.addWidget(QLabel(_("Find content")))
        self.patternEdit = QTextEdit()
        self.patternEdit.setAcceptRichText(False)
        self.patternEdit.setPlaceholderText(_("One plain-text rule per line, or one lambda expression"))
        self.patternEdit.setToolTip(_("Plain text searches exact text. Lambda receives text and may return bool, string, list, or (start, end) ranges."))
        self.patternEdit.setFixedHeight(90)
        layout.addWidget(self.patternEdit)

        optionsLayout = QHBoxLayout()
        self.lambdaCheck = QCheckBox(_("Lambda expression"))
        self.lambdaCheck.setToolTip(_("Use a lambda like: lambda text: re.findall(r'ERR\\d+', text)"))
        self.colorButton = QPushButton(_("Highlight color"))
        self.colorButton.setToolTip(_("Choose highlight color for new rules or selected rules"))
        self.updateColorButton()
        optionsLayout.addWidget(self.lambdaCheck)
        optionsLayout.addWidget(self.colorButton)
        optionsLayout.addStretch(1)
        layout.addLayout(optionsLayout)

        actionsLayout = QHBoxLayout()
        self.addButton = QPushButton(_("Add"))
        self.updateButton = QPushButton(_("Update selected"))
        self.applyColorButton = QPushButton(_("Apply color"))
        self.clearColorButton = QPushButton(_("Clear color"))
        self.deleteButton = QPushButton(_("Delete selected"))
        self.addButton.setToolTip(_("Add one or more find rules"))
        self.updateButton.setToolTip(_("Update the selected find rule from the input"))
        self.applyColorButton.setToolTip(_("Apply the current highlight color to all selected rules"))
        self.clearColorButton.setToolTip(_("Remove highlight color from all selected rules"))
        self.deleteButton.setToolTip(_("Delete all selected find rules"))
        actionsLayout.addWidget(self.addButton)
        actionsLayout.addWidget(self.updateButton)
        actionsLayout.addWidget(self.applyColorButton)
        actionsLayout.addWidget(self.clearColorButton)
        actionsLayout.addWidget(self.deleteButton)
        layout.addLayout(actionsLayout)

        self.rulesList = QListWidget()
        self.rulesList.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.rulesList.setToolTip(_("Select multiple rules to apply or clear highlight color together"))
        layout.addWidget(self.rulesList, 1)

        bottomLayout = QHBoxLayout()
        self.closeButton = QPushButton(_("Close"))
        self.closeButton.setToolTip(_("Close find window"))
        bottomLayout.addStretch(1)
        bottomLayout.addWidget(self.closeButton)
        layout.addLayout(bottomLayout)

        self.autoUpdateTimer = QTimer(self)
        self.autoUpdateTimer.setSingleShot(True)
        self.autoUpdateTimer.setInterval(250)
        self.autoUpdateTimer.timeout.connect(self.updateSelectedRuleFromEditor)

        self.colorButton.clicked.connect(self.selectColor)
        self.addButton.clicked.connect(self.addRules)
        self.updateButton.clicked.connect(self.updateSelectedRuleFromEditor)
        self.applyColorButton.clicked.connect(self.applyColorToSelected)
        self.clearColorButton.clicked.connect(self.clearSelectedColor)
        self.deleteButton.clicked.connect(self.deleteSelectedRules)
        self.closeButton.clicked.connect(self.close)
        self.rulesList.itemSelectionChanged.connect(self.onSelectionChanged)
        self.rulesList.itemChanged.connect(self.onItemChanged)
        self.patternEdit.textChanged.connect(self.queueSelectedUpdate)
        self.lambdaCheck.clicked.connect(self.updateSelectedRuleFromEditor)
        self.refreshRules()

    def updateColorButton(self):
        color = QColor(self.currentColor)
        if color.isValid():
            textColor = "black" if (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) > 160 else "white"
            self.colorButton.setStyleSheet("background-color: {}; border-color: {}; color: {};".format(self.currentColor, self.currentColor, textColor))
        else:
            self.colorButton.setStyleSheet("")

    def selectColor(self):
        color = QColorDialog.getColor(QColor(self.currentColor), self, _("Select color"))
        if not color.isValid():
            return
        self.currentColor = color.name()
        self.updateColorButton()
        if self.selectedIndexes():
            self.applyColorToSelected()

    def selectedIndexes(self):
        return sorted([self.rulesList.row(item) for item in self.rulesList.selectedItems()])

    def ruleText(self, rule):
        prefix = "lambda" if rule.get("isLambda") else "text"
        color = rule.get("color") or _("no color")
        pattern = rule.get("pattern", "").replace("\n", "\\n")
        return "{} [{}] {}".format(prefix, color, pattern)

    def updateListItem(self, idx):
        if idx < 0 or idx >= self.rulesList.count():
            return
        if idx >= len(self.plugin.config["receiveFindRules"]):
            return
        rule = self.plugin.normalizeReceiveFindRule(self.plugin.config["receiveFindRules"][idx])
        item = self.rulesList.item(idx)
        oldLoading = self.loading
        self.loading = True
        item.setText(self.ruleText(rule))
        item.setToolTip(rule.get("pattern", ""))
        item.setCheckState(Qt.Checked if rule.get("enabled") else Qt.Unchecked)
        qcolor = QColor(rule.get("color", ""))
        if qcolor.isValid():
            item.setBackground(qcolor.lighter(170))
        else:
            item.setBackground(QColor("transparent"))
        self.loading = oldLoading

    def refreshRules(self, selectIndexes=None):
        selectIndexes = set(selectIndexes or [])
        self.loading = True
        self.rulesList.clear()
        self.plugin.config["receiveFindRules"] = [
            self.plugin.normalizeReceiveFindRule(rule)
            for rule in self.plugin.config.get("receiveFindRules", [])
        ]
        for idx, rule in enumerate(self.plugin.config["receiveFindRules"]):
            item = QListWidgetItem()
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.rulesList.addItem(item)
            self.updateListItem(idx)
            if idx in selectIndexes:
                item.setSelected(True)
        self.loading = False
        self.updateActionState()

    def updateActionState(self):
        hasSelection = bool(self.selectedIndexes())
        self.updateButton.setEnabled(len(self.selectedIndexes()) == 1)
        self.applyColorButton.setEnabled(hasSelection)
        self.clearColorButton.setEnabled(hasSelection)
        self.deleteButton.setEnabled(hasSelection)

    def onSelectionChanged(self):
        indexes = self.selectedIndexes()
        self.updateActionState()
        if len(indexes) != 1:
            return
        rule = self.plugin.normalizeReceiveFindRule(self.plugin.config["receiveFindRules"][indexes[0]])
        self.loading = True
        self.patternEdit.setPlainText(rule.get("pattern", ""))
        self.lambdaCheck.setChecked(rule.get("isLambda", False))
        if rule.get("color"):
            self.currentColor = rule["color"]
            self.updateColorButton()
        self.loading = False

    def onItemChanged(self, item):
        if self.loading:
            return
        idx = self.rulesList.row(item)
        if idx < 0 or idx >= len(self.plugin.config["receiveFindRules"]):
            return
        self.plugin.config["receiveFindRules"][idx]["enabled"] = item.checkState() == Qt.Checked
        self.plugin.onReceiveFindRulesChanged()

    def queueSelectedUpdate(self):
        if self.loading or len(self.selectedIndexes()) != 1:
            return
        self.autoUpdateTimer.start()

    def inputRules(self):
        text = self.patternEdit.toPlainText()
        if self.lambdaCheck.isChecked():
            rules = [text.strip()]
        else:
            rules = [line.strip() for line in text.splitlines()]
        return [rule for rule in rules if rule]

    def addRules(self):
        patterns = self.inputRules()
        if not patterns:
            return
        isLambda = self.lambdaCheck.isChecked()
        if isLambda:
            ok, msg = self.plugin.validateReceiveFindLambda(patterns[0])
            if not ok:
                self.plugin.hintSignal.emit("error", _("Error"), msg)
                return
        for pattern in patterns:
            self.plugin.config["receiveFindRules"].append(self.plugin.normalizeReceiveFindRule({
                "pattern": pattern,
                "color": self.currentColor,
                "enabled": True,
                "isLambda": isLambda
            }))
        indexes = range(len(self.plugin.config["receiveFindRules"]) - len(patterns), len(self.plugin.config["receiveFindRules"]))
        self.refreshRules(indexes)
        self.plugin.onReceiveFindRulesChanged()

    def updateSelectedRuleFromEditor(self):
        if self.loading:
            return
        indexes = self.selectedIndexes()
        if len(indexes) != 1:
            return
        patterns = self.inputRules()
        if not patterns:
            return
        pattern = patterns[0]
        isLambda = self.lambdaCheck.isChecked()
        if isLambda:
            ok, msg = self.plugin.validateReceiveFindLambda(pattern)
            if not ok:
                return
        idx = indexes[0]
        oldColor = self.plugin.config["receiveFindRules"][idx].get("color", self.currentColor)
        self.plugin.config["receiveFindRules"][idx] = self.plugin.normalizeReceiveFindRule({
            "pattern": pattern,
            "color": oldColor,
            "enabled": self.rulesList.item(idx).checkState() == Qt.Checked,
            "isLambda": isLambda
        })
        self.updateListItem(idx)
        self.plugin.onReceiveFindRulesChanged()

    def applyColorToSelected(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        for idx in indexes:
            if idx < len(self.plugin.config["receiveFindRules"]):
                self.plugin.config["receiveFindRules"][idx]["color"] = self.currentColor
                self.updateListItem(idx)
        self.plugin.onReceiveFindRulesChanged()

    def clearSelectedColor(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        for idx in indexes:
            if idx < len(self.plugin.config["receiveFindRules"]):
                self.plugin.config["receiveFindRules"][idx]["color"] = ""
                self.updateListItem(idx)
        self.plugin.onReceiveFindRulesChanged()

    def deleteSelectedRules(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        for idx in sorted(indexes, reverse=True):
            if idx < len(self.plugin.config["receiveFindRules"]):
                self.plugin.config["receiveFindRules"].pop(idx)
        self.refreshRules()
        self.plugin.onReceiveFindRulesChanged()

class Plugin(Plugin_Base):
    '''
        call sequence:
            set vars like hintSignal, hintSignal
            onInit
            onWidget
            onUiInitDone
                send
                onReceived
    '''
    # vars set by caller
    send = None              # send(data_bytes=None, file_path=None)
    hintSignal = None       # hintSignal.emit(title, msg)
    configGlobal = {}
    # other vars
    connParent = "main"
    connChilds = []
    id = "dbg"
    name = _("Send Receive")
    #
    receiveUpdateSignal = pyqtSignal(str, list, str, bool) # head, content, encoding, isSend
    receiveProgressStop = False
    receivedData = []
    sendRecord = []
    lastColor = None
    lastBg = None
    defaultColor = None
    defaultBg = None
    help = '''{}<br>
<b style="color:#ef5350;"><kbd>F11</kbd></b>: {}<br>
<b style="color:#ef5350;"><kbd>Ctrl+Enter</kbd></b>: {}<br>
<b style="color:#ef5350;"><kbd>Ctrl+L</kbd></b>: {}<br>
<b style="color:#ef5350;"><kbd>Ctrl+K</kbd></b>: {}<br>
'''.format(
        _('Shortcut:'),
        _('Full screen'),
        _('Send data'),
        _('Clear Send Area'),
        _('Clear Receive Area')
    )

    def onInit(self, config):
        super().onInit(config)
        self.lock_wait_rx = threading.Lock()
        self.lock_op_rx_buff = threading.Lock()
        self.keyControlPressed = False
        self.isScheduledSending = False
        self.config = config
        existingFontSize = self.config.get("fontSize", 10)
        hasReceiveFontSize = "receiveFontSize" in self.config
        hasSendFontSize = "sendFontSize" in self.config
        default = {
            "version": 1,
            "receiveAscii" : True,
            "receiveAutoLinefeed" : False,
            "receiveAutoLindefeedTime" : 200,
            "sendAscii" : True,
            "sendScheduled" : False,
            "sendScheduledTime" : 300,
            "sendAutoNewline": False,
            "useCRLF" : True,
            "showTimestamp" : False,
            "recordSend" : False,
            "saveLogPath" : "",
            "saveLogPath2" : "",
            "saveLog" : False,
            "saveLogTimed": False,
            "saveLogDuration": 60,
            "wrap": False,
            "saveLogAutoNew": False,
            "color" : False,
            "sendEscape" : False,
            "customSendItems" : [],
            "sendHistoryList" : [],
            "receiveEscape" : False,
            "fontSize": 10,
            "receiveFontSize": 10,
            "sendFontSize": 10,
            "receiveFontFamily": DEFAULT_TEXT_FONT,
            "sendFontFamily": DEFAULT_TEXT_FONT,
            "receiveFontColor": "#2e7d32",
            "sendFontColor": "#1976d2",
            "timestampColor": "#6d6d6d",
            "timestampNewline": False,
            "receiveFindRules": []
        }
        for k in default:
            if not k in self.config:
                self.config[k] = default[k]
        if not hasReceiveFontSize:
            self.config["receiveFontSize"] = 10
        if not hasSendFontSize:
            self.config["sendFontSize"] = existingFontSize
        self.config["fontSize"] = self.config["sendFontSize"]
        self.config["color"] = False
        self.lastShowTail = ''
        self.justSent = False # sent data before received data flag
        self.customSendDropTarget = None
        self.receiveDisplayRecords = []
        self.rerenderingReceiveArea = False
        self.saveLogStopTimer = None
        self.saveLogStatusTimer = None
        self.logStartTime = None
        self.receiveFindDialog = None
        self.receiveFindRuleErrors = set()

    def ensureMainActionButtons(self):
        if hasattr(self, "clearReceiveButtion") and hasattr(self, "clearSendButtion"):
            return
        self.clearReceiveButtion = QPushButton(_("Clear RX"))
        self.clearReceiveButtion.setToolTip(_("Clear receive area"))
        utils_ui.setButtonIcon(self.clearReceiveButtion, "mdi6.broom")
        self.clearSendButtion = QPushButton(_("Clear TX"))
        self.clearSendButtion.setToolTip(_("Clear send input"))
        utils_ui.setButtonIcon(self.clearSendButtion, "mdi6.broom")

    def onWidgetMain(self, parent):
        self.mainWidget = QSplitter(Qt.Vertical)
        # widgets receive and send area
        self.receiveArea = QTextEdit()
        self.receiveArea.setToolTip(_("Received RX/TX log output"))
        font = QFont(self.config.get("receiveFontFamily", DEFAULT_TEXT_FONT), self.config["receiveFontSize"])
        self.receiveArea.setFont(font)
        self.sendArea = QTextEdit()
        self.sendArea.setToolTip(_("Input data to send"))
        self.sendArea.setAcceptRichText(False)
        self.ensureMainActionButtons()
        self.receiveFindButton = QPushButton("")
        self.receiveFindButton.setToolTip(_("Find and highlight receive text"))
        utils_ui.setButtonIcon(self.receiveFindButton, "fa.search")
        self.sendButton = QPushButton("")
        self.sendButton.setToolTip(_("Send input data"))
        utils_ui.setButtonIcon(self.sendButton, "fa.send")
        self.sendHistory = ComboBox()
        self.sendHistory.setToolTip(_("Send history"))
        receiveWidget = QWidget()
        receiveAreaWidgetsLayout = QHBoxLayout()
        receiveAreaWidgetsLayout.setContentsMargins(0,0,0,0)
        receiveWidget.setLayout(receiveAreaWidgetsLayout)
        receiveAreaWidgetsLayout.addWidget(self.receiveArea)
        sendWidget = QWidget()
        sendAreaWidgetsLayout = QHBoxLayout()
        sendAreaWidgetsLayout.setContentsMargins(0,4,0,0)
        sendWidget.setLayout(sendAreaWidgetsLayout)
        buttonLayout = QVBoxLayout()
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(self.receiveFindButton)
        buttonLayout.addWidget(self.sendButton)
        sendAreaWidgetsLayout.addWidget(self.sendArea)
        sendAreaWidgetsLayout.addLayout(buttonLayout)
        self.mainWidget.addWidget(receiveWidget)
        self.mainWidget.addWidget(sendWidget)
        self.mainWidget.addWidget(self.sendHistory)
        self.mainWidget.setStretchFactor(0, 7)
        self.mainWidget.setStretchFactor(1, 2)
        self.mainWidget.setStretchFactor(2, 1)
        # event
        self.receiveFindButton.clicked.connect(self.openReceiveFindDialog)
        self.sendButton.clicked.connect(self.onSendData)
        self.clearReceiveButtion.clicked.connect(self.clearReceiveBuffer)
        self.clearSendButtion.clicked.connect(self.sendArea.clear)
        self.receiveUpdateSignal.connect(self.updateReceivedDataDisplay)
        self.sendHistory.activated.connect(self.onSendHistoryIndexChanged)

        return self.mainWidget

    def onWidgetSettings(self, parent):
        # serial receive settings
        layout = QVBoxLayout()
        serialReceiveSettingsLayout = QGridLayout()
        serialReceiveSettingsGroupBox = QGroupBox(_("Receive Settings"))
        self.receiveSettingsAscii = QRadioButton(_("ASCII"))
        self.receiveSettingsAscii.setToolTip(_("Show recived data as visible format, select decode method at top right corner"))
        self.receiveSettingsHex = QRadioButton(_("HEX"))
        self.receiveSettingsHex.setToolTip(_("Show recived data as hex format"))
        self.receiveSettingsAscii.setChecked(True)
        self.receiveSettingsAutoLinefeed = QCheckBox(_("Auto\nLinefeed\nms"))
        self.receiveSettingsAutoLinefeed.setToolTip(_("Auto linefeed after interval, unit: ms"))
        self.receiveSettingsAutoLinefeedTime = QLineEdit("200")
        self.receiveSettingsAutoLinefeedTime.setProperty("class", "smallInput")
        self.receiveSettingsAutoLinefeedTime.setToolTip(_("Auto linefeed after interval, unit: ms"))
        self.receiveSettingsAutoLinefeed.setMaximumWidth(75)
        self.receiveSettingsAutoLinefeedTime.setMaximumWidth(75)
        self.receiveSettingsTimestamp = QCheckBox(_("Timestamp"))
        self.receiveSettingsTimestamp.setToolTip(_("Add timestamp before received data, will automatically enable auto line feed"))
        self.receiveSettingsWrap = QCheckBox(_("Display wrap"))
        self.receiveEscape = QCheckBox(_("Escape"))
        self.receiveEscape.setToolTip(_("Enable escape characters support like \\t \\r \\n \\x01 \\001"))
        self.receiveSettingsWrap.setToolTip(_("When content in a line is too long, always auto wrap to show, and no scroll bar"))
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAscii,1,0,1,1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsHex,1,1,1,1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAutoLinefeed, 2, 0, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAutoLinefeedTime, 2, 1, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsWrap, 3, 0, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveEscape, 3, 1, 1, 1)
        serialReceiveSettingsGroupBox.setLayout(serialReceiveSettingsLayout)
        serialReceiveSettingsGroupBox.setAlignment(Qt.AlignHCenter)
        layout.addWidget(serialReceiveSettingsGroupBox)

        timestampSettingsLayout = QGridLayout()
        timestampSettingsGroupBox = QGroupBox(_("Timestamp"))
        self.timestampColorButton = QPushButton(_("Color"))
        self.timestampColorButton.setToolTip(_("Timestamp color in receive area"))
        self.timestampNewlineCheckbox = QCheckBox(_("Newline after timestamp"))
        self.timestampNewlineCheckbox.setToolTip(_("Display received data on the next line after timestamp"))
        timestampSettingsLayout.addWidget(self.receiveSettingsTimestamp, 0, 0, 1, 2)
        timestampSettingsLayout.addWidget(QLabel(_("Timestamp color")), 1, 0, 1, 1)
        timestampSettingsLayout.addWidget(self.timestampColorButton, 1, 1, 1, 1)
        timestampSettingsLayout.addWidget(self.timestampNewlineCheckbox, 2, 0, 1, 2)
        timestampSettingsGroupBox.setLayout(timestampSettingsLayout)
        layout.addWidget(timestampSettingsGroupBox)

        # serial send settings
        serialSendSettingsLayout = QGridLayout()
        serialSendSettingsGroupBox = QGroupBox(_("Send Settings"))
        self.sendSettingsAscii = QRadioButton(_("ASCII"))
        self.sendSettingsHex = QRadioButton(_("HEX"))
        self.sendSettingsAscii.setToolTip(_("Get send data as visible format, select encoding method at top right corner"))
        self.sendSettingsHex.setToolTip(_("Get send data as hex format, e.g. hex '31 32 33' equal to ascii '123'"))
        self.sendSettingsAscii.setChecked(True)
        self.sendSettingsScheduledCheckBox = QCheckBox(_("Timed Send\nms"))
        self.sendSettingsScheduledCheckBox.setToolTip(_("Timed send, unit: ms"))
        self.sendSettingsScheduled = QLineEdit("300")
        self.sendSettingsScheduled.setProperty("class", "smallInput")
        self.sendSettingsScheduled.setToolTip(_("Timed send, unit: ms"))
        self.sendSettingsScheduledCheckBox.setMaximumWidth(75)
        self.sendSettingsScheduled.setMaximumWidth(75)
        self.sendSettingsCRLF = QCheckBox(_("<CRLF>"))
        self.sendSettingsCRLF.setToolTip(_("Select to send \\r\\n instead of \\n"))
        self.sendSettingsCRLF.setChecked(False)
        self.sendSettingsRecord = QCheckBox(_("Record"))
        self.sendSettingsRecord.setToolTip(_("Record send data"))
        self.sendSettingsEscape= QCheckBox(_("Escape"))
        self.sendSettingsEscape.setToolTip(_("Enable escape characters support like \\t \\r \\n \\x01 \\001"))
        self.sendSettingsAppendNewLine= QCheckBox(_("Newline"))
        self.sendSettingsAppendNewLine.setToolTip(_("Auto add new line when send"))
        serialSendSettingsLayout.addWidget(self.sendSettingsAscii,1,0,1,1)
        serialSendSettingsLayout.addWidget(self.sendSettingsHex,1,1,1,1)
        serialSendSettingsLayout.addWidget(self.sendSettingsScheduledCheckBox, 2, 0, 1, 1)
        serialSendSettingsLayout.addWidget(self.sendSettingsScheduled, 2, 1, 1, 1)
        serialSendSettingsLayout.addWidget(self.sendSettingsCRLF, 3, 0, 1, 1)
        serialSendSettingsLayout.addWidget(self.sendSettingsAppendNewLine, 3, 1, 1, 1)
        serialSendSettingsLayout.addWidget(self.sendSettingsEscape, 4, 0, 1, 2)
        serialSendSettingsLayout.addWidget(self.sendSettingsEscape, 4, 0, 1, 2)
        serialSendSettingsLayout.addWidget(self.sendSettingsRecord, 4, 1, 1, 1)
        serialSendSettingsGroupBox.setLayout(serialSendSettingsLayout)
        layout.addWidget(serialSendSettingsGroupBox)
        self.ensureMainActionButtons()
        self.createFunctionalSettings(layout)

        widget = QWidget()
        widget.setLayout(layout)
        layout.setContentsMargins(0,0,0,0)
        # event
        self.receiveSettingsTimestamp.clicked.connect(self.onTimeStampClicked)
        self.timestampNewlineCheckbox.clicked.connect(lambda: self.bindVar(self.timestampNewlineCheckbox, self.config, "timestampNewline"))
        self.timestampColorButton.clicked.connect(self.selectTimestampColor)
        self.receiveSettingsAutoLinefeed.clicked.connect(self.onAutoLinefeedClicked)
        self.receiveSettingsAscii.clicked.connect(lambda : self.switchRxMode(True))
        self.receiveSettingsHex.clicked.connect(lambda : self.switchRxMode(False))
        self.sendSettingsHex.clicked.connect(self.onSendSettingsHexClicked)
        self.sendSettingsAscii.clicked.connect(self.onSendSettingsAsciiClicked)
        self.sendSettingsRecord.clicked.connect(self.onRecordSendClicked)
        self.sendSettingsAppendNewLine.clicked.connect(lambda: self.bindVar(self.sendSettingsAppendNewLine, self.config, "sendAutoNewline"))
        self.sendSettingsEscape.clicked.connect(lambda: self.bindVar(self.sendSettingsEscape, self.config, "sendEscape"))
        self.sendSettingsCRLF.clicked.connect(lambda: self.bindVar(self.sendSettingsCRLF, self.config, "useCRLF"))
        self.receiveSettingsAutoLinefeedTime.textChanged.connect(lambda: self.bindVar(self.receiveSettingsAutoLinefeedTime, self.config, "receiveAutoLindefeedTime", vtype=int, vErrorMsg=_("Auto line feed value error, must be integer"), emptyDefault = "200"))
        self.sendSettingsScheduled.textChanged.connect(lambda: self.bindVar(self.sendSettingsScheduled, self.config, "sendScheduledTime", vtype=int, vErrorMsg=_("Timed send value error, must be integer"), emptyDefault = "300"))
        self.sendSettingsScheduledCheckBox.clicked.connect(lambda: self.bindVar(self.sendSettingsScheduledCheckBox, self.config, "sendScheduled"))
        self.receiveSettingsWrap.clicked.connect(self.onSettingWrap)
        self.receiveEscape.clicked.connect(lambda: self.bindVar(self.receiveEscape, self.config, "receiveEscape"))
        self.sendFileButton.clicked.connect(self.sendFile)
        self.saveLogCheckbox.clicked.connect(self.setSaveLog)
        self.logFileBtn.clicked.connect(self.selectLogFile)
        self.saveLogAutoNew.clicked.connect(lambda: self.bindVar(self.saveLogAutoNew, self.config, "saveLogAutoNew"))
        self.saveLogTimed.clicked.connect(self.onSaveLogTimedChanged)
        self.saveLogDuration.editingFinished.connect(self.onSaveLogDurationChanged)
        self.openFileButton.clicked.connect(self.selectFile)
        self.clearHistoryButton.clicked.connect(self.clearHistory)
        self.receiveFontSizeInput.valueChanged.connect(self.changeReceiveFontSize)
        self.sendFontSizeInput.valueChanged.connect(self.changeSendFontSize)
        self.receiveFontFamilyInput.currentFontChanged.connect(self.changeReceiveFontFamily)
        self.sendFontFamilyInput.currentFontChanged.connect(self.changeSendFontFamily)
        self.receiveFontColorButton.clicked.connect(lambda: self.selectDefaultFontColor("receiveFontColor"))
        self.sendFontColorButton.clicked.connect(lambda: self.selectDefaultFontColor("sendFontColor"))
        if self.saveLogStopTimer is None:
            self.saveLogStopTimer = QTimer(self)
            self.saveLogStopTimer.setSingleShot(True)
            self.saveLogStopTimer.timeout.connect(self.stopTimedSaveLog)
        if self.saveLogStatusTimer is None:
            self.saveLogStatusTimer = QTimer(self)
            self.saveLogStatusTimer.setInterval(1000)
            self.saveLogStatusTimer.timeout.connect(self.updateSaveLogStatus)
        return widget

    def onFunctionalWidgetDefaultVisible(self):
        return True

    def onConfigButtonsInSettings(self):
        return True

    def onSettingsWidgetScrollTogether(self):
        return True

    def createFunctionalSettings(self, parentLayout):
        self.fontSettingsGroupBox = QGroupBox(_("Default font"))
        fontSettingsLayout = QGridLayout()
        self.fontSettingsGroupBox.setLayout(fontSettingsLayout)
        self.receiveFontFamilyInput = NoWheelFontComboBox()
        self.receiveFontFamilyInput.setToolTip(_("Font family for received RX text"))
        self.receiveFontSizeInput = NoWheelSpinBox()
        self.receiveFontSizeInput.setRange(1, 100)
        self.receiveFontSizeInput.setToolTip(_("Font size for received RX text"))
        self.receiveFontColorButton = QPushButton(_("Color"))
        self.receiveFontColorButton.setToolTip(_("Color for received RX text in the receive area"))
        self.sendFontFamilyInput = NoWheelFontComboBox()
        self.sendFontFamilyInput.setToolTip(_("Font family for TX input text"))
        self.sendFontSizeInput = NoWheelSpinBox()
        self.sendFontSizeInput.setRange(1, 100)
        self.sendFontSizeInput.setToolTip(_("Font size for TX input text"))
        self.sendFontColorButton = QPushButton(_("Color"))
        self.sendFontColorButton.setToolTip(_("Color for TX input text and recorded TX lines"))
        fontSettingsLayout.addWidget(QLabel(_("RX font")), 0, 0, 1, 1)
        fontSettingsLayout.addWidget(self.receiveFontFamilyInput, 0, 1, 1, 3)
        fontSettingsLayout.addWidget(QLabel(_("RX size")), 1, 0, 1, 1)
        fontSettingsLayout.addWidget(self.receiveFontSizeInput, 1, 1, 1, 1)
        fontSettingsLayout.addWidget(QLabel(_("RX color")), 1, 2, 1, 1)
        fontSettingsLayout.addWidget(self.receiveFontColorButton, 1, 3, 1, 1)
        fontSettingsLayout.addWidget(QLabel(_("TX font")), 2, 0, 1, 1)
        fontSettingsLayout.addWidget(self.sendFontFamilyInput, 2, 1, 1, 3)
        fontSettingsLayout.addWidget(QLabel(_("TX size")), 3, 0, 1, 1)
        fontSettingsLayout.addWidget(self.sendFontSizeInput, 3, 1, 1, 1)
        fontSettingsLayout.addWidget(QLabel(_("TX color")), 3, 2, 1, 1)
        fontSettingsLayout.addWidget(self.sendFontColorButton, 3, 3, 1, 1)
        self.fontSizeInput = self.sendFontSizeInput

        self.filePathWidget = QLineEdit()
        self.filePathWidget.setToolTip(_("Path of the file to send"))
        self.openFileButton = QPushButton(_("Open File"))
        self.openFileButton.setToolTip(_("Select a file to send"))
        self.sendFileButton = QPushButton(_("Send File"))
        self.sendFileButton.setToolTip(_("Send the selected file over the current connection"))
        self.clearHistoryButton = QPushButton(_("Clear History"))
        self.clearHistoryButton.setToolTip(_("Clear send history"))
        self.fileSendGroupBox = QGroupBox(_("Send File"))
        fileSendGridLayout = QGridLayout()
        fileSendGridLayout.addWidget(self.filePathWidget, 0, 0, 1, 1)
        fileSendGridLayout.addWidget(self.openFileButton, 0, 1, 1, 1)
        fileSendGridLayout.addWidget(self.sendFileButton, 1, 0, 1, 2)
        self.fileSendGroupBox.setLayout(fileSendGridLayout)

        self.logFileGroupBox = QGroupBox(_("Save log"))
        logFileWrapper = QVBoxLayout()
        logFileLayout = QHBoxLayout()
        self.saveLogCheckbox = QCheckBox()
        self.saveLogCheckbox.setToolTip(_("Enable saving received and recorded sent data to a log file"))
        self.logFilePath = QLineEdit()
        self.logFilePath.setToolTip(_("Log file path"))
        self.logFileBtn = QPushButton(_("Log path"))
        self.logFileBtn.setToolTip(_("Select log file path"))
        self.saveLogAutoNew = QCheckBox(_("Auto new file"))
        self.saveLogAutoNew.setToolTip(_("When start a new connection, will automatically create a new log file"))
        self.saveLogTimed = QCheckBox(_("Timed log"))
        self.saveLogTimed.setToolTip(_("Stop saving log automatically after the configured duration"))
        self.saveLogDuration = QLineEdit("00:01:00")
        self.saveLogDuration.setProperty("class", "smallInput")
        self.saveLogDuration.setMaximumWidth(90)
        self.saveLogDuration.setPlaceholderText("HH:MM:SS")
        self.saveLogDuration.setToolTip(_("Timed log duration, format: HH:MM:SS"))
        self.saveLogStatusLabel = QLabel(_("Log: 00:00:00 / 0 B"))
        self.saveLogStatusLabel.setToolTip(_("Current log recording duration and file size"))
        logFileLayout.addWidget(self.saveLogCheckbox)
        logFileLayout.addWidget(self.logFilePath)
        logFileLayout.addWidget(self.logFileBtn)
        logTimedLayout = QHBoxLayout()
        logTimedLayout.addWidget(self.saveLogTimed)
        logTimedLayout.addWidget(self.saveLogDuration)
        logTimedLayout.addStretch(1)
        logFileWrapper.addLayout(logFileLayout)
        logFileWrapper.addWidget(self.saveLogAutoNew)
        logFileWrapper.addLayout(logTimedLayout)
        logFileWrapper.addWidget(self.saveLogStatusLabel)
        self.logFileGroupBox.setLayout(logFileWrapper)

        clearButtonsLayout = QHBoxLayout()
        clearButtonsLayout.addWidget(self.clearReceiveButtion)
        clearButtonsLayout.addWidget(self.clearSendButtion)

        parentLayout.addWidget(self.fontSettingsGroupBox)
        parentLayout.addWidget(self.logFileGroupBox)
        parentLayout.addWidget(self.fileSendGroupBox)
        parentLayout.addWidget(self.clearHistoryButton)
        parentLayout.addLayout(clearButtonsLayout)

    def switchRxMode(self, ascii):
        if ascii:
            self.receiveSettingsAscii.setChecked(True)
            self.config["receiveAscii"] = True
            self.receiveEscape.setDisabled(False)
        else:
            self.receiveSettingsHex.setChecked(True)
            self.config["receiveAscii"] = False
            self.receiveEscape.setDisabled(True)


    def onWidgetFunctional(self, parent):
        sendFunctionalLayout = QVBoxLayout()
        sendFunctionalLayout.setContentsMargins(0,0,0,0)
        self.addButton = QPushButton("")
        utils_ui.setButtonIcon(self.addButton, "fa.plus")
        self.importCustomSendButton = QPushButton(_("Import"))
        self.exportCustomSendButton = QPushButton(_("Export"))
        self.addButton.setToolTip(_("Add a custom send item"))
        self.importCustomSendButton.setToolTip(_("Import custom send items from JSON"))
        self.exportCustomSendButton.setToolTip(_("Export custom send items to JSON"))
        utils_ui.setButtonIcon(self.importCustomSendButton, "fa.folder-open")
        utils_ui.setButtonIcon(self.exportCustomSendButton, "fa.save")
        self.customSendSearch = QLineEdit()
        self.customSendSearch.setClearButtonEnabled(True)
        self.customSendSearch.setPlaceholderText(_("Search remark or command"))
        self.customSendSearch.setToolTip(_("Search custom send items by remark or command"))
        self.customSendSelectAll = QCheckBox(_("All"))
        self.customSendSelectAll.setToolTip(_("Select visible custom send items"))
        self.batchCustomSendColorButton = QPushButton(_("Color"))
        self.batchCustomSendIconButton = QPushButton(_("Icon"))
        self.batchCustomSendDeleteButton = QPushButton(_("Delete"))
        self.batchCustomSendColorButton.setToolTip(_("Set color for selected custom send items"))
        self.batchCustomSendIconButton.setToolTip(_("Set icon for selected custom send items"))
        self.batchCustomSendDeleteButton.setToolTip(_("Delete selected custom send items"))
        utils_ui.setButtonIcon(self.batchCustomSendColorButton, "fa.paint-brush")
        utils_ui.setButtonIcon(self.batchCustomSendIconButton, "fa.send")
        utils_ui.setButtonIcon(self.batchCustomSendDeleteButton, "fa.trash")
        self.batchCustomSendDeleteButton.setProperty("class", "deleteBtn")
        # cumtom send zone
        #   groupbox
        customSendGroupBox = QGroupBox(_("Cutom send"))
        customSendItemsLayout0 = QVBoxLayout()
        customSendItemsLayout0.setContentsMargins(0,8,0,0)
        customSendGroupBox.setLayout(customSendItemsLayout0)
        #   scroll

        self.customSendScroll = QScrollArea()
        self.customSendScroll.setMinimumHeight(320)
        self.customSendScroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.customSendScroll.setWidgetResizable(True)
        self.customSendScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        #   add scroll to groupbox
        customSendItemsLayout0.addWidget(self.customSendSearch)
        customSendBatchLayout = QHBoxLayout()
        customSendBatchLayout.setContentsMargins(0,0,0,0)
        customSendBatchLayout.addWidget(self.customSendSelectAll)
        customSendBatchLayout.addWidget(self.batchCustomSendColorButton)
        customSendBatchLayout.addWidget(self.batchCustomSendIconButton)
        customSendBatchLayout.addWidget(self.batchCustomSendDeleteButton)
        customSendItemsLayout0.addLayout(customSendBatchLayout)
        customSendItemsLayout0.addWidget(self.customSendScroll)
        #   wrapper widget
        cutomSendItemsWraper = QWidget()
        customSendItemsLayoutWrapper = QVBoxLayout()
        customSendItemsLayoutWrapper.setContentsMargins(0,0,0,0)
        cutomSendItemsWraper.setLayout(customSendItemsLayoutWrapper)
        #    custom items
        customItems = QWidget()
        customItems.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.customSendItemsLayout = QVBoxLayout()
        self.customSendItemsLayout.setContentsMargins(0,0,0,0)
        self.customSendItemsLayout.setAlignment(Qt.AlignTop)
        customItems.setLayout(self.customSendItemsLayout)
        customSendButtonsLayout = QHBoxLayout()
        customSendButtonsLayout.setContentsMargins(0,0,0,0)
        customSendButtonsLayout.addWidget(self.importCustomSendButton)
        customSendButtonsLayout.addWidget(self.exportCustomSendButton)
        customSendButtonsLayout.addWidget(self.addButton)
        customSendItemsLayoutWrapper.addWidget(customItems)
        customSendItemsLayoutWrapper.addLayout(customSendButtonsLayout)
        customSendItemsLayoutWrapper.addStretch(1)
        #   set wrapper widget
        self.customSendScroll.setWidget(cutomSendItemsWraper)
        self.customSendScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sendFunctionalLayout.addWidget(customSendGroupBox, 1)
        self.funcWidget = QWidget()
        self.funcWidget.setMinimumWidth(360)
        self.funcWidget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.funcWidget.setLayout(sendFunctionalLayout)
        # event
        self.addButton.clicked.connect(self.customSendAdd)
        self.importCustomSendButton.clicked.connect(self.importCustomSendItems)
        self.exportCustomSendButton.clicked.connect(self.exportCustomSendItems)
        self.customSendSearch.textChanged.connect(self.filterCustomSendItems)
        self.customSendSelectAll.clicked.connect(self.setVisibleCustomSendSelection)
        self.batchCustomSendColorButton.clicked.connect(self.batchSetCustomSendColor)
        self.batchCustomSendIconButton.clicked.connect(self.batchSetCustomSendIcon)
        self.batchCustomSendDeleteButton.clicked.connect(self.batchDeleteCustomSendItems)
        self.funcParent = parent
        return self.funcWidget

    def onWidgetStatusBar(self, parent):
        self.statusBar = statusBar(rxTxCount=True)
        return self.statusBar

    def onUiInitDone(self):
        paramObj = self.config
        self.receiveSettingsHex.setChecked(not paramObj["receiveAscii"])
        self.receiveEscape.setDisabled(not paramObj["receiveAscii"])
        self.receiveSettingsAutoLinefeed.setChecked(paramObj["receiveAutoLinefeed"])
        self.receiveEscape.setChecked(paramObj["receiveEscape"])
        try:
            interval = int(paramObj["receiveAutoLindefeedTime"])
            paramObj["receiveAutoLindefeedTime"] = interval
        except Exception:
            interval = 200
        self.receiveSettingsAutoLinefeedTime.setText(str(interval))
        self.receiveSettingsTimestamp.setChecked(paramObj["showTimestamp"])
        self.timestampNewlineCheckbox.setChecked(paramObj["timestampNewline"])
        self.updateDefaultFontColorButton(self.timestampColorButton, paramObj["timestampColor"])
        self.receiveSettingsWrap.setChecked(paramObj["wrap"])
        self.sendSettingsHex.setChecked(not paramObj["sendAscii"])
        self.sendSettingsScheduledCheckBox.setChecked(paramObj["sendScheduled"])
        try:
            interval = int(paramObj["sendScheduledTime"])
            paramObj["sendScheduledTime"] = interval
        except Exception:
            interval = 300
        self.sendSettingsScheduled.setText(str(interval))
        self.sendSettingsCRLF.setChecked(paramObj["useCRLF"])
        self.sendSettingsAppendNewLine.setChecked(paramObj["sendAutoNewline"])
        self.sendSettingsRecord.setChecked(paramObj["recordSend"])
        self.sendSettingsEscape.setChecked(paramObj["sendEscape"])
        for i in range(0, len(paramObj["sendHistoryList"])):
            text = paramObj["sendHistoryList"][i]
            self.sendHistory.addItem(text)
        self.logFilePath.setText(paramObj["saveLogPath"])
        self.logFilePath.setToolTip(paramObj["saveLogPath"])
        self.saveLogCheckbox.setChecked(paramObj["saveLog"])
        self.saveLogAutoNew.setChecked(paramObj["saveLogAutoNew"])
        self.saveLogTimed.setChecked(paramObj["saveLogTimed"])
        try:
            duration = int(paramObj["saveLogDuration"])
            paramObj["saveLogDuration"] = duration
        except Exception:
            duration = 60
        self.saveLogDuration.setText(self.secondsToHms(duration))
        self.updateSaveLogStatus()
        # wrap
        self.applyWrapMode()
        # send items
        customSendItems = []
        for item in paramObj["customSendItems"]:
            customSendItems.append(self.insertSendItem(item, load=True))
        paramObj["customSendItems"] = customSendItems
        self.filterCustomSendItems()
        self.receiveFontFamilyInput.setCurrentFont(QFont(paramObj["receiveFontFamily"]))
        self.sendFontFamilyInput.setCurrentFont(QFont(paramObj["sendFontFamily"]))
        self.receiveFontSizeInput.setValue(paramObj["receiveFontSize"])
        self.sendFontSizeInput.setValue(paramObj["sendFontSize"])
        self.updateDefaultFontColorButton(self.receiveFontColorButton, paramObj["receiveFontColor"])
        self.updateDefaultFontColorButton(self.sendFontColorButton, paramObj["sendFontColor"])
        self.applyReceiveFont()
        self.applySendFont()
        paramObj["receiveFindRules"] = [
            self.normalizeReceiveFindRule(rule)
            for rule in paramObj.get("receiveFindRules", [])
        ]
        if paramObj["saveLog"]:
            self.logStartTime = time.time()
            self.startSaveLogStatus()
        self.startTimedSaveLog()

        self.receiveProcess = threading.Thread(target=self.receiveDataProcess)
        self.receiveProcess.setDaemon(True)
        self.receiveProcess.start()

    def normalizeReceiveFindRule(self, rule=None):
        if rule is None:
            rule = {}
        if isinstance(rule, str):
            rule = {"pattern": rule}
        return {
            "pattern": "" if rule.get("pattern") is None else str(rule.get("pattern", "")),
            "color": "" if rule.get("color") is None else str(rule.get("color", "")),
            "enabled": bool(rule.get("enabled", True)),
            "isLambda": bool(rule.get("isLambda", rule.get("lambda", False)))
        }

    def onReceiveFindRulesChanged(self):
        self.config["receiveFindRules"] = [
            self.normalizeReceiveFindRule(rule)
            for rule in self.config.get("receiveFindRules", [])
        ]
        self.receiveFindRuleErrors.clear()
        self.rerenderReceiveArea()

    def openReceiveFindDialog(self):
        if self.receiveFindDialog is None:
            self.receiveFindDialog = ReceiveFindDialog(self, self.mainWidget)
        self.receiveFindDialog.refreshRules()
        self.receiveFindDialog.show()
        self.receiveFindDialog.raise_()
        self.receiveFindDialog.activateWindow()

    def validateReceiveFindLambda(self, expression):
        try:
            self.compileReceiveFindLambda(expression)
        except Exception as e:
            return False, _("Lambda expression error") + ": " + str(e)
        return True, ""

    def compileReceiveFindLambda(self, expression):
        safeGlobals = {
            "__builtins__": {},
            "re": re,
            "len": len,
            "min": min,
            "max": max,
            "sum": sum,
            "any": any,
            "all": all,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
        }
        func = eval(expression, safeGlobals, {})
        if not callable(func):
            raise ValueError(_("Lambda expression must return a callable"))
        return func

    def plainTextFindRanges(self, text, pattern):
        if not pattern:
            return []
        ranges = []
        start = 0
        while True:
            idx = text.find(pattern, start)
            if idx < 0:
                break
            end = idx + len(pattern)
            ranges.append((idx, end))
            start = end if end > idx else idx + 1
        return ranges

    def lambdaResultFindRanges(self, text, result):
        if result is None or result is False:
            return []
        if result is True:
            return [(0, len(text))] if text else []
        if hasattr(result, "start") and hasattr(result, "end"):
            return [(result.start(), result.end())]
        if isinstance(result, str):
            return self.plainTextFindRanges(text, result)
        if isinstance(result, (tuple, list)) and len(result) == 2 and all(isinstance(v, int) for v in result):
            return [tuple(result)]
        if isinstance(result, (tuple, list, set)):
            ranges = []
            for item in result:
                ranges.extend(self.lambdaResultFindRanges(text, item))
            return ranges
        return self.plainTextFindRanges(text, str(result))

    def receiveFindRuleRanges(self, rule, text):
        pattern = rule.get("pattern", "")
        if not pattern:
            return []
        if rule.get("isLambda", False):
            try:
                func = self.compileReceiveFindLambda(pattern)
                return self.lambdaResultFindRanges(text, func(text))
            except Exception as e:
                key = pattern
                if key not in self.receiveFindRuleErrors:
                    self.receiveFindRuleErrors.add(key)
                    print("receive find lambda error:", e)
                return []
        return self.plainTextFindRanges(text, pattern)

    def splitTextByReceiveFindRules(self, text, originalColor=None, originalBg=None):
        if not text:
            return []
        ranges = []
        for order, rawRule in enumerate(self.config.get("receiveFindRules", [])):
            rule = self.normalizeReceiveFindRule(rawRule)
            color = rule.get("color", "")
            qcolor = QColor(color)
            if not rule.get("enabled") or not color or not qcolor.isValid():
                continue
            for start, end in self.receiveFindRuleRanges(rule, text):
                start = max(0, min(len(text), int(start)))
                end = max(0, min(len(text), int(end)))
                if start < end:
                    ranges.append((start, end, color, order))
        if not ranges:
            return [[originalColor, originalBg, text]]
        points = {0, len(text)}
        for start, end, _color, _order in ranges:
            points.add(start)
            points.add(end)
        points = sorted(points)
        segments = []
        for idx in range(len(points) - 1):
            start, end = points[idx], points[idx + 1]
            if start == end:
                continue
            bg = originalBg
            bestOrder = -1
            for rangeStart, rangeEnd, color, order in ranges:
                if rangeStart <= start and end <= rangeEnd and order >= bestOrder:
                    bg = color
                    bestOrder = order
            segments.append([originalColor, bg, text[start:end]])
        return segments

    def setTextEditPaletteColor(self, edit, color, updateDocument=False):
        qcolor = QColor(color)
        if not qcolor.isValid():
            return
        palette = edit.palette()
        palette.setColor(QPalette.Text, qcolor)
        edit.setPalette(palette)
        edit.setTextColor(qcolor)
        if updateDocument and edit.document().characterCount() > 1:
            cursor = edit.textCursor()
            verticalValue = edit.verticalScrollBar().value()
            horizontalValue = edit.horizontalScrollBar().value()
            docCursor = QTextCursor(edit.document())
            docCursor.select(QTextCursor.Document)
            textFormat = docCursor.charFormat()
            textFormat.setForeground(qcolor)
            docCursor.mergeCharFormat(textFormat)
            edit.setTextCursor(cursor)
            edit.verticalScrollBar().setValue(verticalValue)
            edit.horizontalScrollBar().setValue(horizontalValue)

    def updateDefaultFontColorButton(self, button, color):
        qcolor = QColor(color)
        if qcolor.isValid():
            textColor = self.buttonTextColor(color)
            button.setStyleSheet("background-color: {}; border-color: {}; color: {};".format(color, color, textColor))
        else:
            button.setStyleSheet("")

    def selectDefaultFontColor(self, configKey):
        current = self.config.get(configKey) or ("#1976d2" if configKey == "sendFontColor" else "#2e7d32")
        color = QColorDialog.getColor(QColor(current), self.mainWidget, _("Select color"))
        if not color.isValid():
            return
        self.config[configKey] = color.name()
        if configKey == "receiveFontColor":
            self.updateDefaultFontColorButton(self.receiveFontColorButton, self.config[configKey])
            self.applyReceiveFont()
        else:
            self.updateDefaultFontColorButton(self.sendFontColorButton, self.config[configKey])
            self.applySendFont()
        self.rerenderReceiveArea()

    def selectTimestampColor(self):
        current = self.config.get("timestampColor") or "#6d6d6d"
        color = QColorDialog.getColor(QColor(current), self.mainWidget, _("Select color"))
        if not color.isValid():
            return
        self.config["timestampColor"] = color.name()
        self.updateDefaultFontColorButton(self.timestampColorButton, self.config["timestampColor"])
        self.rerenderReceiveArea()

    def applyReceiveFont(self):
        font = self.receiveArea.currentFont()
        font.setFamily(self.config.get("receiveFontFamily", DEFAULT_TEXT_FONT))
        font.setPointSize(self.config["receiveFontSize"])
        self.receiveArea.setFont(font)
        self.setTextEditPaletteColor(self.receiveArea, self.config["receiveFontColor"])

    def applySendFont(self):
        font = self.sendArea.currentFont()
        font.setFamily(self.config.get("sendFontFamily", DEFAULT_TEXT_FONT))
        font.setPointSize(self.config["sendFontSize"])
        self.sendArea.setFont(font)
        self.setTextEditPaletteColor(self.sendArea, self.config["sendFontColor"], updateDocument=True)

    def changeReceiveFontSize(self, size):
        self.config["receiveFontSize"] = size
        self.applyReceiveFont()
        self.rerenderReceiveArea()

    def changeSendFontSize(self, size):
        self.config["sendFontSize"] = size
        self.config["fontSize"] = size
        self.applySendFont()

    def changeReceiveFontFamily(self, font):
        self.config["receiveFontFamily"] = font.family()
        self.applyReceiveFont()
        self.rerenderReceiveArea()

    def changeSendFontFamily(self, font):
        self.config["sendFontFamily"] = font.family()
        self.applySendFont()

    def onSendSettingsHexClicked(self):
        self.config["sendAscii"] = False
        data = self.sendArea.toPlainText().replace("\n","\r\n")
        data = utils.bytes_to_hex_str(data.encode())
        self.sendArea.clear()
        self.sendArea.insertPlainText(data)

    def onSendSettingsAsciiClicked(self):
        self.config["sendAscii"] = True
        try:
            data = self.sendArea.toPlainText().replace("\n"," ").strip()
            self.sendArea.clear()
            if data != "":
                data = utils.hex_str_to_bytes(data).decode(self.configGlobal["encoding"],'ignore')
                self.sendArea.insertPlainText(data)
        except Exception as e:
            # QMessageBox.information(self,self.strings.strWriteFormatError,self.strings.strWriteFormatError)
            print("format error")

    def onAutoLinefeedClicked(self):
        if (self.config["showTimestamp"] or self.config["recordSend"]) and not self.receiveSettingsAutoLinefeed.isChecked():
            self.receiveSettingsAutoLinefeed.setChecked(True)
            self.hintSignal.emit("warning", _("Warning"), _("linefeed always on if timestamp or record send is on"))
        self.config["receiveAutoLinefeed"] = self.receiveSettingsAutoLinefeed.isChecked()

    def onTimeStampClicked(self):
        self.config["showTimestamp"] = self.receiveSettingsTimestamp.isChecked()
        if self.config["showTimestamp"]:
            self.config["receiveAutoLinefeed"] = True
            self.receiveSettingsAutoLinefeed.setChecked(True)

    def onRecordSendClicked(self):
        self.config["recordSend"] = self.sendSettingsRecord.isChecked()
        if self.config["recordSend"]:
            self.config["receiveAutoLinefeed"] = True
            self.receiveSettingsAutoLinefeed.setChecked(True)

    def onSettingWrap(self):
        self.config["wrap"] = self.receiveSettingsWrap.isChecked()
        self.applyWrapMode()

    def applyWrapMode(self):
        wrap = self.config["wrap"]
        flag = QTextEdit.WidgetWidth if wrap else QTextEdit.NoWrap
        wrapMode = QTextOption.WrapAnywhere if wrap else QTextOption.NoWrap
        self.receiveArea.setLineWrapMode(flag)
        self.receiveArea.setLineWrapColumnOrWidth(0)
        self.receiveArea.setWordWrapMode(wrapMode)
        self.receiveArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if wrap else Qt.ScrollBarAsNeeded)
        option = self.receiveArea.document().defaultTextOption()
        option.setWrapMode(wrapMode)
        self.receiveArea.document().setDefaultTextOption(option)
        self.sendArea.setLineWrapMode(flag)
        self.sendArea.setLineWrapColumnOrWidth(0)
        self.sendArea.setWordWrapMode(wrapMode)
        self.sendArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if wrap else Qt.ScrollBarAsNeeded)

    def onEscapeSendClicked(self):
        self.config["sendEscape"] = self.sendSettingsEscape.isChecked()

    def onSetColorChanged(self):
        self.config["color"] = False

    def onSendHistoryIndexChanged(self, idx):
        self.sendArea.clear()
        self.sendArea.insertPlainText(self.sendHistory.currentText())

    def clearHistory(self):
        self.config["sendHistoryList"].clear()
        self.sendHistory.clear()
        self.hintSignal.emit("info", _("OK"), _("History cleared!"))


    def onSent(self, ok, msg, length, path):
        if ok:
            self.statusBar.addTx(length)
        else:
            self.hintSignal.emit("error", _("Error"), _("Send data failed!") + " " + msg)

    def onSentFile(self, ok, msg, length, path):
        print("file sent {}, path: {}".format('ok' if ok else 'fail', path))
        if ok:
            self.sendFileButton.setText(_("Send file"))
            self.sendFileButton.setDisabled(False)
            self.statusBar.addTx(length)
        else:
            self.hintSignal.emit("error", _("Error"), _("Send file failed!") + " " + msg)

    def setSaveLog(self):
        if self.saveLogCheckbox.isChecked():
            self.config["saveLog"] = True
            self.logStartTime = time.time()
            self.startSaveLogStatus()
            self.startTimedSaveLog()
        else:
            self.config["saveLog"] = False
            self.stopSaveLogStatus()
            self.stopSaveLogTimer()

    def onSaveLogTimedChanged(self):
        self.bindVar(self.saveLogTimed, self.config, "saveLogTimed")
        if self.config["saveLog"]:
            self.startTimedSaveLog()
        else:
            self.stopSaveLogTimer()

    def onSaveLogDurationChanged(self):
        text = self.saveLogDuration.text().strip()
        if not text:
            text = "00:00:00"
        try:
            self.config["saveLogDuration"] = self.parseHmsToSeconds(text)
        except Exception:
            self.saveLogDuration.setText(self.secondsToHms(self.config["saveLogDuration"]))
            self.hintSignal.emit("error", _("Error"), _("Timed log duration error, format: HH:MM:SS"))
            return
        self.saveLogDuration.setText(self.secondsToHms(self.config["saveLogDuration"]))
        if self.config["saveLog"] and self.config["saveLogTimed"]:
            self.startTimedSaveLog()

    def stopSaveLogTimer(self):
        if self.saveLogStopTimer is not None:
            self.saveLogStopTimer.stop()

    def startTimedSaveLog(self):
        if self.saveLogStopTimer is None:
            return
        self.stopSaveLogTimer()
        if not self.config.get("saveLog") or not self.config.get("saveLogTimed"):
            return
        duration = int(self.config.get("saveLogDuration", 60))
        if duration <= 0:
            duration = 1
            self.config["saveLogDuration"] = duration
            self.saveLogDuration.setText(self.secondsToHms(duration))
        self.saveLogStopTimer.start(duration * 1000)

    def stopTimedSaveLog(self):
        self.config["saveLog"] = False
        if hasattr(self, "saveLogCheckbox"):
            self.saveLogCheckbox.setChecked(False)
        self.stopSaveLogStatus()
        self.hintSignal.emit("info", _("OK"), _("Timed log stopped"))

    def secondsToHms(self, seconds):
        seconds = max(0, int(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return "{:02d}:{:02d}:{:02d}".format(h, m, s)

    def parseHmsToSeconds(self, text):
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError(text)
        h, m, s = [int(part) for part in parts]
        if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
            raise ValueError(text)
        return h * 3600 + m * 60 + s

    def formatFileSize(self, size):
        units = ["B", "KB", "MB", "GB"]
        value = float(max(0, size))
        unit = units[0]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                break
            value /= 1024
        if unit == "B":
            return "{} B".format(int(value))
        return "{:.2f} {}".format(value, unit)

    def currentLogPath(self):
        return self.config["saveLogPath2"] if self.config["saveLogAutoNew"] else self.config["saveLogPath"]

    def startSaveLogStatus(self):
        if self.logStartTime is None:
            self.logStartTime = time.time()
        self.updateSaveLogStatus()
        if self.saveLogStatusTimer is not None:
            self.saveLogStatusTimer.start()

    def stopSaveLogStatus(self):
        if self.saveLogStatusTimer is not None:
            self.saveLogStatusTimer.stop()
        self.updateSaveLogStatus()

    def updateSaveLogStatus(self):
        elapsed = 0 if self.logStartTime is None else int(time.time() - self.logStartTime)
        path = self.currentLogPath()
        size = os.path.getsize(path) if path and os.path.exists(path) else 0
        if hasattr(self, "saveLogStatusLabel"):
            self.saveLogStatusLabel.setText("{}: {} / {}".format(_("Log"), self.secondsToHms(elapsed), self.formatFileSize(size)))

    def selectFile(self):
        oldPath = self.filePathWidget.text()
        if oldPath=="":
            oldPath = os.getcwd()
        fileName_choose, filetype = QFileDialog.getOpenFileName(self.mainWidget,
                                    _("Select file"),
                                    oldPath,
                                    _("All Files (*)"))

        if fileName_choose == "":
            return
        self.filePathWidget.setText(fileName_choose)
        self.filePathWidget.setToolTip(fileName_choose)

    def selectLogFile(self):
        oldPath = self.logFilePath.text()
        if oldPath=="":
            oldPath = os.getcwd()
        fileName_choose, filetype = QFileDialog.getSaveFileName(self.mainWidget,
                                    _("Select file"),
                                    os.path.join(oldPath, "comtool.log"),
                                    _("Log file (*.log);;txt file (*.txt);;All Files (*)"))

        if fileName_choose == "":
            return
        self.logFilePath.setText(fileName_choose)
        self.logFilePath.setToolTip(fileName_choose)
        self.config["saveLogPath"] = fileName_choose
        self.config["saveLogPath2"] = fileName_choose

    def updateLogPath(self):
        '''
            update log path add datetiem and com port name
        '''
        if not self.config["saveLogPath"]:
            return
        date = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        path = os.path.splitext(self.config['saveLogPath'])
        self.config["saveLogPath2"] = f"{path[0]}_{date}{path[1]}"


    def onLog(self, text):
        path = self.currentLogPath()
        if self.config["saveLog"] and path:
            with open(path, "a+", encoding=self.configGlobal["encoding"], newline="\n") as f:
                f.write(text)
            self.updateSaveLogStatus()

    def onConnChanged(self, status:ConnectionStatus, msg:str):
        super().onConnChanged(status, msg)
        if status == ConnectionStatus.CONNECTED and self.config["saveLogAutoNew"]:
            self.updateLogPath()
            if self.config["saveLog"]:
                self.logStartTime = time.time()
                self.startSaveLogStatus()

    def onKeyPressEvent(self, event):
        if event.matches(QKeySequence.Find):
            self.openReceiveFindDialog()
            event.accept()
        elif event.key() == Qt.Key_Control:
            self.keyControlPressed = True
        elif event.key() == Qt.Key_Return or event.key()==Qt.Key_Enter:
            if self.keyControlPressed:
                self.onSendData()
        elif event.key() == Qt.Key_L:
            if self.keyControlPressed:
                self.sendArea.clear()
        elif event.key() == Qt.Key_K:
            if self.keyControlPressed:
                self.receiveArea.clear()

    def onKeyReleaseEvent(self, event):
        if event.key() == Qt.Key_Control:
            self.keyControlPressed = False

    def normalizeCustomSendItem(self, item=None):
        if item is None:
            item = {}
        if isinstance(item, dict):
            text = item.get("text", "")
            remark = item.get("remark", "")
            icon = item.get("icon", None)
            highlight = item.get("highlight", False)
            color = item.get("color", "")
        else:
            text = item
            remark = ""
            icon = None
            highlight = False
            color = ""
        if highlight and not color:
            color = "#ffc107"
        return {
            "text": "" if text is None else str(text),
            "remark": "" if remark is None else str(remark),
            "icon": icon or "fa.send",
            "highlight": bool(highlight),
            "color": "" if color is None else str(color)
        }

    def insertSendItem(self, customItem=None, load = False):
        customItem = self.normalizeCustomSendItem(customItem)
        item = CustomSendItemWidget(self)
        layout = QHBoxLayout()
        layout.setContentsMargins(2,2,2,2)
        item.setLayout(layout)
        select = QCheckBox()
        select.setToolTip(_("Select for batch edit"))
        dragHandle = CustomSendDragHandle(item)
        utils_ui.setButtonIcon(dragHandle, "fa.bars")
        dragHandle.setProperty("class", "remark")
        dragHandle.setToolTip(_("Drag before another item to reorder"))
        cmd = QLineEdit(customItem["text"])
        send = QPushButton(customItem["remark"])
        utils_ui.setButtonIcon(send, customItem["icon"])
        colorButton = CustomSendColorButton(self, item, send)
        colorButton.setProperty("class", "remark")
        colorButton.setToolTip(_("Click to set button color, right click to clear"))
        self.updateColorButton(colorButton, customItem["color"])
        editRemark = QPushButton("")
        editRemark.setObjectName("editRemark")
        utils_ui.setButtonIcon(editRemark, "ei.pencil")
        editRemark.setProperty("class", "remark")
        editRemark.setToolTip(_("Edit custom send remark and icon"))
        cmd.setToolTip(customItem["text"])
        send.setToolTip(customItem["text"])
        cmd.textChanged.connect(lambda: self.onCustomItemChange(self.customSendItemsLayout.indexOf(item), cmd, send))
        send.setProperty("class", "smallBtn")
        send.clicked.connect(lambda: self.sendCustomItem(self.config["customSendItems"][self.customSendItemsLayout.indexOf(item)]))
        delete = QPushButton("")
        utils_ui.setButtonIcon(delete, "fa.close")
        delete.setProperty("class", "deleteBtn")
        delete.setToolTip(_("Delete this custom send item"))
        layout.addWidget(select)
        layout.addWidget(dragHandle)
        layout.addWidget(cmd, 3)
        layout.addWidget(send, 2)
        layout.addWidget(colorButton)
        layout.addWidget(editRemark)
        layout.addWidget(delete)
        delete.clicked.connect(lambda: self.deleteSendItem(self.customSendItemsLayout.indexOf(item), item))
        colorButton.clicked.connect(lambda: self.selectCustomItemColor(self.customSendItemsLayout.indexOf(item), item, send, colorButton))
        select.stateChanged.connect(self.updateCustomSendSelectionActions)
        def changeRemark(idx, obj):
            customItem = self.config["customSendItems"][idx]
            ok, remark, icon, _shortcut = EditRemarDialog(
                obj.text(), customItem.get("icon"), shortcut=[], enableShortcut=False).exec()
            if ok:
                obj.setText(remark)
                if icon:
                    utils_ui.setButtonIcon(obj, icon)
                else:
                    obj.setIcon(QIcon())
                self.config["customSendItems"][idx]["remark"] = remark
                self.config["customSendItems"][idx]["icon"] = icon
                self.filterCustomSendItems()
        editRemark.clicked.connect(lambda: changeRemark(self.customSendItemsLayout.indexOf(item), send))
        self.customSendItemsLayout.addWidget(item)
        if not load:
            self.config["customSendItems"].append(customItem)
        item.customSendData = customItem
        item.sendButton = send
        item.colorButton = colorButton
        item.selectCheckBox = select
        self.applyCustomItemColor(item, send, customItem["color"])
        if not load:
            self.filterCustomSendItems()
            QTimer.singleShot(0, self.scrollCustomSendToBottom)
        return customItem

    def deleteSendItem(self, idx, item):
        if idx < 0 or idx >= len(self.config["customSendItems"]):
            return
        if QMessageBox.question(self.funcWidget, _("Delete"), _("Delete selected custom send item?"),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.removeCustomSendItem(idx, item)
        self.filterCustomSendItems()

    def removeCustomSendItem(self, idx, item):
        for obj in item.findChildren(QPushButton):
            utils_ui.clearButtonIcon(obj)
        item.setParent(None)
        item.deleteLater()
        self.config["customSendItems"].pop(idx)
        self.updateCustomSendSelectionActions()

    def onCustomItemChange(self, idx, edit, send):
        text = edit.text()
        edit.setToolTip(text)
        send.setToolTip(text)
        self.config["customSendItems"][idx].update({
            "text": text,
            "remark": send.text()
        })
        self.filterCustomSendItems()

    def sendCustomItem(self, item):
        text = item.get("text", "") if isinstance(item, dict) else item
        self.onSendData(data = text)

    def customSendAdd(self):
        self.insertSendItem()

    def scrollCustomSendToBottom(self):
        if hasattr(self, "customSendScroll"):
            bar = self.customSendScroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def updateColorButton(self, button, color):
        utils_ui.setButtonIcon(button, "fa.paint-brush")
        qcolor = QColor(color)
        if color and qcolor.isValid():
            hoverColor = qcolor.darker(110).name()
            pressedColor = qcolor.darker(135).name()
            button.setStyleSheet(
                "QPushButton {"
                "background-color: %s;"
                "border-color: %s;"
                "}"
                "QPushButton:hover {"
                "background-color: %s;"
                "border-color: %s;"
                "}"
                "QPushButton:pressed {"
                "background-color: %s;"
                "border-color: %s;"
                "}"
                % (color, color, hoverColor, hoverColor, pressedColor, pressedColor)
            )
        else:
            button.setStyleSheet("")

    def buttonTextColor(self, color):
        qcolor = QColor(color)
        if not qcolor.isValid():
            return "white"
        luminance = 0.299 * qcolor.red() + 0.587 * qcolor.green() + 0.114 * qcolor.blue()
        return "black" if luminance > 160 else "white"

    def applyCustomItemColor(self, item, sendButton, color):
        qcolor = QColor(color)
        if color and qcolor.isValid():
            textColor = self.buttonTextColor(color)
            hoverColor = qcolor.darker(110).name()
            pressedColor = qcolor.darker(135).name()
            sendButton.setStyleSheet(
                "QPushButton {"
                "background-color: %s;"
                "border-color: %s;"
                "color: %s;"
                "}"
                "QPushButton:hover {"
                "background-color: %s;"
                "border-color: %s;"
                "}"
                "QPushButton:pressed {"
                "background-color: %s;"
                "border-color: %s;"
                "}"
                % (color, color, textColor, hoverColor, hoverColor, pressedColor, pressedColor)
            )
            item.setStyleSheet(
                "QWidget#customSendItem {"
                "background: rgba(%d, %d, %d, 38);"
                "border: 1px solid %s;"
                "border-radius: 4px;"
                "}"
                % (qcolor.red(), qcolor.green(), qcolor.blue(), color)
            )
        else:
            sendButton.setStyleSheet("")
            item.setStyleSheet(
                "QWidget#customSendItem {"
                "background: transparent;"
                "border: 1px solid transparent;"
                "border-radius: 4px;"
                "}"
            )

    def selectCustomItemColor(self, idx, item, sendButton, colorButton):
        if idx < 0 or idx >= len(self.config["customSendItems"]):
            return
        current = self.config["customSendItems"][idx].get("color") or "#ffc107"
        color = QColorDialog.getColor(QColor(current), self.funcWidget, _("Select color"))
        if color.isValid():
            self.setCustomItemColor(idx, item, sendButton, colorButton, color.name())

    def setCustomItemColor(self, idx, item, sendButton, colorButton, color):
        if idx < 0 or idx >= len(self.config["customSendItems"]):
            return
        self.config["customSendItems"][idx]["color"] = color
        self.config["customSendItems"][idx]["highlight"] = bool(color)
        if hasattr(item, "customSendData"):
            item.customSendData["color"] = color
            item.customSendData["highlight"] = bool(color)
        self.updateColorButton(colorButton, color)
        self.applyCustomItemColor(item, sendButton, color)

    def iterCustomSendWidgets(self):
        for idx in range(self.customSendItemsLayout.count()):
            layoutItem = self.customSendItemsLayout.itemAt(idx)
            widget = layoutItem.widget()
            if widget is not None:
                yield idx, widget

    def selectedCustomSendIndexes(self):
        indexes = []
        for idx, widget in self.iterCustomSendWidgets():
            if hasattr(widget, "selectCheckBox") and widget.selectCheckBox.isChecked():
                indexes.append(idx)
        return indexes

    def updateCustomSendSelectionActions(self):
        if not hasattr(self, "batchCustomSendColorButton"):
            return
        selectedCount = len(self.selectedCustomSendIndexes())
        enabled = selectedCount > 0
        self.batchCustomSendColorButton.setEnabled(enabled)
        self.batchCustomSendIconButton.setEnabled(enabled)
        self.batchCustomSendDeleteButton.setEnabled(enabled)
        if hasattr(self, "customSendSelectAll"):
            visibleWidgets = [widget for _idx, widget in self.iterCustomSendWidgets() if widget.isVisible()]
            checkedWidgets = [widget for widget in visibleWidgets if hasattr(widget, "selectCheckBox") and widget.selectCheckBox.isChecked()]
            self.customSendSelectAll.blockSignals(True)
            self.customSendSelectAll.setChecked(bool(visibleWidgets) and len(visibleWidgets) == len(checkedWidgets))
            self.customSendSelectAll.blockSignals(False)

    def setVisibleCustomSendSelection(self):
        checked = self.customSendSelectAll.isChecked()
        for _idx, widget in self.iterCustomSendWidgets():
            if hasattr(widget, "selectCheckBox") and widget.isVisible():
                widget.selectCheckBox.setChecked(checked)
        self.updateCustomSendSelectionActions()

    def batchSetCustomSendColor(self):
        indexes = self.selectedCustomSendIndexes()
        if not indexes:
            return
        current = self.config["customSendItems"][indexes[0]].get("color") or "#ffc107"
        color = QColorDialog.getColor(QColor(current), self.funcWidget, _("Select color"))
        if not color.isValid():
            return
        for idx in indexes:
            layoutItem = self.customSendItemsLayout.itemAt(idx)
            widget = layoutItem.widget()
            if widget:
                self.setCustomItemColor(idx, widget, widget.sendButton, widget.colorButton, color.name())

    def batchSetCustomSendIcon(self):
        indexes = self.selectedCustomSendIndexes()
        if not indexes:
            return
        icon = selectIcon(parent=self.funcWidget, title=_("Select icon"), btnName=_("OK"), color=utils_ui.getStyleVar("iconSelectorColor"))
        if not icon:
            return
        icon = icon or "fa.send"
        for idx in indexes:
            self.config["customSendItems"][idx]["icon"] = icon
            layoutItem = self.customSendItemsLayout.itemAt(idx)
            widget = layoutItem.widget()
            if widget:
                widget.customSendData["icon"] = icon
                utils_ui.setButtonIcon(widget.sendButton, icon)

    def batchDeleteCustomSendItems(self):
        indexes = self.selectedCustomSendIndexes()
        if not indexes:
            return
        msg = _("Delete selected custom send items?") + " ({})".format(len(indexes))
        if QMessageBox.question(self.funcWidget, _("Delete"), msg,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        for idx in sorted(indexes, reverse=True):
            layoutItem = self.customSendItemsLayout.itemAt(idx)
            widget = layoutItem.widget()
            if widget:
                self.removeCustomSendItem(idx, widget)
        self.filterCustomSendItems()

    def setCustomSendDropTarget(self, item):
        if self.customSendDropTarget is item:
            return
        self.clearCustomSendDropTarget()
        self.customSendDropTarget = item
        item.setMinimumHeight(max(item.sizeHint().height() + 16, parameters.customSendItemHeight + 16))
        item.setStyleSheet(
            "QWidget#customSendItem {"
            "background: rgba(33, 150, 243, 55);"
            "border: 2px solid #2196f3;"
            "border-radius: 4px;"
            "}"
        )

    def clearCustomSendDropTarget(self, item=None):
        if item is not None and self.customSendDropTarget is not item:
            return
        target = self.customSendDropTarget
        self.customSendDropTarget = None
        if target is None:
            return
        target.setMinimumHeight(0)
        color = ""
        if hasattr(target, "customSendData"):
            color = target.customSendData.get("color", "")
        if hasattr(target, "sendButton"):
            self.applyCustomItemColor(target, target.sendButton, color)

    def filterCustomSendItems(self):
        if not hasattr(self, "customSendSearch"):
            return
        keyword = self.customSendSearch.text().strip().lower()
        for idx in range(self.customSendItemsLayout.count()):
            layoutItem = self.customSendItemsLayout.itemAt(idx)
            widget = layoutItem.widget()
            if widget is None or idx >= len(self.config["customSendItems"]):
                continue
            item = self.normalizeCustomSendItem(self.config["customSendItems"][idx])
            text = item.get("text", "")
            remark = item.get("remark", "")
            matched = (not keyword) or keyword in remark.lower() or keyword in text.lower()
            widget.setVisible(matched)
        self.updateCustomSendSelectionActions()

    def refreshCustomSendItems(self):
        items = [item.copy() for item in self.config["customSendItems"]]
        self.loadCustomSendItems(items)
        self.filterCustomSendItems()

    def restoreCustomSendScroll(self, value):
        if not hasattr(self, "customSendScroll"):
            return
        bar = self.customSendScroll.verticalScrollBar()
        bar.setValue(min(value, bar.maximum()))

    def moveCustomSendItemBefore(self, fromIdx, toIdx):
        if fromIdx == toIdx:
            return
        if fromIdx < 0 or toIdx < 0:
            return
        if fromIdx >= len(self.config["customSendItems"]) or toIdx >= len(self.config["customSendItems"]):
            return
        scrollValue = self.customSendScroll.verticalScrollBar().value() if hasattr(self, "customSendScroll") else 0
        items = self.config["customSendItems"]
        item = items.pop(fromIdx)
        if fromIdx < toIdx:
            toIdx -= 1
        items.insert(toIdx, item)
        self.refreshCustomSendItems()
        self.restoreCustomSendScroll(scrollValue)
        QTimer.singleShot(0, lambda value=scrollValue: self.restoreCustomSendScroll(value))

    def clearCustomSendItemsWidgets(self):
        while self.customSendItemsLayout.count():
            layoutItem = self.customSendItemsLayout.takeAt(0)
            widget = layoutItem.widget()
            if widget:
                for obj in widget.findChildren(QPushButton):
                    utils_ui.clearButtonIcon(obj)
                widget.setParent(None)
                widget.deleteLater()

    def loadCustomSendItems(self, items):
        self.clearCustomSendItemsWidgets()
        self.config["customSendItems"] = []
        for item in items:
            normalized = self.insertSendItem(item, load=True)
            self.config["customSendItems"].append(normalized)
        self.filterCustomSendItems()

    def importCustomSendItems(self):
        fileName_choose, filetype = QFileDialog.getOpenFileName(self.funcWidget,
                                    _("Import custom send"),
                                    os.getcwd(),
                                    _("JSON file (*.json);;All Files (*)"))
        if fileName_choose == "":
            return
        try:
            with open(fileName_choose, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "customSendItems" in data:
                data = data["customSendItems"]
            if not isinstance(data, list):
                raise ValueError(_("Custom send file must be a JSON list"))
            self.loadCustomSendItems([self.normalizeCustomSendItem(item) for item in data])
            self.hintSignal.emit("info", _("OK"), _("Custom send items imported!"))
        except Exception as e:
            self.hintSignal.emit("error", _("Error"), _("Import custom send failed!") + " " + str(e))

    def exportCustomSendItems(self):
        fileName_choose, filetype = QFileDialog.getSaveFileName(self.funcWidget,
                                    _("Export custom send"),
                                    os.path.join(os.getcwd(), "custom_send_items.json"),
                                    _("JSON file (*.json);;All Files (*)"))
        if fileName_choose == "":
            return
        try:
            with open(fileName_choose, "w", encoding="utf-8") as f:
                json.dump(self.config["customSendItems"], f, indent=4, ensure_ascii=False)
            self.hintSignal.emit("info", _("OK"), _("Custom send items exported!"))
        except Exception as e:
            self.hintSignal.emit("error", _("Error"), _("Export custom send failed!") + " " + str(e))

    def getSendData(self, data=None) -> bytes:
        if data is None:
            data = self.sendArea.toPlainText()
        return self.parseSendData(data, self.configGlobal["encoding"], self.config["useCRLF"], not self.config["sendAscii"], self.config["sendEscape"])

    def sendFile(self):
        filename = self.filePathWidget.text()
        if not os.path.exists(filename):
            self.hintSignal.emit("error", _("Error"), _("File path error\npath") + ":%s" %(filename))
            return
        if not self.isConnected():
            self.hintSignal.emit("warning", _("Warning"), _("Connect first please"))
        else:
            self.sendFileButton.setDisabled(True)
            self.sendFileButton.setText(_("Sending file"))
            self.send(file_path=filename, callback = lambda ok, msg, length, path: self.onSentFile(ok, msg, length, path))


    def scheduledSend(self):
        self.isScheduledSending = True
        interval = self.config["sendScheduledTime"]
        last_change_interval_time = time.time()
        change_interval_delay = 2 # 2s to take effect after change interval
        while self.config["sendScheduled"] and interval > 0:
            self.onSendData()
            try:
                time.sleep(interval/1000)
                if self.config["sendScheduledTime"] != interval and time.time() - last_change_interval_time > change_interval_delay:
                    last_change_interval_time = time.time()
                    interval = self.config["sendScheduledTime"]
            except Exception:
                self.hintSignal.emit("error", _("Error"), _("Time format error"))
        self.isScheduledSending = False

    def displayLineBreak(self):
        return "\r\n" if self.config["useCRLF"] else "\n"

    def buildRecordHead(self, direction="", showTimestamp=False, isHex=False, leadingLineBreak=False):
        prefix = self.displayLineBreak() if leadingLineBreak else ""
        directionPart = "{} ".format(direction) if direction else ""
        timestampPart = "[{}] ".format(utils.datetime_format_ms(datetime.now())) if showTimestamp else ""
        hexPart = "[HEX] " if isHex else ""
        if showTimestamp and self.config.get("timestampNewline", False):
            firstLine = "{}{}{}".format(prefix, directionPart, timestampPart).rstrip()
            secondLine = "{}{}".format(directionPart, hexPart)
            if isHex:
                secondLine = "{}: ".format(secondLine.rstrip())
            return firstLine + self.displayLineBreak() + secondLine
        head = "{}{}{}{}".format(prefix, directionPart, timestampPart, hexPart)
        if showTimestamp or (direction and isHex):
            head = "{}: ".format(head.rstrip())
        return head

    def sendData(self, data_bytes = None):
        try:
            if self.isConnected():
                if not data_bytes or type(data_bytes) == str:
                    data = self.getSendData(data_bytes)
                else:
                    data = data_bytes
                if not data:
                    return
                if self.config["sendAutoNewline"]:
                    data += b"\r\n" if self.config["useCRLF"] else b"\n"
                # record send data
                if self.config["recordSend"]:
                    isHexStr, sendStr, sendStrsColored = self.bytes2String(data, not self.config["receiveAscii"], encoding=self.configGlobal["encoding"])
                    if isHexStr:
                        sendStr = sendStr.upper()
                    head = self.buildRecordHead("=>", self.config["showTimestamp"], isHexStr, leadingLineBreak=True)
                    self.receiveUpdateSignal.emit(head, [sendStr], self.configGlobal["encoding"], True)
                    self.sendRecord.insert(0, head + sendStr)
                self.send(data_bytes=data, callback = self.onSent)
                self.justSent = True # flag for receive thread
                if data_bytes:
                    data = str(data_bytes)
                else:
                    data = self.sendArea.toPlainText()
                self.sendHistoryFindDelete(data)
                self.sendHistory.insertItem(0,data)
                self.sendHistory.setCurrentIndex(0)
                try:
                    idx = self.config["sendHistoryList"].index(data)
                    self.config["sendHistoryList"].pop(idx)
                except Exception:
                     pass
                self.config["sendHistoryList"].insert(0, data)

                # scheduled send
                if self.config["sendScheduled"]:
                    if not self.isScheduledSending:
                        t = threading.Thread(target=self.scheduledSend)
                        t.setDaemon(True)
                        t.start()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("[Error] sendData: ", e)
            self.hintSignal.emit("error", _("Error"), _("Send Error") + str(e))
            # print(e)

    def onSendData(self, call=True, data=None):
        try:
            self.sendData(data)
        except Exception as e:
            print("[Error] onSendData: ", e)
            self.hintSignal.emit("error", _("Error"), _("get data error") + ": " + str(e))

    def receiveDisplayColor(self, isSend):
        color = self.config["sendFontColor"] if isSend else self.config["receiveFontColor"]
        qcolor = QColor(color)
        return qcolor if qcolor.isValid() else QColor("#1976d2" if isSend else "#2e7d32")

    def timestampDisplayColor(self):
        qcolor = QColor(self.config.get("timestampColor", "#6d6d6d"))
        return qcolor if qcolor.isValid() else QColor("#6d6d6d")

    def receiveDisplayFont(self):
        return QFont(self.config.get("receiveFontFamily", DEFAULT_TEXT_FONT), self.config["receiveFontSize"])

    def insertHeadText(self, cursor, textFormat, head, isSend):
        timestampPattern = re.compile(r"\[\d{4}[^\]]*\]")
        directionColor = self.receiveDisplayColor(isSend)
        timestampColor = self.timestampDisplayColor()
        p = 0
        for match in timestampPattern.finditer(head):
            if match.start() > p:
                textFormat.setForeground(directionColor)
                textFormat.setBackground(self.defaultBg)
                textFormat.setFontWeight(QFont.Bold if isSend else QFont.Normal)
                cursor.setCharFormat(textFormat)
                cursor.insertText(head[p:match.start()])
            textFormat.setForeground(timestampColor)
            textFormat.setBackground(self.defaultBg)
            textFormat.setFontWeight(QFont.Bold if isSend else QFont.Normal)
            cursor.setCharFormat(textFormat)
            cursor.insertText(match.group(0))
            p = match.end()
        if p < len(head):
            textFormat.setForeground(directionColor)
            textFormat.setBackground(self.defaultBg)
            textFormat.setFontWeight(QFont.Bold if isSend else QFont.Normal)
            cursor.setCharFormat(textFormat)
            cursor.insertText(head[p:])

    def appendReceivedDataRecord(self, record, preserveScroll=True):
        datas = record["datas"]
        encoding = record["encoding"]
        isSend = record["isSend"]
        head = record["head"]
        if datas:
            curScrollValue = self.receiveArea.verticalScrollBar().value()
            curHorizontalValue = self.receiveArea.horizontalScrollBar().value()
            self.receiveArea.moveCursor(QTextCursor.End)
            endScrollValue = self.receiveArea.verticalScrollBar().value()
            cursor = self.receiveArea.textCursor()
            format = cursor.charFormat()
            format.setFont(self.receiveDisplayFont())
            if not self.defaultColor:
                self.defaultColor = format.foreground()
            if not self.defaultBg:
                self.defaultBg = format.background()
            directionColor = self.receiveDisplayColor(isSend)
            if head:
                self.insertHeadText(cursor, format, head, isSend)
            format.setFontWeight(QFont.Normal)
            for data in datas:
                if type(data) == str:
                    for color, bg, text in self.splitTextByReceiveFindRules(data):
                        format.setForeground(QColor(color) if color else directionColor)
                        format.setBackground(QColor(bg) if bg else self.defaultBg)
                        cursor.setCharFormat(format)
                        cursor.insertText(text)
                elif type(data) == list:
                    for color, bg, text in data:
                        for segColor, segBg, segText in self.splitTextByReceiveFindRules(text, color, bg):
                            if segColor:
                                format.setForeground(QColor(segColor))
                            else:
                                format.setForeground(directionColor)
                            if segBg:
                                format.setBackground(QColor(segBg))
                            else:
                                format.setBackground(self.defaultBg)
                            cursor.setCharFormat(format)
                            cursor.insertText(segText)
                else: # bytes
                    text = data.decode(encoding=encoding, errors="ignore")
                    for color, bg, text in self.splitTextByReceiveFindRules(text):
                        format.setForeground(QColor(color) if color else directionColor)
                        format.setBackground(QColor(bg) if bg else self.defaultBg)
                        cursor.setCharFormat(format)
                        cursor.insertText(text)
            if preserveScroll and curScrollValue < endScrollValue:
                self.receiveArea.verticalScrollBar().setValue(curScrollValue)
            else:
                self.receiveArea.moveCursor(QTextCursor.End)
            self.receiveArea.horizontalScrollBar().setValue(curHorizontalValue)

    def updateReceivedDataDisplay(self, head : str, datas : list, encoding : str, isSend : bool):
        if not datas:
            return
        record = {
            "head": head,
            "datas": datas,
            "encoding": encoding,
            "isSend": isSend
        }
        self.receiveDisplayRecords.append(record)
        self.appendReceivedDataRecord(record)

    def rerenderReceiveArea(self):
        if not hasattr(self, "receiveArea") or self.rerenderingReceiveArea:
            return
        self.rerenderingReceiveArea = True
        scrollBar = self.receiveArea.verticalScrollBar()
        oldValue = scrollBar.value()
        atEnd = oldValue >= scrollBar.maximum()
        records = list(self.receiveDisplayRecords)
        self.receiveArea.clear()
        self.defaultColor = None
        self.defaultBg = None
        for record in records:
            self.appendReceivedDataRecord(record, preserveScroll=False)
        if atEnd:
            self.receiveArea.moveCursor(QTextCursor.End)
        else:
            scrollBar.setValue(min(oldValue, scrollBar.maximum()))
        self.rerenderingReceiveArea = False

    def sendHistoryFindDelete(self,str):
        self.sendHistory.removeItem(self.sendHistory.findText(str))

    def _getColorByfmt(self, fmt:bytes):
        colors = {
            b"0": None,
            b"30": "#000000",
            b"31": "#f44336",
            b"32": "#4caf50",
            b"33": "#ffa000",
            b"34": "#2196f3",
            b"35": "#e85aad",
            b"36": "#26c6da",
            b"37": "#a1887f",
        }
        bgs = {
            b"0": None,
            b"40": "#000000",
            b"41": "#f44336",
            b"42": "#4caf50",
            b"43": "#ffa000",
            b"44": "#2196f3",
            b"45": "#e85aad",
            b"46": "#26c6da",
            b"47": "#a1887f",
        }
        fmt = fmt[2:-1].split(b";")
        color = colors[b'0']
        bg = bgs[b'0']
        for cmd in fmt:
            if cmd in colors:
                color = colors[cmd]
            if cmd in bgs:
                bg = bgs[cmd]
        return color, bg

    def _texSplitByColor(self, text:bytes):
        remain = b''
        ignoreCodes = [rb'\x1b\[\?.*?h', rb'\x1b\[\?.*?l']
        text = text.replace(b"\x1b[K", b"")
        for code in ignoreCodes:
            colorFmt = re.findall(code, text)
            for fmt in colorFmt:
                text = text.replace(fmt, b"")
        colorFmt = re.findall(rb'\x1b\[.*?m', text)
        if text.endswith(b"\x1b"): # ***\x1b
            text = text[:-1]
            remain = b'\x1b'
        elif text.endswith(b"\x1b["): # ***\x1b[
            text = text[:-2]
            remain = b'\x1b['
        else: # ****\x1b[****, ****\x1b[****;****m
            idx = -2
            idx_remain = -1
            while 1:
                idx = text.find(b"\x1b[", len(text) - 10 + idx + 2) # \x1b[00;00m]
                if idx < 0:
                    break
                remain = text[idx:]
                idx_remain = idx
            if len(remain) > 0:
                match = re.findall(rb'\x1b\[.*?m', remain)  # ****\x1b[****;****m***
                if len(match) > 0: # have full color format
                    remain = b''
                else:
                    text = text[:idx_remain]
        plaintext = text
        for fmt in colorFmt:
            plaintext = plaintext.replace(fmt, b"")
        colorStrs = []
        if colorFmt:
            p = 0
            for fmt in colorFmt:
                idx = text[p:].index(fmt)
                if idx != 0:
                    colorStrs.append([self.lastColor, self.lastBg, text[p:p+idx]])
                    p += idx
                self.lastColor, self.lastBg = self._getColorByfmt(fmt)
                p += len(fmt)
            colorStrs.append([self.lastColor, self.lastBg, text[p:]])
        else:
            colorStrs = [[self.lastColor, self.lastBg, text]]
        return plaintext, colorStrs, remain

    def getColoredText(self, data_bytes, decoding=None, to_bytes_str = True):
        plainText, coloredText, remain = self._texSplitByColor(data_bytes)
        if decoding:
            if to_bytes_str:
                plainText = str(plainText)[2:-1]
            else:
                plainText = plainText.decode(encoding=decoding, errors="ignore")
            decodedColoredText = []
            for color, bg, text in coloredText:
                content = str(text)[2:-1] if to_bytes_str else text.decode(encoding=decoding, errors="ignore")
                decodedColoredText.append([color, bg, content])
            coloredText = decodedColoredText
        return plainText, coloredText, remain

    def bytes2String(self, data : bytes, showAsHex : bool, encoding="utf-8"):
        isHexString = False
        dataColored = None
        if showAsHex:
            return True, utils.hexlify(data, ' ').decode(encoding=encoding), dataColored
        try:
            dataPlain, dataColored, remain = self.getColoredText(data, self.configGlobal["encoding"], self.config["receiveEscape"])
            if remain:
                dataPlain += str(remain)[2:-1] if self.config["receiveEscape"] else remain.decode(encoding=self.configGlobal["encoding"], errors="ignore")
        except Exception:
            dataPlain = utils.hexlify(data, ' ').decode(encoding=encoding)
            isHexString = True
        return isHexString, dataPlain, dataColored

    def clearReceiveBuffer(self):
        self.receiveArea.clear()
        self.receiveDisplayRecords.clear()
        if hasattr(self, "statusBar"):
            self.statusBar.clear()

    def onReceived(self, data : bytes):
        self.lock_op_rx_buff.acquire()
        self.receivedData.append(data)
        self.lock_op_rx_buff.release()
        self.statusBar.addRx(len(data))
        if self.lock_wait_rx.locked():
            self.lock_wait_rx.release()

    def receiveDataProcess(self):
        self.receiveProgressStop = False
        timeLastReceive = 0
        new_line = True
        logData = None
        buffer = b''
        remain = b''
        self.lock_wait_rx.acquire()
        while(not self.receiveProgressStop):
            logData = None
            head = ""
            new = b''
            # ok means got new data
            ok = self.lock_wait_rx.acquire(timeout=max(0.001, self.config["receiveAutoLindefeedTime"] / 1000))
            if (not ok) and len(buffer) == 0:
                continue
            if ok:
                self.lock_op_rx_buff.acquire()
                new = b"".join(self.receivedData)
                buffer += new
                self.receivedData = []
                self.lock_op_rx_buff.release()
            # timeout, add new line
            # self.justSent means just sent data, need show head
            if time.time() - timeLastReceive > self.config["receiveAutoLindefeedTime"] / 1000 or (self.config["recordSend"] and self.justSent):
                if self.config["receiveAutoLinefeed"]:
                    if self.config["useCRLF"]:
                        head += "\r\n"
                    else:
                        head += "\n"
                    new_line = True
                    self.justSent = False
            data = ""
            # have data in buffer
            if len(buffer) > 0:
                hexstr = False
                # show as hex, just show
                if not self.config["receiveAscii"]:
                    data = utils.bytes_to_hex_str(buffer)
                    colorData = data
                    buffer = b''
                    hexstr = True
                # show as string, and don't need to render color
                elif not self.config["color"]:
                    if self.config["receiveEscape"]:
                        data = str(buffer)[2:-1]
                    else:
                        data = buffer.decode(encoding=self.configGlobal["encoding"], errors="ignore")
                    # self.lastShowTail for separated \r\n, prevent show two linefeed
                    # if last msg endswith "\r", and this msg startswith "\n", don't show "\n", if you have different thought, add issue to github
                    if self.lastShowTail == "\r" and data[0] == "\n":
                        data = data[1:]
                    colorData = data
                    buffer = b''
                    if data and data[-1] == "\r":
                        self.lastShowTail = data[-1]
                    else:
                        self.lastShowTail = ""
                # show as string, and need to render color, wait for \n or until timeout to ensure color flag in buffer
                else:
                    if time.time() - timeLastReceive >  self.config["receiveAutoLindefeedTime"] / 1000 or b'\n' in buffer:
                        data, colorData, remain = self.getColoredText(buffer, self.configGlobal["encoding"], to_bytes_str = self.config["receiveEscape"])
                        buffer = remain
                # add time receive head
                # get data from buffer, now render
                if data:
                    # add time header, head format(send receive '123' for example):
                    # '123'  '[2021-12-20 11:02:08.02.754]: 123' '=> 12' '<= 123'
                    # '=> [2021-12-20 11:02:34.02.291]: 123' '<= [2021-12-20 11:02:40.02.783]: 123'
                    # '<= [2021-12-20 11:03:25.03.320] [HEX]: 31 32 33 ' '=> [2021-12-20 11:03:27.03.319] [HEX]: 31 32 33'
                    if new_line:
                        head += self.buildRecordHead("<=" if self.config["recordSend"] else "",
                                                     self.config["showTimestamp"],
                                                     hexstr)
                        new_line = False
                    self.receiveUpdateSignal.emit(head, [colorData], self.configGlobal["encoding"], False)
                    logData = head + data
            if len(new) > 0:
                timeLastReceive = time.time()

            while len(self.sendRecord) > 0:
                self.onLog(self.sendRecord.pop())
            if logData:
                self.onLog(logData)


    def onDel(self):
        self.receiveProgressStop = True
        self.stopSaveLogTimer()
        self.stopSaveLogStatus()

