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
except ImportError:
    from COMTool import parameters,helpAbout,autoUpdate, utils, utils_ui
    from COMTool.Combobox import ComboBox
    from COMTool import i18n
    from COMTool.i18n import _, tr
    from COMTool import version
    from COMTool.conn.base import ConnectionStatus
    from COMTool.widgets import statusBar
    from COMTool.widgets import EditRemarDialog

try:
    from base import Plugin_Base
except Exception:
    from .base import Plugin_Base

from PyQt5.QtCore import pyqtSignal,Qt, QRect, QMargins, QMimeData, QTimer
from PyQt5.QtWidgets import (QApplication, QWidget,QPushButton,QMessageBox,QDesktopWidget,QMainWindow,
                             QVBoxLayout,QHBoxLayout,QGridLayout,QTextEdit,QLabel,QRadioButton,QCheckBox,
                             QLineEdit,QGroupBox,QSplitter,QFileDialog, QScrollArea, QSpinBox, QSizePolicy,
                             QColorDialog)
from PyQt5.QtGui import QIcon,QFont,QTextCursor,QPixmap,QColor, QDrag, QTextOption, QPalette
import qtawesome as qta # https://github.com/spyder-ide/qtawesome
import os, threading, time, re, json
from datetime import datetime


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
            "receiveFontColor": "#2e7d32",
            "sendFontColor": "#1976d2"
        }
        for k in default:
            if not k in self.config:
                self.config[k] = default[k]
        if not hasReceiveFontSize:
            self.config["receiveFontSize"] = 10
        if not hasSendFontSize:
            self.config["sendFontSize"] = existingFontSize
        self.config["fontSize"] = self.config["sendFontSize"]
        self.lastShowTail = ''
        self.justSent = False # sent data before received data flag
        self.customSendDropTarget = None

    def onWidgetMain(self, parent):
        self.mainWidget = QSplitter(Qt.Vertical)
        # widgets receive and send area
        self.receiveArea = QTextEdit()
        font = QFont('Menlo,Consolas,Bitstream Vera Sans Mono,Courier New,monospace, Microsoft YaHei', 10)
        self.receiveArea.setFont(font)
        self.sendArea = QTextEdit()
        self.sendArea.setAcceptRichText(False)
        self.clearReceiveButtion = QPushButton(_("Clear RX"))
        self.clearReceiveButtion.setToolTip(_("Clear receive area"))
        utils_ui.setButtonIcon(self.clearReceiveButtion, "mdi6.broom")
        self.clearSendButtion = QPushButton(_("Clear TX"))
        self.clearSendButtion.setToolTip(_("Clear send input"))
        utils_ui.setButtonIcon(self.clearSendButtion, "mdi6.broom")
        self.sendButton = QPushButton("")
        utils_ui.setButtonIcon(self.sendButton, "fa.send")
        self.sendHistory = ComboBox()
        receiveWidget = QWidget()
        receiveAreaWidgetsLayout = QHBoxLayout()
        receiveAreaWidgetsLayout.setContentsMargins(0,0,0,0)
        receiveWidget.setLayout(receiveAreaWidgetsLayout)
        receiveButtonLayout = QVBoxLayout()
        receiveButtonLayout.addWidget(self.clearReceiveButtion)
        receiveButtonLayout.addStretch(1)
        receiveAreaWidgetsLayout.addWidget(self.receiveArea)
        receiveAreaWidgetsLayout.addLayout(receiveButtonLayout)
        sendWidget = QWidget()
        sendAreaWidgetsLayout = QHBoxLayout()
        sendAreaWidgetsLayout.setContentsMargins(0,4,0,0)
        sendWidget.setLayout(sendAreaWidgetsLayout)
        buttonLayout = QVBoxLayout()
        buttonLayout.addWidget(self.clearSendButtion)
        buttonLayout.addStretch(1)
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
        self.receiveSettingsColor = QCheckBox(_("Color"))
        self.receiveSettingsColor.setToolTip(_("Enable unix terminal color support, e.g. \\33[31;43mhello\\33[0m"))
        self.receiveSettingsWrap = QCheckBox(_("Display wrap"))
        self.receiveEscape = QCheckBox(_("Escape"))
        self.receiveEscape.setToolTip(_("Enable escape characters support like \\t \\r \\n \\x01 \\001"))
        self.receiveSettingsWrap.setToolTip(_("When content in a line is too long, always auto wrap to show, and no scroll bar"))
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAscii,1,0,1,1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsHex,1,1,1,1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAutoLinefeed, 2, 0, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAutoLinefeedTime, 2, 1, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsTimestamp, 3, 0, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsColor, 3, 1, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsWrap, 4, 0, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveEscape, 4, 1, 1, 1)
        serialReceiveSettingsGroupBox.setLayout(serialReceiveSettingsLayout)
        serialReceiveSettingsGroupBox.setAlignment(Qt.AlignHCenter)
        layout.addWidget(serialReceiveSettingsGroupBox)

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
        self.createFunctionalSettings(layout)

        widget = QWidget()
        widget.setLayout(layout)
        layout.setContentsMargins(0,0,0,0)
        # event
        self.receiveSettingsTimestamp.clicked.connect(self.onTimeStampClicked)
        self.receiveSettingsAutoLinefeed.clicked.connect(self.onAutoLinefeedClicked)
        self.receiveSettingsAscii.clicked.connect(lambda : self.switchRxMode(True))
        self.receiveSettingsHex.clicked.connect(lambda : self.switchRxMode(False))
        self.sendSettingsHex.clicked.connect(self.onSendSettingsHexClicked)
        self.sendSettingsAscii.clicked.connect(self.onSendSettingsAsciiClicked)
        self.sendSettingsRecord.clicked.connect(self.onRecordSendClicked)
        self.sendSettingsAppendNewLine.clicked.connect(lambda: self.bindVar(self.sendSettingsAppendNewLine, self.config, "sendAutoNewline"))
        self.sendSettingsEscape.clicked.connect(lambda: self.bindVar(self.sendSettingsEscape, self.config, "sendEscape"))
        self.sendSettingsCRLF.clicked.connect(lambda: self.bindVar(self.sendSettingsCRLF, self.config, "useCRLF"))
        self.receiveSettingsColor.clicked.connect(self.onSetColorChanged)
        self.receiveSettingsAutoLinefeedTime.textChanged.connect(lambda: self.bindVar(self.receiveSettingsAutoLinefeedTime, self.config, "receiveAutoLindefeedTime", vtype=int, vErrorMsg=_("Auto line feed value error, must be integer"), emptyDefault = "200"))
        self.sendSettingsScheduled.textChanged.connect(lambda: self.bindVar(self.sendSettingsScheduled, self.config, "sendScheduledTime", vtype=int, vErrorMsg=_("Timed send value error, must be integer"), emptyDefault = "300"))
        self.sendSettingsScheduledCheckBox.clicked.connect(lambda: self.bindVar(self.sendSettingsScheduledCheckBox, self.config, "sendScheduled"))
        self.receiveSettingsWrap.clicked.connect(self.onSettingWrap)
        self.receiveEscape.clicked.connect(lambda: self.bindVar(self.receiveEscape, self.config, "receiveEscape"))
        self.sendFileButton.clicked.connect(self.sendFile)
        self.saveLogCheckbox.clicked.connect(self.setSaveLog)
        self.logFileBtn.clicked.connect(self.selectLogFile)
        self.saveLogAutoNew.clicked.connect(lambda: self.bindVar(self.saveLogAutoNew, self.config, "saveLogAutoNew"))
        self.openFileButton.clicked.connect(self.selectFile)
        self.clearHistoryButton.clicked.connect(self.clearHistory)
        self.receiveFontSizeInput.valueChanged.connect(self.changeReceiveFontSize)
        self.sendFontSizeInput.valueChanged.connect(self.changeSendFontSize)
        self.receiveFontColorButton.clicked.connect(lambda: self.selectDefaultFontColor("receiveFontColor"))
        self.sendFontColorButton.clicked.connect(lambda: self.selectDefaultFontColor("sendFontColor"))
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
        self.receiveFontSizeInput = NoWheelSpinBox()
        self.receiveFontSizeInput.setRange(1, 100)
        self.receiveFontColorButton = QPushButton(_("Color"))
        self.sendFontSizeInput = NoWheelSpinBox()
        self.sendFontSizeInput.setRange(1, 100)
        self.sendFontColorButton = QPushButton(_("Color"))
        fontSettingsLayout.addWidget(QLabel(_("Receive size")), 0, 0, 1, 1)
        fontSettingsLayout.addWidget(self.receiveFontSizeInput, 0, 1, 1, 1)
        fontSettingsLayout.addWidget(self.receiveFontColorButton, 0, 2, 1, 1)
        fontSettingsLayout.addWidget(QLabel(_("Send size")), 1, 0, 1, 1)
        fontSettingsLayout.addWidget(self.sendFontSizeInput, 1, 1, 1, 1)
        fontSettingsLayout.addWidget(self.sendFontColorButton, 1, 2, 1, 1)
        self.fontSizeInput = self.sendFontSizeInput

        self.filePathWidget = QLineEdit()
        self.openFileButton = QPushButton(_("Open File"))
        self.sendFileButton = QPushButton(_("Send File"))
        self.clearHistoryButton = QPushButton(_("Clear History"))
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
        self.logFilePath = QLineEdit()
        self.logFileBtn = QPushButton(_("Log path"))
        self.saveLogAutoNew = QCheckBox(_("Auto new file"))
        self.saveLogAutoNew.setToolTip(_("When start a new connection, will automatically create a new log file"))
        logFileLayout.addWidget(self.saveLogCheckbox)
        logFileLayout.addWidget(self.logFilePath)
        logFileLayout.addWidget(self.logFileBtn)
        logFileWrapper.addLayout(logFileLayout)
        logFileWrapper.addWidget(self.saveLogAutoNew)
        self.logFileGroupBox.setLayout(logFileWrapper)

        parentLayout.addWidget(self.fontSettingsGroupBox)
        parentLayout.addWidget(self.logFileGroupBox)
        parentLayout.addWidget(self.fileSendGroupBox)
        parentLayout.addWidget(self.clearHistoryButton)

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
        utils_ui.setButtonIcon(self.importCustomSendButton, "fa.folder-open")
        utils_ui.setButtonIcon(self.exportCustomSendButton, "fa.save")
        self.customSendSearch = QLineEdit()
        self.customSendSearch.setClearButtonEnabled(True)
        self.customSendSearch.setPlaceholderText(_("Search remark or command"))
        self.customSendSearch.setToolTip(_("Search custom send items by remark or command"))
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
        self.receiveSettingsColor.setChecked(paramObj["color"])
        # wrap
        self.applyWrapMode()
        # send items
        customSendItems = []
        for item in paramObj["customSendItems"]:
            customSendItems.append(self.insertSendItem(item, load=True))
        paramObj["customSendItems"] = customSendItems
        self.filterCustomSendItems()
        self.receiveFontSizeInput.setValue(paramObj["receiveFontSize"])
        self.sendFontSizeInput.setValue(paramObj["sendFontSize"])
        self.updateDefaultFontColorButton(self.receiveFontColorButton, paramObj["receiveFontColor"])
        self.updateDefaultFontColorButton(self.sendFontColorButton, paramObj["sendFontColor"])
        self.applyReceiveFont()
        self.applySendFont()

        self.receiveProcess = threading.Thread(target=self.receiveDataProcess)
        self.receiveProcess.setDaemon(True)
        self.receiveProcess.start()

    def setTextEditPaletteColor(self, edit, color):
        qcolor = QColor(color)
        if not qcolor.isValid():
            return
        palette = edit.palette()
        palette.setColor(QPalette.Text, qcolor)
        edit.setPalette(palette)
        edit.setTextColor(qcolor)

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

    def applyReceiveFont(self):
        font = self.receiveArea.currentFont()
        font.setPointSize(self.config["receiveFontSize"])
        self.receiveArea.setFont(font)
        self.setTextEditPaletteColor(self.receiveArea, self.config["receiveFontColor"])

    def applySendFont(self):
        font = self.sendArea.currentFont()
        font.setPointSize(self.config["sendFontSize"])
        self.sendArea.setFont(font)
        self.setTextEditPaletteColor(self.sendArea, self.config["sendFontColor"])

    def changeReceiveFontSize(self, size):
        self.config["receiveFontSize"] = size
        self.applyReceiveFont()

    def changeSendFontSize(self, size):
        self.config["sendFontSize"] = size
        self.config["fontSize"] = size
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
        self.receiveArea.setWordWrapMode(wrapMode)
        self.sendArea.setLineWrapMode(flag)
        self.sendArea.setWordWrapMode(wrapMode)

    def onEscapeSendClicked(self):
        self.config["sendEscape"] = self.sendSettingsEscape.isChecked()

    def onSetColorChanged(self):
        self.config["color"] = self.receiveSettingsColor.isChecked()

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
        else:
            self.config["saveLog"] = False

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
        path = self.config["saveLogPath2"] if self.config["saveLogAutoNew"] else self.config["saveLogPath"]
        if self.config["saveLog"] and path:
            with open(path, "a+", encoding=self.configGlobal["encoding"], newline="\n") as f:
                f.write(text)

    def onConnChanged(self, status:ConnectionStatus, msg:str):
        super().onConnChanged(status, msg)
        if status == ConnectionStatus.CONNECTED and self.config["saveLogAutoNew"]:
            self.updateLogPath()

    def onKeyPressEvent(self, event):
        if event.key() == Qt.Key_Control:
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
        cmd.setToolTip(customItem["text"])
        send.setToolTip(customItem["text"])
        cmd.textChanged.connect(lambda: self.onCustomItemChange(self.customSendItemsLayout.indexOf(item), cmd, send))
        send.setProperty("class", "smallBtn")
        send.clicked.connect(lambda: self.sendCustomItem(self.config["customSendItems"][self.customSendItemsLayout.indexOf(item)]))
        delete = QPushButton("")
        utils_ui.setButtonIcon(delete, "fa.close")
        delete.setProperty("class", "deleteBtn")
        layout.addWidget(dragHandle)
        layout.addWidget(cmd, 3)
        layout.addWidget(send, 2)
        layout.addWidget(colorButton)
        layout.addWidget(editRemark)
        layout.addWidget(delete)
        delete.clicked.connect(lambda: self.deleteSendItem(self.customSendItemsLayout.indexOf(item), item))
        colorButton.clicked.connect(lambda: self.selectCustomItemColor(self.customSendItemsLayout.indexOf(item), item, send, colorButton))
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
        self.applyCustomItemColor(item, send, customItem["color"])
        if not load:
            self.filterCustomSendItems()
            QTimer.singleShot(0, self.scrollCustomSendToBottom)
        return customItem

    def deleteSendItem(self, idx, item):
        for obj in item.findChildren(QPushButton):
            utils_ui.clearButtonIcon(obj)
        item.setParent(None)
        self.config["customSendItems"].pop(idx)
        self.filterCustomSendItems()

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
                    head = '=> '
                    if self.config["showTimestamp"]:
                        head += '[{}] '.format(utils.datetime_format_ms(datetime.now()))
                    isHexStr, sendStr, sendStrsColored = self.bytes2String(data, not self.config["receiveAscii"], encoding=self.configGlobal["encoding"])
                    if isHexStr:
                        sendStr = sendStr.upper()
                        head += "[HEX] "
                    if self.config["useCRLF"]:
                        head = "\r\n" + head
                    else:
                        head = "\n" + head
                    if head.strip() != '=>':
                        head = '{}: '.format(head.rstrip())
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

    def updateReceivedDataDisplay(self, head : str, datas : list, encoding : str, isSend : bool):
        if datas:
            curScrollValue = self.receiveArea.verticalScrollBar().value()
            self.receiveArea.moveCursor(QTextCursor.End)
            endScrollValue = self.receiveArea.verticalScrollBar().value()
            cursor = self.receiveArea.textCursor()
            format = cursor.charFormat()
            font = QFont('Menlo,Consolas,Bitstream Vera Sans Mono,Courier New,monospace, Microsoft YaHei', self.config["receiveFontSize"])
            format.setFont(font)
            if not self.defaultColor:
                self.defaultColor = format.foreground()
            if not self.defaultBg:
                self.defaultBg = format.background()
            directionColor = self.receiveDisplayColor(isSend)
            if head:
                format.setForeground(directionColor)
                format.setBackground(self.defaultBg)
                format.setFontWeight(QFont.Bold if isSend else QFont.Normal)
                cursor.setCharFormat(format)
                cursor.insertText(head)
            format.setFontWeight(QFont.Normal)
            for data in datas:
                if type(data) == str:
                    format.setForeground(directionColor)
                    format.setBackground(self.defaultBg)
                    cursor.setCharFormat(format)
                    cursor.insertText(data)
                elif type(data) == list:
                    for color, bg, text in data:
                        if color:
                            format.setForeground(QColor(color))
                            cursor.setCharFormat(format)
                        else:
                            format.setForeground(directionColor)
                            cursor.setCharFormat(format)
                        if bg:
                            format.setBackground(QColor(bg))
                            cursor.setCharFormat(format)
                        else:
                            format.setBackground(self.defaultBg)
                            cursor.setCharFormat(format)
                        cursor.insertText(text)
                else: # bytes
                    format.setForeground(directionColor)
                    format.setBackground(self.defaultBg)
                    cursor.setCharFormat(format)
                    cursor.insertText(data.decode(encoding=encoding, errors="ignore"))
            if curScrollValue < endScrollValue:
                self.receiveArea.verticalScrollBar().setValue(curScrollValue)
            else:
                self.receiveArea.moveCursor(QTextCursor.End)

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
                        timeNow = '[{}] '.format(utils.datetime_format_ms(datetime.now()))
                        if self.config["recordSend"]:
                            head += "<= "
                        if self.config["showTimestamp"]:
                            head += timeNow
                            head = '{} '.format(head.rstrip())
                        if hexstr:
                            head += "[HEX] "
                        if (self.config["recordSend"] or self.config["showTimestamp"]) and not head.endswith("<= "):
                            head = head[:-1] + ": "
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

