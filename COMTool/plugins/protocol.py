
from PyQt5.QtCore import QObject, Qt, pyqtSignal, QEvent, QTimer
from PyQt5.QtWidgets import (QApplication, QWidget,QPushButton,QMessageBox,QDesktopWidget,QMainWindow,
                             QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QRadioButton,QCheckBox,
                             QLineEdit,QGroupBox,QSplitter,QFileDialog, QScrollArea, QInputDialog, QDialog,
                             QSizePolicy, QTextEdit, QColorDialog)
from PyQt5.QtGui import QIcon,QFont,QTextCursor,QPixmap,QColor, QFontMetricsF, QKeySequence, QFocusEvent, QPalette, QTextOption
import qtawesome as qta # https://github.com/spyder-ide/qtawesome

try:
    import parameters
    from Combobox import ComboBox
    from i18n import _
    from widgets import TextEdit, PlainTextEdit
    import utils, utils_ui
    from widgets import statusBar
    from widgets import EditRemarDialog
    from conn.base import ConnectionStatus
    from qta_icon_browser import selectIcon
except ImportError:
    from COMTool import parameters, utils, utils_ui
    from COMTool.i18n import _
    from COMTool.Combobox import ComboBox
    from COMTool.widgets import TextEdit, PlainTextEdit
    from COMTool.widgets import statusBar
    from COMTool.widgets import EditRemarDialog
    from COMTool.conn.base import ConnectionStatus
    from COMTool.qta_icon_browser import selectIcon

try:
    from base import Plugin_Base
    import crc
    from protocols import defaultProtocols
    from protocol_capture import DataCaptureWidget, defaultCaptureConfig
    from dbg import (AsyncTextFileWriter, CommandSequenceDialog, CustomSendColorButton, CustomSendDragHandle, CustomSendItemWidget,
                     FindMarkerScrollBar, LogSettingsDialog, NoWheelFontComboBox,
                     NoWheelSpinBox, ReceiveFindDialog, WrapRemarkButton, DEFAULT_TEXT_FONT)
except Exception:
    from .base import Plugin_Base
    from . import crc
    from .protocols import defaultProtocols
    from .protocol_capture import DataCaptureWidget, defaultCaptureConfig
    from .dbg import (AsyncTextFileWriter, CommandSequenceDialog, CustomSendColorButton, CustomSendDragHandle, CustomSendItemWidget,
                      FindMarkerScrollBar, LogSettingsDialog, NoWheelFontComboBox,
                      NoWheelSpinBox, ReceiveFindDialog, WrapRemarkButton, DEFAULT_TEXT_FONT)

import os, json, time, re, threading
from datetime import datetime
from struct import unpack, pack


class Plugin(Plugin_Base):
    '''
        call sequence:
            set vars like hintSignal, hintSignal
            onInit
            onWidget
            onUiInitDone
                send
                onReceived
            getConfig
    '''
    # vars set by caller
    isConnected = lambda : False
    send = lambda x,y:None          # send(data_bytes=None, file_path=None, callback=lambda ok,msg:None)
    hintSignal = None               # hintSignal.emit(type(error, warning, info), title, msg)
    configGlobal = {}
    # other vars
    connParent = "dbg"       # parent id
    connChilds = []          # children ids
    id = "protocol"
    name = _("protocol")

    enabled = False          # user enabled this plugin
    active  = False          # using this plugin

    showReceiveDataSignal = pyqtSignal(str)
    commandSequenceFinishedSignal = pyqtSignal()

    help = '''<h2>{}</h2><p>{}</p><h3>{}</h3><p>{}</p><pre>{}</pre>'''.format(
        _("Protocol page"),
        _("Use Python encode/decode scripts and Multi-channel Data Capture to transform serial data, keep raw logs, and extract live table/curve data."),
        _("Multi-channel Data Capture script"),
        _("Define tables, columns, plots, and parse(line, ctx). Return None to ignore, a dict with table, or list[dict] for multi-channel rows."),
'''import re
tables = [{"id": "BAT1", "title": "Battery 1"}]
columns = ["time", "voltage", "current", "temperature", "soc"]
plots = [{"title": "Voltage", "y": ["BAT1.voltage"]}]
pattern = re.compile(r"BAT1 V=(?P<voltage>-?\\d+\\.?\\d*) I=(?P<current>-?\\d+\\.?\\d*) T=(?P<temperature>-?\\d+\\.?\\d*) SOC=(?P<soc>-?\\d+\\.?\\d*)")

def parse(line, ctx):
    m = pattern.search(line)
    if not m:
        return None
    return {
        "table": "BAT1",
        "voltage": float(m.group("voltage")),
        "current": float(m.group("current")),
        "temperature": float(m.group("temperature")),
        "soc": float(m.group("soc")),
    }'''
    )

    def __init__(self):
        super().__init__()
        if not self.id:
            raise ValueError(f"var id of Plugin {self} should be set")

    def onInit(self, config):
        '''
            init params, DO NOT take too long time in this func
        '''
        default = {
            "version": 1,
            "receiveAscii" : True,
            "receiveAutoLinefeed" : False,
            "receiveAutoLindefeedTime" : 200,
            "sendAscii" : True,
            "sendScheduled" : False,
            "sendScheduledTime" : 300,
            "sendAutoNewline": False,
            "useCRLF" : False,
            "sendRecord" : False,
            "recordSend" : False,
            "sendEscape" : True,
            "receiveEscape" : False,
            "receiveShowNonPrintableHex": False,
            "showTimestamp" : False,
            "timestampColor": "#6d6d6d",
            "timestampNewline": False,
            "wrap": False,
            "saveLogPath" : "",
            "saveLogPath2" : "",
            "saveLog" : False,
            "saveLogTimed": False,
            "saveLogDuration": 60,
            "saveLogAppendInfo": False,
            "saveLogAppendInfoItems": {},
            "saveLogAutoNew": False,
            "color" : False,
            "fontSize": 10,
            "receiveFontSize": 10,
            "sendFontSize": 10,
            "receiveFontFamily": DEFAULT_TEXT_FONT,
            "sendFontFamily": DEFAULT_TEXT_FONT,
            "receiveFontColor": "#2e7d32",
            "sendFontColor": "#1976d2",
            "receiveBufferSizeKB": 4096,
            "sendHistoryList" : [],
            "code": defaultProtocols.copy(),
            "currCode": "default",
            "dataCapture": defaultCaptureConfig(),
            "receiveFindRules": [],
            "customSendItems": [],
            "commandSequenceItems": [],
            "commandSequenceLoop": False,
            "commandSequences": [],
            "commandSequenceCurrent": ""
        }
        self.config = config
        for k in default:
            if not k in self.config:
                self.config[k] = default[k]
        captureDefault = defaultCaptureConfig()
        if not isinstance(self.config["dataCapture"], dict):
            self.config["dataCapture"] = captureDefault
        else:
            for k in captureDefault:
                if not k in self.config["dataCapture"]:
                    self.config["dataCapture"][k] = captureDefault[k]
        self.editingDefaults = False
        self.config["recordSend"] = bool(self.config.get("recordSend", self.config.get("sendRecord", False)))
        self.config["sendRecord"] = self.config["recordSend"]
        self.config["saveLog"] = False
        self.config["saveLogAutoNew"] = False
        self.normalizeLogAppendInfoItems()
        self.codeGlobals = {"unpack": unpack, "pack": pack, "crc": crc, "encoding": self.configGlobal["encoding"], "print": self.print}
        self.encodeMethod = lambda x:x
        self.decodeMethod = lambda x:x
        self.pressedKeys = []
        self.keyModeClickTime = 0
        self.dataCaptureWidget = None
        self.receiveFindDialog = None
        self.receiveFindRuleErrors = set()
        self.receiveFindMarkerTimer = None
        self.receiveDisplayRecords = []
        self.receiveClearRecords = []
        self.rerenderingReceiveArea = False
        self.defaultColor = None
        self.defaultBg = None
        self.lastColor = None
        self.lastBg = None
        self.customSendDropTarget = None
        self.isScheduledSending = False
        self.captureLocked = False
        self.currentConnStatus = ConnectionStatus.CLOSED
        self.logStartTime = None
        self.logSessionActive = False
        self.logPaused = False
        self.logSessionPath = ""
        self.logSessionStartDt = None
        self.logPauseStartTime = None
        self.logPauseStartDt = None
        self.logPausePeriods = []
        self.logConnectionEvents = []
        self.logTimedDeadline = None
        self.logTimedRemaining = None
        self.logLastSize = 0
        self.logWriter = AsyncTextFileWriter(self.configGlobal["encoding"])
        self.saveLogStopTimer = None
        self.saveLogStatusTimer = None
        self.sendRecord = []
        self.commandSequenceSending = False
        self.commandSequenceStop = False

    def print(self, *args, **kw_args):
        end = "\n"
        start = "[MSG]: "
        if "end" in kw_args:
            end = kw_args["end"]
        if "start" in kw_args:
            start = kw_args["start"]
        string = start  + " ".join(map(str, args)) + end
        self.showReceiveDataSignal.emit(string)


    class ModeButton(QPushButton):
        onFocusIn = pyqtSignal(QFocusEvent)
        onFocusOut = pyqtSignal(QFocusEvent)

        def __init__(self, text, eventFilter, parent = None) -> None:
            super().__init__(text, parent)
            self.installEventFilter(eventFilter)

        def focusInEvent(self, event):
            self.onFocusIn.emit(event)

        def focusOutEvent(self, event):
            self.onFocusOut.emit(event)

    def onWidgetMain(self, parent):
        self.mainWidget = QSplitter(Qt.Vertical)
        self.receiveWidget = TextEdit()
        self.receiveArea = self.receiveWidget
        self.receiveWidget.setReadOnly(True)
        self.receiveWidget.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        font = QFont('Menlo,Consolas,Bitstream Vera Sans Mono,Courier New,monospace, Microsoft YaHei', 10)
        self.receiveWidget.setFont(font)
        self.receiveWidget.setLineWrapMode(TextEdit.NoWrap)
        self.receiveFindScrollBar = FindMarkerScrollBar(Qt.Vertical, self.receiveWidget)
        self.receiveWidget.setVerticalScrollBar(self.receiveFindScrollBar)
        self.clearBtn = QPushButton("")
        self.clearBtn.setToolTip(_("Clear receive area"))
        utils_ui.setButtonIcon(self.clearBtn, "mdi6.broom")
        self.receiveFindButton = QPushButton("")
        self.receiveFindButton.setToolTip(_("Find and highlight receive text"))
        utils_ui.setButtonIcon(self.receiveFindButton, "fa.search")
        self.receiveScrollBottomButton = QPushButton("")
        self.receiveScrollBottomButton.setToolTip(_("Scroll receive area to bottom"))
        utils_ui.setButtonIcon(self.receiveScrollBottomButton, "fa.arrow-down")
        for button in [self.receiveFindButton, self.receiveScrollBottomButton, self.clearBtn]:
            button.setMinimumWidth(260)
            button.setMaximumWidth(260)
        receiveWidget = QWidget()
        receiveLayout = QHBoxLayout()
        receiveLayout.setContentsMargins(0,0,0,0)
        receiveWidget.setLayout(receiveLayout)
        receiveButtonLayout = QVBoxLayout()
        receiveButtonLayout.addWidget(self.receiveFindButton)
        receiveButtonLayout.addWidget(self.receiveScrollBottomButton)
        receiveButtonLayout.addWidget(self.clearBtn)
        receiveButtonLayout.addStretch(1)
        receiveLayout.addWidget(self.receiveWidget)
        receiveLayout.addLayout(receiveButtonLayout)
        self.dataCaptureWidget = DataCaptureWidget(self.config["dataCapture"], self.hintSignal, self.configGlobal["encoding"], pageTitle=getattr(self, "pageName", self.name))

        self.mainWidget.addWidget(receiveWidget)
        self.mainWidget.addWidget(self.dataCaptureWidget)
        self.mainWidget.setStretchFactor(0, 5)
        self.mainWidget.setStretchFactor(1, 4)
        # event
        def clearReceived():
            self.recordReceiveClear()
            self.receiveWidget.clear()
            self.receiveDisplayRecords.clear()
            self.receiveFindScrollBar.setMarkers([])
            self.statusBar.clear()
        self.clearBtn.clicked.connect(clearReceived)
        self.receiveFindButton.clicked.connect(self.openReceiveFindDialog)
        self.receiveScrollBottomButton.clicked.connect(self.scrollReceiveToBottom)
        self.dataCaptureWidget.captureActiveChanged.connect(self.setCaptureLocked)
        if self.receiveFindMarkerTimer is None:
            self.receiveFindMarkerTimer = QTimer(self)
            self.receiveFindMarkerTimer.setSingleShot(True)
            self.receiveFindMarkerTimer.timeout.connect(self.updateReceiveFindMarkers)
        self.setCaptureLocked(self.dataCaptureWidget.isSessionActive())
        return self.mainWidget

    def onWidgetSettings(self, parent):
        rootLayout = QVBoxLayout()

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
        self.receiveSettingsWrap = QCheckBox(_("Display wrap"))
        self.receiveEscape = QCheckBox(_("Escape"))
        self.receiveEscape.setToolTip(_("Enable escape characters support like \\t \\r \\n \\x01 \\001"))
        self.receiveShowNonPrintableHex = QCheckBox(_("HEX for non-ASCII"))
        self.receiveShowNonPrintableHex.setToolTip(_("In ASCII receive mode, show bytes without printable ASCII characters as \\xNN"))
        self.receiveSettingsWrap.setToolTip(_("When content in a line is too long, always auto wrap to show, and no scroll bar"))
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAscii,1,0,1,1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsHex,1,1,1,1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAutoLinefeed, 2, 0, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsAutoLinefeedTime, 2, 1, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveSettingsWrap, 3, 0, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveEscape, 3, 1, 1, 1)
        serialReceiveSettingsLayout.addWidget(self.receiveShowNonPrintableHex, 4, 0, 1, 2)
        serialReceiveSettingsGroupBox.setLayout(serialReceiveSettingsLayout)
        serialReceiveSettingsGroupBox.setAlignment(Qt.AlignHCenter)
        rootLayout.addWidget(serialReceiveSettingsGroupBox)

        timestampSettingsLayout = QGridLayout()
        timestampSettingsGroupBox = QGroupBox(_("Timestamp"))
        self.receiveSettingsTimestamp = QCheckBox(_("Timestamp"))
        self.receiveSettingsTimestamp.setToolTip(_("Add timestamp before received data, will automatically enable auto line feed"))
        self.timestampColorButton = QPushButton(_("Color"))
        self.timestampColorButton.setToolTip(_("Timestamp color in receive area"))
        self.timestampNewlineCheckbox = QCheckBox(_("Newline after timestamp"))
        self.timestampNewlineCheckbox.setToolTip(_("Display received data on the next line after timestamp"))
        timestampSettingsLayout.addWidget(self.receiveSettingsTimestamp, 0, 0, 1, 2)
        timestampSettingsLayout.addWidget(QLabel(_("Timestamp color")), 1, 0, 1, 1)
        timestampSettingsLayout.addWidget(self.timestampColorButton, 1, 1, 1, 1)
        timestampSettingsLayout.addWidget(self.timestampNewlineCheckbox, 2, 0, 1, 2)
        timestampSettingsGroupBox.setLayout(timestampSettingsLayout)
        rootLayout.addWidget(timestampSettingsGroupBox)

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
        serialSendSettingsLayout.addWidget(self.sendSettingsRecord, 4, 1, 1, 1)
        serialSendSettingsGroupBox.setLayout(serialSendSettingsLayout)
        rootLayout.addWidget(serialSendSettingsGroupBox)

        self.createFunctionalSettings(rootLayout)

        sendContentGroup = QGroupBox(_("Send content"))
        sendContentLayout = QGridLayout()
        sendContentGroup.setLayout(sendContentLayout)
        self.sendArea = TextEdit()
        self.sendArea.setAcceptRichText(False)
        self.sendArea.setToolTip(_("Input data to send"))
        self.sendArea.setMinimumHeight(120)
        self.commandSequenceBar = self.createCommandSequenceBar()
        self.sendButton = QPushButton(_("Send"))
        self.sendButton.setToolTip(_("Send"))
        self.clearSendButton = QPushButton(_("Clear"))
        self.clearSendButton.setToolTip(_("Clear send input"))
        sendButtonLayout = QHBoxLayout()
        sendButtonLayout.addWidget(self.clearSendButton)
        sendButtonLayout.addWidget(self.sendButton)
        sendContentLayout.addWidget(self.commandSequenceBar, 0, 0, 1, 1)
        sendContentLayout.addWidget(self.sendArea, 1, 0, 1, 1)
        sendContentLayout.addLayout(sendButtonLayout, 2, 0, 1, 1)
        rootLayout.addWidget(sendContentGroup)

        root = QWidget()
        root.setLayout(rootLayout)
        rootLayout.setContentsMargins(0,0,0,0)
        # event
        self.receiveSettingsTimestamp.clicked.connect(self.onTimeStampClicked)
        self.timestampNewlineCheckbox.clicked.connect(lambda: self.bindVar(self.timestampNewlineCheckbox, self.config, "timestampNewline"))
        self.timestampColorButton.clicked.connect(self.selectTimestampColor)
        self.receiveSettingsAutoLinefeed.clicked.connect(self.onAutoLinefeedClicked)
        self.receiveSettingsAscii.clicked.connect(lambda : self.switchRxMode(True))
        self.receiveSettingsHex.clicked.connect(lambda : self.switchRxMode(False))
        self.receiveShowNonPrintableHex.clicked.connect(lambda: self.bindVar(self.receiveShowNonPrintableHex, self.config, "receiveShowNonPrintableHex"))
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
        self.sendButton.clicked.connect(self.onSendData)
        self.clearSendButton.clicked.connect(self.sendArea.clear)
        self.logFileBtn.clicked.connect(self.selectLogFile)
        self.logFilePath.editingFinished.connect(self.onLogFilePathChanged)
        self.saveLogStartButton.clicked.connect(self.toggleSaveLogRecording)
        self.saveLogStopButton.clicked.connect(self.confirmStopSaveLog)
        self.logMoreSettingsButton.clicked.connect(self.openLogSettingsDialog)
        self.receiveFontSizeInput.valueChanged.connect(self.changeReceiveFontSize)
        self.sendFontSizeInput.valueChanged.connect(self.changeSendFontSize)
        self.receiveBufferSizeInput.valueChanged.connect(self.changeReceiveBufferSize)
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
        return root

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

        self.logFileGroupBox = QGroupBox(_("Log"))
        logFileWrapper = QVBoxLayout()
        logFileLayout = QHBoxLayout()
        self.logFilePath = QLineEdit()
        self.logFilePath.setToolTip(_("Log file path"))
        self.logFileBtn = QPushButton(_("Log path"))
        self.logFileBtn.setToolTip(_("Select log file path"))
        self.saveLogStartButton = QPushButton(_("Start record"))
        self.saveLogStartButton.setToolTip(_("Start or pause log recording"))
        self.saveLogStopButton = QPushButton(_("Stop record"))
        self.saveLogStopButton.setToolTip(_("Stop log recording"))
        self.saveLogStopButton.setEnabled(False)
        self.logMoreSettingsButton = QPushButton(_("More log settings"))
        self.logMoreSettingsButton.setToolTip(_("Configure auto new file, timed log, and log information summary"))
        self.logSettingsSummaryLabel = QLabel("")
        self.logSettingsSummaryLabel.setWordWrap(True)
        self.logSettingsSummaryLabel.setToolTip(_("Current log settings"))
        self.saveLogStatusLabel = QLabel(_("Log: 00:00:00 / 0 B"))
        self.saveLogStatusLabel.setToolTip(_("Current log recording duration and file size"))
        self.logFileGroupBox.setLayout(logFileWrapper)
        self.rxBufferGroupBox = QGroupBox(_("RX buffer size"))
        rxBufferLayout = QHBoxLayout()
        self.receiveBufferSizeInput = NoWheelSpinBox()
        self.receiveBufferSizeInput.setRange(64, 1048576)
        self.receiveBufferSizeInput.setSingleStep(64)
        self.receiveBufferSizeInput.setSuffix(" KB")
        self.receiveBufferSizeInput.setToolTip(_("RX buffer size, only editable while the connection is closed"))
        rxBufferLayout.addWidget(self.receiveBufferSizeInput)
        rxBufferLayout.addStretch(1)
        self.rxBufferGroupBox.setLayout(rxBufferLayout)
        logFileLayout.addWidget(self.logFilePath)
        logFileLayout.addWidget(self.logFileBtn)
        logControlLayout = QHBoxLayout()
        logControlLayout.addWidget(self.saveLogStartButton)
        logControlLayout.addWidget(self.saveLogStopButton)
        logFileWrapper.addLayout(logFileLayout)
        logFileWrapper.addLayout(logControlLayout)
        logFileWrapper.addWidget(self.logMoreSettingsButton)
        logFileWrapper.addWidget(self.logSettingsSummaryLabel)
        logFileWrapper.addWidget(self.saveLogStatusLabel)
        parentLayout.addWidget(self.fontSettingsGroupBox)
        parentLayout.addWidget(self.logFileGroupBox)
        parentLayout.addWidget(self.rxBufferGroupBox)

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
        self.customSendComboButton = QPushButton(_("Combo"))
        self.batchCustomSendColorButton.setToolTip(_("Set color for selected custom send items"))
        self.batchCustomSendIconButton.setToolTip(_("Set icon for selected custom send items"))
        self.batchCustomSendDeleteButton.setToolTip(_("Delete selected custom send items"))
        self.customSendComboButton.setToolTip(_("Build a combo command from selected custom send items"))
        utils_ui.setButtonIcon(self.batchCustomSendColorButton, "fa.paint-brush")
        utils_ui.setButtonIcon(self.batchCustomSendIconButton, "fa.send")
        utils_ui.setButtonIcon(self.batchCustomSendDeleteButton, "fa.trash")
        utils_ui.setButtonIcon(self.customSendComboButton, "fa.list")
        self.batchCustomSendDeleteButton.setProperty("class", "deleteBtn")
        customSendGroupBox = QGroupBox(_("Cutom send"))
        customSendItemsLayout0 = QVBoxLayout()
        customSendItemsLayout0.setContentsMargins(0,8,0,0)
        customSendGroupBox.setLayout(customSendItemsLayout0)
        self.customSendScroll = QScrollArea()
        self.customSendScroll.setMinimumHeight(320)
        self.customSendScroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.customSendScroll.setWidgetResizable(True)
        self.customSendScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        customSendItemsLayout0.addWidget(self.customSendSearch)
        customSendBatchLayout = QHBoxLayout()
        customSendBatchLayout.setContentsMargins(0,0,0,0)
        customSendBatchLayout.addWidget(self.customSendSelectAll)
        customSendBatchLayout.addWidget(self.batchCustomSendColorButton)
        customSendBatchLayout.addWidget(self.batchCustomSendIconButton)
        customSendBatchLayout.addWidget(self.batchCustomSendDeleteButton)
        customSendBatchLayout.addWidget(self.customSendComboButton)
        customSendItemsLayout0.addLayout(customSendBatchLayout)
        customSendItemsLayout0.addWidget(self.customSendScroll)

        cutomSendItemsWraper = QWidget()
        customSendItemsLayoutWrapper = QVBoxLayout()
        customSendItemsLayoutWrapper.setContentsMargins(0,0,0,0)
        cutomSendItemsWraper.setLayout(customSendItemsLayoutWrapper)
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
        self.customSendScroll.setWidget(cutomSendItemsWraper)
        self.customSendScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sendFunctionalLayout.addWidget(customSendGroupBox, 1)
        self.funcWidget = QWidget()
        self.funcWidget.setMinimumWidth(360)
        self.funcWidget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.funcWidget.setLayout(sendFunctionalLayout)
        self.addButton.clicked.connect(self.customSendAdd)
        self.importCustomSendButton.clicked.connect(self.importCustomSendItems)
        self.exportCustomSendButton.clicked.connect(self.exportCustomSendItems)
        self.customSendSearch.textChanged.connect(self.filterCustomSendItems)
        self.customSendSelectAll.clicked.connect(self.setVisibleCustomSendSelection)
        self.batchCustomSendColorButton.clicked.connect(self.batchSetCustomSendColor)
        self.batchCustomSendIconButton.clicked.connect(self.batchSetCustomSendIcon)
        self.batchCustomSendDeleteButton.clicked.connect(self.batchDeleteCustomSendItems)
        self.customSendComboButton.clicked.connect(self.openCommandSequenceDialog)
        self.funcParent = parent
        return self.funcWidget

    def onFunctionalWidgetDefaultVisible(self):
        return True

    def onConfigButtonsInSettings(self):
        return True

    def onSettingsWidgetScrollTogether(self):
        return True

    def onWidgetStatusBar(self, parent):
        self.statusBar = statusBar(rxTxCount=True)
        return self.statusBar

    def onUiInitDone(self):
        '''
            UI init done, you can update your widget here
            this method runs in UI thread, do not block too long
        '''
        paramObj = self.config
        self.receiveSettingsHex.setChecked(not paramObj["receiveAscii"])
        self.receiveEscape.setDisabled(not paramObj["receiveAscii"])
        self.receiveShowNonPrintableHex.setDisabled(not paramObj["receiveAscii"])
        self.receiveSettingsAutoLinefeed.setChecked(paramObj["receiveAutoLinefeed"])
        self.receiveEscape.setChecked(paramObj["receiveEscape"])
        self.receiveShowNonPrintableHex.setChecked(paramObj.get("receiveShowNonPrintableHex", False))
        try:
            interval = int(paramObj["receiveAutoLindefeedTime"])
            paramObj["receiveAutoLindefeedTime"] = interval
        except Exception:
            interval = 200
            paramObj["receiveAutoLindefeedTime"] = interval
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
            paramObj["sendScheduledTime"] = interval
        self.sendSettingsScheduled.setText(str(interval))
        self.sendSettingsCRLF.setChecked(paramObj["useCRLF"])
        self.sendSettingsAppendNewLine.setChecked(paramObj["sendAutoNewline"])
        self.sendSettingsRecord.setChecked(paramObj["recordSend"])
        self.sendSettingsEscape.setChecked(paramObj["sendEscape"])
        self.logFilePath.setText(paramObj["saveLogPath"])
        self.logFilePath.setToolTip(paramObj["saveLogPath"])
        paramObj["saveLog"] = False
        try:
            duration = int(paramObj["saveLogDuration"])
            paramObj["saveLogDuration"] = duration
        except Exception:
            duration = 60
            paramObj["saveLogDuration"] = duration
        self.updateLogSettingsSummary()
        self.updateSaveLogButtons()
        self.updateSaveLogStatus()
        self.applyWrapMode()
        newItems = []
        for item in self.config["customSendItems"]:
            item = self.insertSendItem(item, load=True)
            newItems.append(item)
        self.config["customSendItems"] = newItems
        self.filterCustomSendItems()
        self.normalizeCommandSequences()
        self.updateCommandSequenceBar()
        self.receiveFontFamilyInput.setCurrentFont(QFont(paramObj["receiveFontFamily"]))
        self.sendFontFamilyInput.setCurrentFont(QFont(paramObj["sendFontFamily"]))
        self.receiveFontSizeInput.setValue(paramObj["receiveFontSize"])
        self.sendFontSizeInput.setValue(paramObj["sendFontSize"])
        try:
            paramObj["receiveBufferSizeKB"] = int(paramObj["receiveBufferSizeKB"])
        except Exception:
            paramObj["receiveBufferSizeKB"] = 4096
        self.receiveBufferSizeInput.setValue(paramObj["receiveBufferSizeKB"])
        self.updateDefaultFontColorButton(self.receiveFontColorButton, paramObj["receiveFontColor"])
        self.updateDefaultFontColorButton(self.sendFontColorButton, paramObj["sendFontColor"])
        self.applyReceiveFont()
        self.applySendFont()
        self.showReceiveDataSignal.connect(self.showReceivedData)
        self.config["receiveFindRules"] = [
            self.normalizeReceiveFindRule(rule)
            for rule in self.config.get("receiveFindRules", [])
        ]
        self.updateClosedOnlyControls()
        # init decoder and encoder
        name = self.config["currCode"]
        if name not in self.config["code"]:
            name = "default"
        self.config["currCode"] = name
        ok, encode, decode = self.getEnDecodeMethod(self.config["code"].get(name, defaultProtocols["default"]))
        if ok:
            self.encodeMethod = encode
            self.decodeMethod = decode
        self.setCaptureLocked(getattr(self, "captureLocked", False) or self.dataCaptureWidget.isSessionActive())

    class ModeButtonEventFilter(QObject):
        def __init__(self, keyPressCb, keyReleaseCb) -> None:
            super().__init__()
            self.keyPressCb = keyPressCb
            self.keyReleaseCb = keyReleaseCb

        def eventFilter(self, obj, evt):
            if evt.type() == QEvent.KeyPress:
                # prevent default key events
                self.keyPressCb(evt)
                return True
            elif evt.type() == QEvent.KeyRelease:
                self.keyReleaseCb(evt)
                return True
            return False

    def onModeBtnKeyPressEvent(self, event):
        # send by shortcut
        key = event.key()
        self.pressedKeys.append(key)
        for item in self.config["customSendItems"]:
            if not "shortcut" in item:
                continue
            shortcut = item["shortcut"]
            if len(shortcut) == len(self.pressedKeys):
                same = True
                for i in range(len(shortcut)):
                    if shortcut[i][0] != self.pressedKeys[i]:
                        same = False
                        break
                if same:
                    self.sendCustomItem(item)

    def onModeBtnKeyReleaseEvent(self, event):
        key = event.key()
        if key in self.pressedKeys:
            self.pressedKeys.remove(key)

    def onKeyPressEvent(self, event):
        if event.matches(QKeySequence.Find):
            self.openReceiveFindDialog()
            event.accept()

    def onKeyReleaseEvent(self, event):
        pass

    def setPageName(self, name):
        self.pageName = name
        if self.dataCaptureWidget is not None:
            self.dataCaptureWidget.pageTitle = name

    def onSettingWrap(self):
        self.config["wrap"] = self.receiveSettingsWrap.isChecked()
        self.applyWrapMode()

    def switchRxMode(self, ascii):
        if ascii:
            self.receiveSettingsAscii.setChecked(True)
            self.config["receiveAscii"] = True
            self.receiveEscape.setDisabled(False)
            self.receiveShowNonPrintableHex.setDisabled(False)
        else:
            self.receiveSettingsHex.setChecked(True)
            self.config["receiveAscii"] = False
            self.receiveEscape.setDisabled(True)
            self.receiveShowNonPrintableHex.setDisabled(True)

    def createCommandSequenceBar(self):
        bar = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 4)
        bar.setLayout(layout)
        self.commandSequenceSelector = ComboBox()
        self.commandSequenceSelector.setToolTip(_("Select combo command"))
        self.commandSequenceLabel = QLabel("")
        self.commandSequenceLabel.setToolTip(_("Current combo command"))
        self.commandSequenceEditButton = QPushButton(_("Edit combo"))
        self.commandSequenceSendButton = QPushButton(_("Send combo"))
        self.commandSequenceClearButton = QPushButton(_("Clear combo"))
        self.commandSequenceEditButton.setToolTip(_("Edit combo command order and delays"))
        self.commandSequenceSendButton.setToolTip(_("Send combo command in order"))
        self.commandSequenceClearButton.setToolTip(_("Clear current combo command"))
        utils_ui.setButtonIcon(self.commandSequenceEditButton, "ei.pencil")
        utils_ui.setButtonIcon(self.commandSequenceSendButton, "fa.play")
        utils_ui.setButtonIcon(self.commandSequenceClearButton, "fa.close")
        layout.addWidget(QLabel(_("Combo command")))
        layout.addWidget(self.commandSequenceSelector)
        layout.addWidget(self.commandSequenceLabel, 1)
        layout.addWidget(self.commandSequenceEditButton)
        layout.addWidget(self.commandSequenceSendButton)
        layout.addWidget(self.commandSequenceClearButton)
        self.commandSequenceSelector.currentIndexChanged.connect(self.onCommandSequenceSelected)
        self.commandSequenceEditButton.clicked.connect(self.openCommandSequenceDialog)
        self.commandSequenceSendButton.clicked.connect(self.startCommandSequence)
        self.commandSequenceClearButton.clicked.connect(self.clearCommandSequence)
        self.commandSequenceFinishedSignal.connect(self.updateCommandSequenceBar)
        bar.hide()
        return bar

    def normalizeCommandSequenceItem(self, item=None):
        if item is None:
            item = {}
        if isinstance(item, dict):
            text = item.get("text", "")
            remark = item.get("remark", "")
            delay = item.get("delay", 0)
        else:
            text = str(item)
            remark = ""
            delay = 0
        try:
            delay = max(0, int(delay))
        except Exception:
            delay = 0
        return {
            "text": "" if text is None else str(text),
            "remark": "" if remark is None else str(remark),
            "delay": delay
        }

    def commandSequenceFromSelectedItems(self):
        sequence = []
        for idx in self.selectedCustomSendIndexes():
            if idx < 0 or idx >= len(self.config["customSendItems"]):
                continue
            item = self.normalizeCustomSendItem(self.config["customSendItems"][idx])
            sequence.append(self.normalizeCommandSequenceItem({
                "text": item.get("text", ""),
                "remark": item.get("remark", ""),
                "delay": 0
            }))
        return sequence

    def nextCommandSequenceName(self):
        sequences = self.config.get("commandSequences", [])
        base = _("Combo command")
        names = set()
        if isinstance(sequences, list):
            for sequence in sequences:
                if isinstance(sequence, dict):
                    names.add(str(sequence.get("name", "")))
        if base not in names:
            return base
        idx = 2
        while "{} {}".format(base, idx) in names:
            idx += 1
        return "{} {}".format(base, idx)

    def normalizeCommandSequences(self):
        normalizedSequences = []
        rawSequences = self.config.get("commandSequences", [])
        if isinstance(rawSequences, list):
            for sequence in rawSequences:
                if not isinstance(sequence, dict):
                    continue
                items = []
                for item in sequence.get("items", []):
                    normalizedItem = self.normalizeCommandSequenceItem(item)
                    if normalizedItem.get("text"):
                        items.append(normalizedItem)
                if not items:
                    continue
                name = str(sequence.get("name", "")).strip() or "{} {}".format(_("Combo command"), len(normalizedSequences) + 1)
                normalizedSequences.append({
                    "name": name,
                    "items": items,
                    "loop": bool(sequence.get("loop", False))
                })
        legacy = self.config.get("commandSequenceItems", [])
        if legacy and not normalizedSequences:
            items = []
            for item in legacy:
                normalizedItem = self.normalizeCommandSequenceItem(item)
                if normalizedItem.get("text"):
                    items.append(normalizedItem)
            if items:
                normalizedSequences.append({
                    "name": self.config.get("commandSequenceCurrent") or _("Combo command"),
                    "items": items,
                    "loop": bool(self.config.get("commandSequenceLoop", False))
                })
        self.config["commandSequences"] = normalizedSequences
        current = self.config.get("commandSequenceCurrent", "")
        names = [sequence["name"] for sequence in normalizedSequences]
        if names and current not in names:
            self.config["commandSequenceCurrent"] = names[0]
        elif not names:
            self.config["commandSequenceCurrent"] = ""
        currentSequence = self.currentCommandSequence()
        self.config["commandSequenceItems"] = currentSequence.get("items", []) if currentSequence else []
        self.config["commandSequenceLoop"] = currentSequence.get("loop", False) if currentSequence else False

    def normalizeCommandSequencesNoLegacy(self):
        if not isinstance(self.config.get("commandSequences", []), list):
            self.config["commandSequences"] = []

    def currentCommandSequence(self):
        self.normalizeCommandSequencesNoLegacy()
        sequences = self.config.get("commandSequences", [])
        current = self.config.get("commandSequenceCurrent", "")
        for sequence in sequences:
            if sequence.get("name") == current:
                return sequence
        return sequences[0] if sequences else None

    def updateCommandSequenceSelector(self):
        if not hasattr(self, "commandSequenceSelector"):
            return
        self.normalizeCommandSequencesNoLegacy()
        current = self.config.get("commandSequenceCurrent", "")
        self.commandSequenceSelector.blockSignals(True)
        self.commandSequenceSelector.clear()
        currentIndex = -1
        for idx, sequence in enumerate(self.config.get("commandSequences", [])):
            self.commandSequenceSelector.addItem(sequence.get("name", _("Combo command")))
            if sequence.get("name") == current:
                currentIndex = idx
        if currentIndex >= 0:
            self.commandSequenceSelector.setCurrentIndex(currentIndex)
        self.commandSequenceSelector.blockSignals(False)

    def onCommandSequenceSelected(self, idx):
        sequences = self.config.get("commandSequences", [])
        if idx < 0 or idx >= len(sequences):
            return
        self.config["commandSequenceCurrent"] = sequences[idx].get("name", "")
        self.config["commandSequenceItems"] = sequences[idx].get("items", [])
        self.config["commandSequenceLoop"] = bool(sequences[idx].get("loop", False))
        self.updateCommandSequenceBar()

    def setCommandSequence(self, sequence, name=None, loop=False):
        normalized = []
        for item in sequence:
            normalizedItem = self.normalizeCommandSequenceItem(item)
            if normalizedItem.get("text"):
                normalized.append(normalizedItem)
        if not normalized:
            return
        self.normalizeCommandSequences()
        name = (name or self.config.get("commandSequenceCurrent") or self.nextCommandSequenceName()).strip()
        updated = False
        for sequenceObj in self.config["commandSequences"]:
            if sequenceObj.get("name") == name:
                sequenceObj["items"] = normalized
                sequenceObj["loop"] = bool(loop)
                updated = True
                break
        if not updated:
            self.config["commandSequences"].append({
                "name": name,
                "items": normalized,
                "loop": bool(loop)
            })
        self.config["commandSequenceCurrent"] = name
        self.config["commandSequenceItems"] = normalized
        self.config["commandSequenceLoop"] = bool(loop)
        self.updateCommandSequenceBar()

    def commandSequenceSummary(self):
        sequenceObj = self.currentCommandSequence()
        if not sequenceObj:
            return ""
        sequence = sequenceObj.get("items", [])
        names = []
        for item in sequence[:3]:
            names.append(item.get("remark") or item.get("text") or _("Command"))
        if len(sequence) > 3:
            names.append("...")
        loopText = _("Loop") if sequenceObj.get("loop", False) else _("Once")
        return "{} [{}]: {} ({})".format(sequenceObj.get("name", _("Combo command")), loopText, " -> ".join(names), len(sequence))

    def updateCommandSequenceBar(self):
        if not hasattr(self, "commandSequenceBar"):
            return
        self.updateCommandSequenceSelector()
        summary = self.commandSequenceSummary()
        if summary:
            self.commandSequenceLabel.setText(summary)
            self.commandSequenceLabel.setToolTip(summary)
            if self.commandSequenceSending:
                self.commandSequenceSendButton.setText(_("Stop combo"))
                self.commandSequenceSendButton.setToolTip(_("Stop combo command sending"))
                utils_ui.setButtonIcon(self.commandSequenceSendButton, "fa.stop")
            else:
                self.commandSequenceSendButton.setText(_("Send combo"))
                self.commandSequenceSendButton.setToolTip(_("Send combo command in order"))
                utils_ui.setButtonIcon(self.commandSequenceSendButton, "fa.play")
            self.commandSequenceBar.show()
        else:
            self.commandSequenceLabel.setText("")
            self.commandSequenceBar.hide()

    def openCommandSequenceDialog(self):
        selected = self.commandSequenceFromSelectedItems()
        currentSequence = self.currentCommandSequence()
        sequence = selected or (currentSequence.get("items", []) if currentSequence else [])
        if not sequence:
            self.hintSignal.emit("warning", _("Warning"), _("Select custom send items first"))
            return
        dialog = CommandSequenceDialog(
            self,
            sequence,
            self.mainWidget,
            currentSequence.get("name", "") if currentSequence else self.nextCommandSequenceName(),
            currentSequence.get("loop", False) if currentSequence else False
        )
        dialog.exec()

    def clearCommandSequence(self):
        current = self.config.get("commandSequenceCurrent", "")
        self.config["commandSequences"] = [
            sequence for sequence in self.config.get("commandSequences", [])
            if sequence.get("name") != current
        ]
        self.config["commandSequenceItems"] = []
        self.config["commandSequenceLoop"] = False
        self.normalizeCommandSequences()
        self.updateCommandSequenceBar()

    def stopCommandSequence(self):
        self.commandSequenceStop = True
        self.updateCommandSequenceBar()

    def startCommandSequence(self):
        if self.commandSequenceSending:
            self.stopCommandSequence()
            return
        sequenceObj = self.currentCommandSequence()
        if sequenceObj is None:
            self.normalizeCommandSequences()
            sequenceObj = self.currentCommandSequence()
        sequence = []
        for item in sequenceObj.get("items", []) if sequenceObj else []:
            normalizedItem = self.normalizeCommandSequenceItem(item)
            if normalizedItem.get("text"):
                sequence.append(normalizedItem)
        if not sequence:
            self.hintSignal.emit("warning", _("Warning"), _("No command in combo"))
            return
        self.commandSequenceSending = True
        self.commandSequenceStop = False
        self.updateCommandSequenceBar()
        t = threading.Thread(target=self.commandSequenceSendProcess, args=(sequence, bool(sequenceObj.get("loop", False))))
        t.setDaemon(True)
        t.start()

    def commandSequenceDelay(self, delayMs):
        endAt = time.time() + max(0, int(delayMs)) / 1000
        while not self.commandSequenceStop and time.time() < endAt:
            time.sleep(min(0.05, max(0, endAt - time.time())))

    def commandSequenceSendProcess(self, sequence, loop=False):
        try:
            while not self.commandSequenceStop:
                for item in sequence:
                    if self.commandSequenceStop:
                        break
                    self.onSendData(data=item.get("text", ""))
                    delay = int(item.get("delay", 0))
                    if delay > 0:
                        self.commandSequenceDelay(delay)
                if not loop:
                    break
        finally:
            self.commandSequenceSending = False
            self.commandSequenceStop = False
            self.commandSequenceFinishedSignal.emit()

    def onSendSettingsHexClicked(self):
        if not self.config.get("sendAscii", True):
            self.sendSettingsHex.setChecked(True)
            return
        self.config["sendAscii"] = False
        data = self.sendArea.toPlainText().replace("\n","\r\n")
        data = utils.bytes_to_hex_str(data.encode(self.configGlobal["encoding"], errors="ignore"))
        self.sendArea.clear()
        self.sendArea.insertPlainText(data)

    def onSendSettingsAsciiClicked(self):
        if self.config.get("sendAscii", True):
            self.sendSettingsAscii.setChecked(True)
            return
        self.config["sendAscii"] = True
        try:
            data = self.sendArea.toPlainText().replace("\n"," ").strip()
            self.sendArea.clear()
            if data != "":
                data = utils.hex_str_to_bytes(data).decode(self.configGlobal["encoding"],'ignore')
                self.sendArea.insertPlainText(data)
        except Exception:
            self.hintSignal.emit("error", _("Error"), _("Format error, should be like 00 01 02 03"))

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
        self.config["sendRecord"] = self.config["recordSend"]
        if self.config["recordSend"]:
            self.config["receiveAutoLinefeed"] = True
            self.receiveSettingsAutoLinefeed.setChecked(True)

    def applyWrapMode(self):
        wrap = self.config["wrap"]
        flag = QTextEdit.WidgetWidth if wrap else QTextEdit.NoWrap
        wrapMode = QTextOption.WrapAnywhere if wrap else QTextOption.NoWrap
        self.receiveWidget.setLineWrapMode(flag)
        self.receiveWidget.setLineWrapColumnOrWidth(0)
        self.receiveWidget.setWordWrapMode(wrapMode)
        self.receiveWidget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if wrap else Qt.ScrollBarAsNeeded)
        option = self.receiveWidget.document().defaultTextOption()
        option.setWrapMode(wrapMode)
        self.receiveWidget.document().setDefaultTextOption(option)
        if hasattr(self, "sendArea"):
            self.sendArea.setLineWrapMode(flag)
            self.sendArea.setLineWrapColumnOrWidth(0)
            self.sendArea.setWordWrapMode(wrapMode)
            self.sendArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if wrap else Qt.ScrollBarAsNeeded)

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
            self.rerenderReceiveArea()
        else:
            self.updateDefaultFontColorButton(self.sendFontColorButton, self.config[configKey])
            self.applySendFont()

    def selectTimestampColor(self):
        current = self.config.get("timestampColor") or "#6d6d6d"
        color = QColorDialog.getColor(QColor(current), self.mainWidget, _("Select color"))
        if not color.isValid():
            return
        self.config["timestampColor"] = color.name()
        self.updateDefaultFontColorButton(self.timestampColorButton, self.config["timestampColor"])
        self.rerenderReceiveArea()

    def isConnectionClosed(self):
        return self.currentConnStatus == ConnectionStatus.CLOSED

    def setCaptureLocked(self, locked):
        self.captureLocked = bool(locked)
        controls = [
            "clearBtn",
            "receiveSettingsAscii",
            "receiveSettingsHex",
            "receiveSettingsAutoLinefeed",
            "receiveSettingsAutoLinefeedTime",
            "receiveSettingsWrap",
            "receiveEscape",
            "receiveShowNonPrintableHex",
            "receiveSettingsTimestamp",
            "timestampNewlineCheckbox",
            "sendSettingsAscii",
            "sendSettingsHex",
            "sendSettingsScheduledCheckBox",
            "sendSettingsScheduled",
            "sendSettingsCRLF",
            "sendSettingsRecord",
            "sendSettingsEscape",
            "sendSettingsAppendNewLine",
            "sendArea",
            "sendButton",
            "clearSendButton",
            "receiveFontFamilyInput",
            "receiveFontSizeInput",
            "sendFontFamilyInput",
            "sendFontSizeInput",
            "sendFontColorButton",
            "customSendSearch",
            "customSendSelectAll",
            "batchCustomSendColorButton",
            "batchCustomSendIconButton",
            "batchCustomSendDeleteButton",
            "importCustomSendButton",
            "exportCustomSendButton",
            "addButton",
        ]
        for name in controls:
            obj = getattr(self, name, None)
            if obj is not None:
                obj.setEnabled(not self.captureLocked)
        self.setCustomSendLocked(self.captureLocked)
        self.updateClosedOnlyControls()

    def setCustomSendLocked(self, locked):
        if not hasattr(self, "customSendScroll"):
            return
        for widgetClass in (QLineEdit, QPushButton, QCheckBox):
            for widget in self.customSendScroll.findChildren(widgetClass):
                widget.setEnabled(not locked)

    def updateClosedOnlyControls(self):
        closed = self.isConnectionClosed() and not self.captureLocked
        for obj in [
            getattr(self, "receiveFontSizeInput", None),
            getattr(self, "sendFontSizeInput", None),
            getattr(self, "receiveBufferSizeInput", None)
        ]:
            if obj is not None:
                obj.setEnabled(closed)

    def resetSpinBoxValue(self, spinBox, value):
        spinBox.blockSignals(True)
        spinBox.setValue(value)
        spinBox.blockSignals(False)

    def applyReceiveFont(self):
        font = self.receiveWidget.currentFont()
        font.setFamily(self.config.get("receiveFontFamily", DEFAULT_TEXT_FONT))
        font.setPointSize(self.config["receiveFontSize"])
        self.receiveWidget.setFont(font)
        self.defaultColor = None
        self.defaultBg = None
        self.setTextEditPaletteColor(self.receiveWidget, self.config["receiveFontColor"], updateDocument=True)

    def applySendFont(self):
        font = QFont(self.config.get("sendFontFamily", DEFAULT_TEXT_FONT), self.config["sendFontSize"])
        if hasattr(self, "sendArea"):
            self.sendArea.setFont(font)
            self.setTextEditPaletteColor(self.sendArea, self.config["sendFontColor"], updateDocument=True)
        if hasattr(self, "customSendScroll"):
            for edit in self.customSendScroll.findChildren(QLineEdit):
                edit.setFont(font)

    def changeReceiveFontSize(self, size):
        if not self.isConnectionClosed():
            self.resetSpinBoxValue(self.receiveFontSizeInput, self.config["receiveFontSize"])
            return
        self.config["receiveFontSize"] = size
        self.applyReceiveFont()
        self.rerenderReceiveArea()

    def changeSendFontSize(self, size):
        if not self.isConnectionClosed():
            self.resetSpinBoxValue(self.sendFontSizeInput, self.config["sendFontSize"])
            return
        self.config["sendFontSize"] = size
        self.config["fontSize"] = size
        self.applySendFont()

    def changeReceiveBufferSize(self, size):
        if not self.isConnectionClosed():
            self.resetSpinBoxValue(self.receiveBufferSizeInput, self.config["receiveBufferSizeKB"])
            return
        self.config["receiveBufferSizeKB"] = size
        if self.trimReceiveDisplayRecords():
            self.rerenderReceiveArea()

    def changeReceiveFontFamily(self, font):
        self.config["receiveFontFamily"] = font.family()
        self.applyReceiveFont()
        self.rerenderReceiveArea()

    def changeSendFontFamily(self, font):
        self.config["sendFontFamily"] = font.family()
        self.applySendFont()

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
        dragHandle.setToolTip(_("Drag before another item to reorder; double click to move this item to top"))
        cmd = QLineEdit(customItem["text"])
        send = WrapRemarkButton(customItem["remark"])
        utils_ui.setButtonIcon(send, customItem["icon"])
        send.updateWrappedText()
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
                "QPushButton {background-color: %s;border-color: %s;}"
                "QPushButton:hover {background-color: %s;border-color: %s;}"
                "QPushButton:pressed {background-color: %s;border-color: %s;}"
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
                "QPushButton {background-color: %s;border-color: %s;color: %s;}"
                "QPushButton:hover {background-color: %s;border-color: %s;}"
                "QPushButton:pressed {background-color: %s;border-color: %s;}"
                % (color, color, textColor, hoverColor, hoverColor, pressedColor, pressedColor)
            )
            item.setStyleSheet(
                "QWidget#customSendItem {background: rgba(%d, %d, %d, 38);border: 1px solid %s;border-radius: 4px;}"
                % (qcolor.red(), qcolor.green(), qcolor.blue(), color)
            )
        else:
            sendButton.setStyleSheet("")
            item.setStyleSheet("QWidget#customSendItem {background: transparent;border: 1px solid transparent;border-radius: 4px;}")

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
        if hasattr(self, "customSendComboButton"):
            self.customSendComboButton.setEnabled(enabled)
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
        item.setStyleSheet("QWidget#customSendItem {background: rgba(33, 150, 243, 55);border: 2px solid #2196f3;border-radius: 4px;}")

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
        if fromIdx == toIdx or fromIdx < 0 or toIdx < 0:
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
        fileName_choose, _filetype = QFileDialog.getOpenFileName(self.funcWidget,
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
        fileName_choose, _filetype = QFileDialog.getSaveFileName(self.funcWidget,
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

    def normalizeLogAppendInfoItems(self):
        defaults = {key: True for key, _label in self.logAppendInfoOptions()}
        value = self.config.get("saveLogAppendInfoItems", {})
        if not isinstance(value, dict):
            value = {}
        defaults.update({key: bool(value.get(key, defaults.get(key, True))) for key in defaults})
        self.config["saveLogAppendInfoItems"] = defaults

    def logAppendInfoOptions(self):
        return [
            ("startTime", _("Start time")),
            ("endTime", _("End time")),
            ("activeDuration", _("Active duration")),
            ("pauseCount", _("Pause count")),
            ("pauseTime", _("Pause time")),
            ("logSize", _("Log size")),
            ("logPath", _("Log path")),
            ("pageName", _("Page name")),
            ("connectionType", _("Connection type")),
            ("connectionStatus", _("Connection status")),
            ("connectionSettings", _("Connection settings")),
            ("portOpenCloseHistory", _("Port open/close history")),
            ("portDropReconnectHistory", _("Port disconnect/reconnect history")),
            ("receiveClearHistory", _("Receive clear history")),
        ]

    def logAppendInfoEnabled(self, key):
        return bool(self.config.get("saveLogAppendInfoItems", {}).get(key, True))

    def recordReceiveClear(self):
        self.receiveClearRecords.append(datetime.now())

    def formatReceiveClearRecordLines(self, title):
        lines = ["{}:".format(title)]
        if not self.receiveClearRecords:
            lines.append("  - {}".format(_("No receive clear records")))
            return lines
        for clearDt in self.receiveClearRecords:
            lines.append("  - {}: {}".format(self.formatLogDateTime(clearDt), _("Receive area cleared")))
        return lines

    def globalConfigValue(self, key, default=None):
        config = self.configGlobal
        if hasattr(config, "get"):
            return config.get(key, default)
        try:
            return config[key]
        except Exception:
            return default

    def updateLogSettingsSummary(self):
        if not hasattr(self, "logSettingsSummaryLabel"):
            return
        items = [
            "{}: {}".format(_("Timed log"), self.secondsToHms(self.config.get("saveLogDuration", 60)) if self.config.get("saveLogTimed", False) else _("Off")),
            "{}: {}".format(_("Append info"), _("On") if self.config.get("saveLogAppendInfo", False) else _("Off")),
        ]
        self.logSettingsSummaryLabel.setText(" | ".join(items))

    def onLogFilePathChanged(self):
        if not hasattr(self, "logFilePath"):
            return
        path = self.logFilePath.text().strip()
        self.config["saveLogPath"] = path
        self.config["saveLogPath2"] = path
        self.logFilePath.setToolTip(path)

    def selectLogFile(self):
        oldPath = self.logFilePath.text()
        if oldPath == "":
            oldPath = os.getcwd()
        fileName_choose, _filetype = QFileDialog.getSaveFileName(self.mainWidget,
                                    _("Select file"),
                                    os.path.join(oldPath, "comtool.log"),
                                    _("Log file (*.log);;txt file (*.txt);;All Files (*)"))
        if fileName_choose == "":
            return
        self.logFilePath.setText(fileName_choose)
        self.logFilePath.setToolTip(fileName_choose)
        self.config["saveLogPath"] = fileName_choose
        self.config["saveLogPath2"] = fileName_choose

    def toggleSaveLogRecording(self):
        if not self.logSessionActive:
            self.startSaveLogRecording()
        elif self.logPaused:
            self.resumeSaveLogRecording()
        else:
            self.pauseSaveLogRecording()

    def startSaveLogRecording(self):
        self.onLogFilePathChanged()
        path = self.configuredLogPath()
        if not self.ensureLogFileReady(path):
            return
        self.logSessionActive = True
        self.logPaused = False
        self.logSessionPath = path
        self.logStartTime = time.time()
        self.logSessionStartDt = datetime.now()
        self.logPauseStartTime = None
        self.logPauseStartDt = None
        self.logPausePeriods = []
        self.logConnectionEvents = []
        self.receiveClearRecords = []
        self.logTimedRemaining = int(self.config.get("saveLogDuration", 60))
        self.logWriter.start(path, self.configGlobal["encoding"])
        self.config["saveLog"] = True
        self.updateSaveLogButtons()
        self.startSaveLogStatus()
        self.startTimedSaveLog()

    def pauseSaveLogRecording(self):
        if not self.logSessionActive or self.logPaused:
            return
        self.logPaused = True
        self.config["saveLog"] = False
        self.logPauseStartTime = time.time()
        self.logPauseStartDt = datetime.now()
        if self.logTimedDeadline is not None:
            self.logTimedRemaining = max(1, int(self.logTimedDeadline - time.time() + 0.999))
        self.stopSaveLogTimer(clearDeadline=True)
        self.stopSaveLogStatus()
        self.updateSaveLogButtons()

    def resumeSaveLogRecording(self):
        if not self.logSessionActive or not self.logPaused:
            return
        self.closeCurrentLogPause()
        self.logPaused = False
        self.config["saveLog"] = True
        self.updateSaveLogButtons()
        self.startSaveLogStatus()
        self.startTimedSaveLog()

    def confirmStopSaveLog(self):
        if not self.logSessionActive:
            return
        if QMessageBox.question(self.mainWidget, _("Confirm stop"), _("Stop log recording?"),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.finishSaveLogRecording()

    def finishSaveLogRecording(self, timed=False):
        if not self.logSessionActive:
            return
        endDt = datetime.now()
        if self.logPaused:
            self.closeCurrentLogPause(endDt=endDt, endTime=time.time())
        self.config["saveLog"] = False
        self.logWriter.stop()
        if self.config.get("saveLogAppendInfo", False):
            self.appendLogInformation(endDt)
        self.logSessionActive = False
        self.logPaused = False
        self.logStartTime = None
        self.logSessionStartDt = None
        self.logPauseStartTime = None
        self.logPauseStartDt = None
        self.logTimedRemaining = None
        self.stopSaveLogTimer(clearDeadline=True)
        self.stopSaveLogStatus()
        self.updateSaveLogButtons()
        self.updateSaveLogStatus()
        if timed:
            self.hintSignal.emit("info", _("OK"), _("Timed log stopped"))

    def closeCurrentLogPause(self, endDt=None, endTime=None):
        if self.logPauseStartTime is None or self.logPauseStartDt is None:
            return
        if endDt is None:
            endDt = datetime.now()
        if endTime is None:
            endTime = time.time()
        duration = max(0, int(endTime - self.logPauseStartTime))
        self.logPausePeriods.append((self.logPauseStartDt, endDt, duration))
        self.logPauseStartTime = None
        self.logPauseStartDt = None

    def updateSaveLogButtons(self):
        if not hasattr(self, "saveLogStartButton"):
            return
        self.saveLogStopButton.setEnabled(self.logSessionActive)
        self.saveLogStopButton.setStyleSheet(
            "QPushButton {background:#d32f2f;color:#ffffff;}"
            "QPushButton:disabled {background:#8a2a2a;color:#dddddd;}"
        )
        self.logMoreSettingsButton.setEnabled(not self.logSessionActive)
        if not self.logSessionActive:
            self.saveLogStartButton.setText(_("Start record"))
            self.saveLogStartButton.setToolTip(_("Start log recording"))
            self.saveLogStartButton.setStyleSheet("")
            return
        if self.logPaused:
            self.saveLogStartButton.setText(_("Resume record"))
            self.saveLogStartButton.setToolTip(_("Resume log recording"))
            self.saveLogStartButton.setStyleSheet("background:#f9a825;color:#212121;")
        else:
            self.saveLogStartButton.setText(_("Pause record"))
            self.saveLogStartButton.setToolTip(_("Pause log recording"))
            self.saveLogStartButton.setStyleSheet("background:#2e7d32;color:#ffffff;")

    def openLogSettingsDialog(self):
        if self.logSessionActive:
            self.hintSignal.emit("warning", _("Warning"), _("Log settings are locked while recording or paused"))
            return
        dialog = LogSettingsDialog(self, self.mainWidget)
        dialog.exec()

    def stopSaveLogTimer(self, clearDeadline=False):
        if self.saveLogStopTimer is not None:
            self.saveLogStopTimer.stop()
        if clearDeadline:
            self.logTimedDeadline = None

    def startTimedSaveLog(self):
        if self.saveLogStopTimer is None:
            return
        self.stopSaveLogTimer(clearDeadline=True)
        if not self.logSessionActive or self.logPaused or not self.config.get("saveLogTimed", False):
            return
        duration = self.logTimedRemaining
        if duration is None:
            duration = int(self.config.get("saveLogDuration", 60))
        if duration <= 0:
            duration = 1
        self.logTimedRemaining = duration
        self.logTimedDeadline = time.time() + duration
        self.saveLogStopTimer.start(duration * 1000)

    def stopTimedSaveLog(self):
        self.finishSaveLogRecording(timed=True)

    def secondsToHms(self, seconds):
        seconds = max(0, int(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return "{:02d}:{:02d}:{:02d}".format(h, m, s)

    def splitSeconds(self, seconds):
        seconds = max(0, int(seconds))
        return seconds // 3600, (seconds % 3600) // 60, seconds % 60

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

    def configuredLogPath(self):
        return self.config["saveLogPath"]

    def currentLogPath(self):
        return self.logSessionPath if self.logSessionActive and self.logSessionPath else self.configuredLogPath()

    def ensureLogFileReady(self, path):
        if not path:
            self.hintSignal.emit("warning", _("Warning"), _("Select log file path before starting log"))
            return False
        folder = os.path.dirname(os.path.abspath(path))
        if folder and not os.path.exists(folder):
            self.hintSignal.emit("error", _("Error"), _("Log folder does not exist") + ": " + folder)
            return False
        try:
            with open(path, "a+", encoding=self.configGlobal["encoding"], newline="\n"):
                pass
        except Exception as e:
            self.hintSignal.emit("error", _("Error"), _("Open log file failed") + ": " + str(e))
            return False
        return True

    def currentLogElapsed(self):
        if not self.logSessionActive or self.logStartTime is None:
            return 0
        end = self.logPauseStartTime if self.logPaused and self.logPauseStartTime is not None else time.time()
        paused = sum(period[2] for period in self.logPausePeriods)
        return max(0, int(end - self.logStartTime - paused))

    def startSaveLogStatus(self):
        self.updateSaveLogStatus()
        if self.saveLogStatusTimer is not None:
            self.saveLogStatusTimer.start()

    def stopSaveLogStatus(self):
        if self.saveLogStatusTimer is not None:
            self.saveLogStatusTimer.stop()
        self.updateSaveLogStatus()

    def updateSaveLogStatus(self):
        elapsed = self.currentLogElapsed()
        path = self.currentLogPath()
        size = os.path.getsize(path) if path and os.path.exists(path) else 0
        self.logLastSize = size
        if hasattr(self, "saveLogStatusLabel"):
            self.saveLogStatusLabel.setText("{}: {} / {}".format(_("Log"), self.secondsToHms(elapsed), self.formatFileSize(size)))

    def formatLogDateTime(self, value):
        return value.strftime("%Y-%m-%d %H:%M:%S") if value else "-"

    def currentPageLogInfo(self):
        for item in self.globalConfigValue("items", []):
            config = item.get("config", {})
            if config.get("plugin") is self.config:
                conns = config.get("conns", {})
                connId = conns.get("currConn", "")
                return item.get("name", ""), connId, conns.get(connId, {})
        return getattr(self, "pageName", self.name), "", {}

    def recordLogConnectionEvent(self, previousStatus, status, msg):
        if not self.logSessionActive:
            return
        eventType = None
        if status == ConnectionStatus.CONNECTED and previousStatus == ConnectionStatus.LOSE:
            eventType = "reconnect"
        elif status == ConnectionStatus.CONNECTED and previousStatus != ConnectionStatus.CONNECTED:
            eventType = "open"
        elif status == ConnectionStatus.CLOSED and previousStatus != ConnectionStatus.CLOSED:
            eventType = "close"
        elif status == ConnectionStatus.LOSE and previousStatus != ConnectionStatus.LOSE:
            eventType = "drop"
        if eventType is None:
            return
        self.logConnectionEvents.append({
            "time": datetime.now(),
            "type": eventType,
            "message": msg or "",
            "from": previousStatus.name if previousStatus is not None else "",
            "to": status.name
        })

    def logConnectionEventLabel(self, eventType):
        labels = {
            "open": _("Port opened"),
            "close": _("Port closed"),
            "drop": _("Port disconnected"),
            "reconnect": _("Port reconnected"),
        }
        return labels.get(eventType, eventType)

    def formatLogConnectionEventLines(self, title, eventTypes):
        lines = ["{}:".format(title)]
        events = [
            event for event in self.logConnectionEvents
            if event.get("type") in eventTypes
        ]
        if not events:
            lines.append("  - {}".format(_("No events")))
            return lines
        for event in events:
            msg = event.get("message", "")
            msgPart = " - {}".format(msg) if msg else ""
            lines.append("  - {}: {}{}".format(
                self.formatLogDateTime(event.get("time")),
                self.logConnectionEventLabel(event.get("type")),
                msgPart
            ))
        return lines

    def appendLogInformation(self, endDt):
        path = self.currentLogPath()
        if not path:
            return
        pageName, connId, connSettings = self.currentPageLogInfo()
        try:
            connSettingsText = json.dumps(connSettings, ensure_ascii=False, sort_keys=True)
        except Exception:
            connSettingsText = str(connSettings)
        baseSize = os.path.getsize(path) if os.path.exists(path) else 0

        def buildSummary(sizeText):
            lines = ["", "", "========== {} ==========".format(_("Log information"))]
            if self.logAppendInfoEnabled("startTime"):
                lines.append("{}: {}".format(_("Start time"), self.formatLogDateTime(self.logSessionStartDt)))
            if self.logAppendInfoEnabled("endTime"):
                lines.append("{}: {}".format(_("End time"), self.formatLogDateTime(endDt)))
            if self.logAppendInfoEnabled("activeDuration"):
                lines.append("{}: {}".format(_("Active duration"), self.secondsToHms(self.currentLogElapsed())))
            if self.logAppendInfoEnabled("pauseCount"):
                lines.append("{}: {}".format(_("Pause count"), len(self.logPausePeriods)))
            if self.logAppendInfoEnabled("pauseTime"):
                if self.logPausePeriods:
                    for idx, (startDt, endPauseDt, duration) in enumerate(self.logPausePeriods, start=1):
                        lines.append("{} {}: {} - {} ({})".format(
                            _("Pause time"),
                            idx,
                            self.formatLogDateTime(startDt),
                            self.formatLogDateTime(endPauseDt),
                            self.secondsToHms(duration)
                        ))
                else:
                    lines.append("{}: {}".format(_("Pause time"), _("None")))
            if self.logAppendInfoEnabled("logSize"):
                lines.append("{}: {}".format(_("Log size"), sizeText))
            if self.logAppendInfoEnabled("logPath"):
                lines.append("{}: {}".format(_("Log path"), path))
            if self.logAppendInfoEnabled("pageName"):
                lines.append("{}: {}".format(_("Page name"), pageName or "-"))
            if self.logAppendInfoEnabled("connectionType"):
                lines.append("{}: {}".format(_("Connection type"), connId or "-"))
            if self.logAppendInfoEnabled("connectionStatus"):
                lines.append("{}: {}".format(_("Connection status"), self.currentConnStatus.name))
            if self.logAppendInfoEnabled("connectionSettings"):
                lines.append("{}: {}".format(_("Connection settings"), connSettingsText or "-"))
            if self.logAppendInfoEnabled("portOpenCloseHistory"):
                lines.extend(self.formatLogConnectionEventLines(
                    _("Port open/close history"),
                    {"open", "close"}
                ))
            if self.logAppendInfoEnabled("portDropReconnectHistory"):
                lines.extend(self.formatLogConnectionEventLines(
                    _("Port disconnect/reconnect history"),
                    {"drop", "reconnect"}
                ))
            if self.logAppendInfoEnabled("receiveClearHistory"):
                lines.extend(self.formatReceiveClearRecordLines(_("Receive clear history")))
            lines.extend(["====================================", ""])
            return "\n".join(lines)

        encoding = self.configGlobal["encoding"]
        summary = buildSummary(self.formatFileSize(baseSize))
        for _i in range(3):
            finalSize = baseSize + len(summary.encode(encoding, errors="ignore"))
            nextSummary = buildSummary(self.formatFileSize(finalSize))
            if nextSummary == summary:
                break
            summary = nextSummary
        with open(path, "a+", encoding=self.configGlobal["encoding"], newline="\n") as f:
            f.write(summary)

    def onLog(self, text):
        path = self.currentLogPath()
        if self.logSessionActive and (not self.logPaused) and self.config["saveLog"] and path:
            if not self.logWriter.write(text):
                with open(path, "a+", encoding=self.configGlobal["encoding"], newline="\n") as f:
                    f.write(text)

    def logTextWithTimestamps(self, text):
        if not text:
            return text
        result = []
        for line in text.splitlines(True):
            if not line:
                continue
            newline = ""
            content = line
            if line.endswith("\r\n"):
                content, newline = line[:-2], "\r\n"
            elif line.endswith("\n"):
                content, newline = line[:-1], "\n"
            elif line.endswith("\r"):
                content, newline = line[:-1], "\r"
            result.append("[{}] {}{}".format(utils.datetime_format_ms(datetime.now()), content, newline))
        return "".join(result)

    def receiveRecordSize(self, record):
        encoding = self.configGlobal["encoding"]
        return len(str(record).encode(encoding, errors="ignore"))

    def receiveBufferLimitBytes(self):
        try:
            return max(64, int(self.config.get("receiveBufferSizeKB", 4096))) * 1024
        except Exception:
            self.config["receiveBufferSizeKB"] = 4096
            return 4096 * 1024

    def trimReceiveDisplayRecords(self):
        limit = self.receiveBufferLimitBytes()
        records = self.receiveDisplayRecords
        if not records:
            return False
        total = 0
        kept = []
        for record in reversed(records):
            size = self.receiveRecordSize(record)
            if kept and total + size > limit:
                break
            kept.append(record)
            total += size
        kept.reverse()
        if len(kept) == len(records):
            return False
        self.receiveDisplayRecords = kept
        return True

    def showReceivedData(self, text: str):
        self.receiveDisplayRecords.append(text)
        self.appendReceiveText(text)
        self.onLog(text)
        if self.trimReceiveDisplayRecords():
            self.rerenderReceiveArea()

    def appendReceiveText(self, text, preserveScroll=True):
        if not text:
            return
        userCursor = self.receiveWidget.textCursor()
        preserveSelection = userCursor.hasSelection()
        curScrollValue = self.receiveWidget.verticalScrollBar().value()
        curHorizontalValue = self.receiveWidget.horizontalScrollBar().value()
        if not preserveSelection:
            self.receiveWidget.moveCursor(QTextCursor.End)
        endScrollValue = self.receiveWidget.verticalScrollBar().value()
        cursor = QTextCursor(self.receiveWidget.document())
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        if not self.defaultColor:
            qcolor = QColor(self.config.get("receiveFontColor", ""))
            self.defaultColor = qcolor if qcolor.isValid() else fmt.foreground()
        if not self.defaultBg:
            self.defaultBg = fmt.background()
        for color, bg, segment in self.splitTextByReceiveFindRules(text):
            fmt.setForeground(QColor(color) if color else self.defaultColor)
            fmt.setBackground(QColor(bg) if bg else self.defaultBg)
            cursor.setCharFormat(fmt)
            cursor.insertText(segment)
        if preserveSelection:
            self.receiveWidget.setTextCursor(userCursor)
            self.receiveWidget.verticalScrollBar().setValue(curScrollValue)
        elif preserveScroll and curScrollValue < endScrollValue:
            self.receiveWidget.verticalScrollBar().setValue(curScrollValue)
        else:
            self.receiveWidget.moveCursor(QTextCursor.End)
        self.receiveWidget.horizontalScrollBar().setValue(curHorizontalValue)
        self.scheduleReceiveFindMarkersUpdate()

    def normalizeReceiveFindRule(self, rule=None):
        if rule is None:
            rule = {}
        if isinstance(rule, str):
            rule = {"pattern": rule}
        return {
            "pattern": "" if rule.get("pattern") is None else str(rule.get("pattern", "")),
            "color": "" if rule.get("color") is None else str(rule.get("color", "")),
            "enabled": bool(rule.get("enabled", True)),
            "isRegex": bool(rule.get("isRegex", rule.get("regex", False))),
            "caseSensitive": bool(rule.get("caseSensitive", True)),
            "wholeWord": bool(rule.get("wholeWord", False)),
            "reverse": bool(rule.get("reverse", False)),
            "wrapFind": bool(rule.get("wrapFind", True)),
            "dotMatchesNewline": bool(rule.get("dotMatchesNewline", False))
        }

    def onReceiveFindRulesChanged(self):
        self.config["receiveFindRules"] = [
            self.normalizeReceiveFindRule(rule)
            for rule in self.config.get("receiveFindRules", [])
        ]
        self.receiveFindRuleErrors.clear()
        self.rerenderReceiveArea()

    def receiveFindDialogTitle(self):
        return "{}-{}".format(getattr(self, "pageName", self.name), _("Receive area find"))

    def openReceiveFindDialog(self):
        if self.receiveFindDialog is None:
            self.receiveFindDialog = ReceiveFindDialog(self, self.mainWidget)
        self.receiveFindDialog.setWindowTitle(self.receiveFindDialogTitle())
        self.receiveFindDialog.refreshRules()
        self.receiveFindDialog.show()
        self.receiveFindDialog.raise_()
        self.receiveFindDialog.activateWindow()

    def scrollReceiveToBottom(self):
        if not hasattr(self, "receiveWidget"):
            return
        self.receiveWidget.moveCursor(QTextCursor.End)
        self.receiveWidget.ensureCursorVisible()
        bar = self.receiveWidget.verticalScrollBar()
        bar.setValue(bar.maximum())

    def plainTextFindRanges(self, text, pattern, caseSensitive=True):
        if not pattern:
            return []
        source = text if caseSensitive else text.lower()
        target = pattern if caseSensitive else pattern.lower()
        ranges = []
        start = 0
        while True:
            idx = source.find(target, start)
            if idx < 0:
                break
            end = idx + len(target)
            ranges.append((idx, end))
            start = end if end > idx else idx + 1
        return ranges

    def regexFindRanges(self, text, pattern, caseSensitive=True, wholeWord=False, dotMatchesNewline=False, sourceKey=None):
        if not pattern:
            return []
        flags = re.MULTILINE
        if not caseSensitive:
            flags |= re.IGNORECASE
        if dotMatchesNewline:
            flags |= re.DOTALL
        expression = pattern
        if wholeWord:
            expression = r"(?<!\w)(?:{})(?!\w)".format(expression)
        try:
            matcher = re.compile(expression, flags)
        except Exception as e:
            key = sourceKey or expression
            if key not in self.receiveFindRuleErrors:
                self.receiveFindRuleErrors.add(key)
                print("receive find regex error:", e)
            return []
        ranges = []
        for match in matcher.finditer(text):
            start, end = match.span()
            if start < end:
                ranges.append((start, end))
        return ranges

    def receiveFindRuleRanges(self, rule, text):
        pattern = rule.get("pattern", "")
        if not pattern:
            return []
        caseSensitive = rule.get("caseSensitive", True)
        wholeWord = rule.get("wholeWord", False)
        if rule.get("isRegex", False):
            return self.regexFindRanges(
                text,
                pattern,
                caseSensitive=caseSensitive,
                wholeWord=wholeWord,
                dotMatchesNewline=rule.get("dotMatchesNewline", False),
                sourceKey=(pattern, caseSensitive, wholeWord, rule.get("dotMatchesNewline", False))
            )
        if wholeWord:
            return self.regexFindRanges(
                text,
                re.escape(pattern),
                caseSensitive=caseSensitive,
                wholeWord=True,
                sourceKey=(pattern, caseSensitive, wholeWord, "plain")
            )
        return self.plainTextFindRanges(text, pattern, caseSensitive=caseSensitive)

    def receiveFindRuleByIndex(self, idx):
        if idx < 0 or idx >= len(self.config.get("receiveFindRules", [])):
            return None
        rule = self.normalizeReceiveFindRule(self.config["receiveFindRules"][idx])
        if not rule.get("enabled", True):
            return None
        return rule

    def countReceiveFindRuleMatches(self, idx):
        rule = self.receiveFindRuleByIndex(idx)
        if rule is None or not hasattr(self, "receiveWidget"):
            return 0
        return len(self.receiveFindRuleRanges(rule, self.receiveWidget.toPlainText()))

    def jumpToNextReceiveFindRule(self, idx):
        rule = self.receiveFindRuleByIndex(idx)
        if rule is None or not hasattr(self, "receiveWidget"):
            return
        text = self.receiveWidget.toPlainText()
        ranges = self.receiveFindRuleRanges(rule, text)
        if not ranges:
            self.hintSignal.emit("info", _("Find"), _("No match found"))
            return
        cursor = self.receiveWidget.textCursor()
        hasSelection = cursor.hasSelection()
        selectionStart = cursor.selectionStart()
        selectionEnd = cursor.selectionEnd()
        position = selectionStart if rule.get("reverse") else selectionEnd
        if not hasSelection:
            position = cursor.position()
        target = None
        if rule.get("reverse"):
            for start, end in reversed(ranges):
                if hasSelection and start == selectionStart and end == selectionEnd:
                    continue
                if not hasSelection and start < position < end:
                    continue
                if end <= position:
                    target = (start, end)
                    break
            if target is None and rule.get("wrapFind"):
                target = ranges[-1]
        else:
            for start, end in ranges:
                if hasSelection and start == selectionStart and end == selectionEnd:
                    continue
                if not hasSelection and start < position < end:
                    continue
                if start >= position:
                    target = (start, end)
                    break
            if target is None and rule.get("wrapFind"):
                target = ranges[0]
        if target is None:
            self.hintSignal.emit("info", _("Find"), _("No more matches"))
            return
        start, end = target
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        self.receiveWidget.setTextCursor(cursor)
        self.receiveWidget.ensureCursorVisible()

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
                overlapsHigherPriority = any(
                    max(start, selectedStart) < min(end, selectedEnd)
                    for selectedStart, selectedEnd, _selectedColor, _selectedOrder in ranges
                )
                if start < end and not overlapsHigherPriority:
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
            bestOrder = None
            for rangeStart, rangeEnd, color, order in ranges:
                if rangeStart <= start and end <= rangeEnd and (bestOrder is None or order < bestOrder):
                    bg = color
                    bestOrder = order
            segments.append([originalColor, bg, text[start:end]])
        return segments

    def rerenderReceiveArea(self):
        if not hasattr(self, "receiveWidget") or self.rerenderingReceiveArea:
            return
        self.rerenderingReceiveArea = True
        try:
            scrollBar = self.receiveWidget.verticalScrollBar()
            oldValue = scrollBar.value()
            atEnd = oldValue >= scrollBar.maximum()
            records = list(self.receiveDisplayRecords)
            self.receiveWidget.clear()
            self.defaultColor = None
            self.defaultBg = None
            for text in records:
                self.appendReceiveText(text, preserveScroll=False)
            if atEnd:
                self.receiveWidget.moveCursor(QTextCursor.End)
            else:
                scrollBar.setValue(min(oldValue, scrollBar.maximum()))
        finally:
            self.rerenderingReceiveArea = False
            self.scheduleReceiveFindMarkersUpdate()

    def scheduleReceiveFindMarkersUpdate(self):
        if self.receiveFindMarkerTimer is not None:
            self.receiveFindMarkerTimer.start(200)

    def shouldShowReceiveFindMarkers(self):
        dialog = getattr(self, "receiveFindDialog", None)
        return bool(dialog is not None and dialog.isVisible())

    def updateReceiveFindMarkers(self):
        if not hasattr(self, "receiveFindScrollBar"):
            return
        if not self.shouldShowReceiveFindMarkers():
            self.receiveFindScrollBar.setMarkers([])
            return
        text = self.receiveWidget.toPlainText() if hasattr(self, "receiveWidget") else ""
        if not text:
            self.receiveFindScrollBar.setMarkers([])
            return
        textLength = max(1, len(text))
        markers = []
        for rawRule in self.config.get("receiveFindRules", []):
            rule = self.normalizeReceiveFindRule(rawRule)
            color = rule.get("color", "")
            qcolor = QColor(color)
            if not rule.get("enabled") or not color or not qcolor.isValid():
                continue
            for start, end in self.receiveFindRuleRanges(rule, text):
                start = max(0, min(textLength, int(start)))
                end = max(0, min(textLength, int(end)))
                if start < end:
                    markers.append(((start + end) / 2 / textLength, color))
                if len(markers) >= 2000:
                    break
            if len(markers) >= 2000:
                break
            self.receiveFindScrollBar.setMarkers(markers)

    def onConnChanged(self, status:ConnectionStatus, msg:str):
        previousStatus = self.currentConnStatus
        self.currentConnStatus = status
        self.recordLogConnectionEvent(previousStatus, status, msg)
        super().onConnChanged(status, msg)
        self.updateClosedOnlyControls()
        if hasattr(self, "receiveFindDialog") and self.receiveFindDialog is not None:
            advanced = getattr(self.receiveFindDialog, "advancedDialog", None)
            if advanced is not None:
                advanced.updateFindNextState()
        self.updateReceiveFindMarkers()

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

    def getSendData(self, data=None):
        if data is None:
            data = self.sendArea.toPlainText()
        return self.parseSendData(
            data,
            self.configGlobal["encoding"],
            self.config["useCRLF"],
            not self.config["sendAscii"],
            self.config["sendEscape"]
        )

    def onSendData(self, call=True, data=None):
        try:
            dataBytes = self.getSendData(data)
            if dataBytes:
                self.sendData(dataBytes)
        except Exception as e:
            self.hintSignal.emit("error", _("Error"), _("get data error") + ": " + str(e))

    def onReceived(self, data : bytes):
        self.statusBar.addRx(len(data))
        try:
            data = self.decodeMethod(data)
        except Exception as e:
            self.hintSignal.emit("error", _("Error"), _("Run decode error") + " " + str(e))
            return
        if not data:
            return
        for plugin in self.connChilds:
            plugin.onReceived(data)
        captureData = data
        if type(data) != str:
            captureData = data.decode(encoding=self.configGlobal["encoding"], errors="ignore")
            data = self.decodeReceivedData(
                data,
                self.configGlobal["encoding"],
                not self.config["receiveAscii"],
                self.config["receiveEscape"],
                self.config.get("receiveShowNonPrintableHex", False)
            )
        if self.dataCaptureWidget:
            self.dataCaptureWidget.onData(captureData)
        head = ""
        if self.config["recordSend"] or self.config["showTimestamp"]:
            head = self.buildRecordHead("<=" if self.config["recordSend"] else "",
                                        self.config["showTimestamp"],
                                        not self.config["receiveAscii"])
        self.showReceiveDataSignal.emit(head + data + "\n")

    def scheduledSend(self, data_bytes):
        self.isScheduledSending = True
        interval = self.config["sendScheduledTime"]
        lastChangeIntervalTime = time.time()
        changeIntervalDelay = 2
        while self.config["sendScheduled"] and interval > 0:
            try:
                time.sleep(interval / 1000)
                self.sendData(data_bytes=data_bytes)
                if self.config["sendScheduledTime"] != interval and time.time() - lastChangeIntervalTime > changeIntervalDelay:
                    lastChangeIntervalTime = time.time()
                    interval = self.config["sendScheduledTime"]
            except Exception:
                self.hintSignal.emit("error", _("Error"), _("Time format error"))
                break
        self.isScheduledSending = False

    def sendData(self, data_bytes=None):
        if self.captureLocked:
            return
        try:
            rawBytes = data_bytes or b""
            if self.config["sendAutoNewline"]:
                rawBytes += b"\r\n" if self.config["useCRLF"] else b"\n"
            data_bytes = self.encodeMethod(rawBytes)
            if self.config["recordSend"]:
                isHex = not self.config["sendAscii"]
                if isHex:
                    sendStr = utils.hexlify(data_bytes, ' ').decode(encoding=self.configGlobal["encoding"]).upper()
                else:
                    sendStr = data_bytes.decode(encoding=self.configGlobal["encoding"], errors="ignore")
                head = self.buildRecordHead("=>", self.config["showTimestamp"], isHex, leadingLineBreak=True)
                self.showReceiveDataSignal.emit(head + sendStr + "\n")
        except Exception as e:
            self.hintSignal.emit("error", _("Error"), _("Run encode error") + " " + str(e))
            return
        if data_bytes:
            self.send(data_bytes, callback=self.onSent)
            if self.config["sendScheduled"] and not self.isScheduledSending:
                t = threading.Thread(target=self.scheduledSend, args=(rawBytes,))
                t.setDaemon(True)
                t.start()

    def onSent(self, ok, msg, length, path):
        if ok:
            self.statusBar.addTx(length)
        else:
            self.hintSignal.emit("error", _("Error"), _("Send data failed!") + " " + msg)

    def onDel(self):
        self.commandSequenceStop = True
        if self.dataCaptureWidget is not None:
            self.dataCaptureWidget.stopCapture()
        if self.logSessionActive:
            self.finishSaveLogRecording()
        self.logWriter.stop()
        self.stopSaveLogTimer()
        self.stopSaveLogStatus()

    def sendCustomItem(self, item):
        if self.captureLocked:
            return
        text = item.get("text", "") if isinstance(item, dict) else item
        dateBytes = self.parseSendData(text, self.configGlobal["encoding"], self.config["useCRLF"], not self.config["sendAscii"], self.config["sendEscape"])
        if dateBytes:
            self.sendData(data_bytes = dateBytes)

    def onCustomItemChange(self, idx, edit, send):
        text = edit.text()
        edit.setToolTip(text)
        send.setToolTip(text)
        self.config["customSendItems"][idx].update({
            "text": text,
            "remark": send.text()
        })
        self.filterCustomSendItems()

    def onCodeItemChanged(self):
        if self.editingDefaults:
            return
        self.editingDefaults = True
        if self.codeItems.currentText() == self.codeItemCustomStr:
            self.codeItems.clearEditText()
            self.editingDefaults = False
            return
        if self.codeItems.currentText() == self.codeItemLoadDefaultsStr:
            for name in defaultProtocols:
                idx = self.codeItems.findText(name)
                if idx >= 0:
                    self.codeItems.removeItem(idx)
                self.codeItems.insertItem(self.codeItems.count() - 2, name)
                self.config["code"][name] = defaultProtocols[name]
            self.codeItems.setCurrentIndex(0)
            self.selectCode(self.codeItems.currentText())
            self.editingDefaults = False
            return
        # update code from defaults
        self.selectCode(self.codeItems.currentText())
        self.editingDefaults = False

    def selectCode(self, name):
        if name in [self.codeItemCustomStr, self.codeItemLoadDefaultsStr] or not name or not name in self.config["code"]:
            print(f"name {name} invalid")
            return
        self.config["currCode"] = name
        self.codeWidget.clear()
        self.codeWidget.insertPlainText(self.config["code"][name])
        ok, e, d = self.getEnDecodeMethod(self.codeWidget.toPlainText())
        if ok:
            self.encodeMethod = e
            self.decodeMethod = d
        self.saveCodeBtn.setText(_("Save"))
        self.saveCodeBtn.setEnabled(False)

    def getEnDecodeMethod(self, code):
        func = lambda x:x
        try:
            exec(code, self.codeGlobals)
            if (not "decode" in self.codeGlobals) or not "encode" in self.codeGlobals:
                raise ValueError(_("decode and encode method should be in code"))
            return True, self.codeGlobals["encode"], self.codeGlobals["decode"]
        except Exception as e:
            msg = _("Method error") + "\n" + str(e)
            self.hintSignal.emit("error", _("Error"), msg)
        return False, func, func

    def onCodeChanged(self):
        changed = True
        name = self.codeItems.currentText()
        if name in self.config["code"]:
            codeSaved = self.config["code"][name]
            code = self.codeWidget.toPlainText()
            if code == codeSaved:
                changed = False
        if changed:
            self.saveCodeBtn.setText(_("Save") + " *")
            self.saveCodeBtn.setEnabled(True)
        else:
            self.saveCodeBtn.setText(_("Save"))
            self.saveCodeBtn.setEnabled(False)

    def saveCode(self):
        self.editingDefaults = True
        name = self.codeItems.currentText()
        if name in [self.codeItemCustomStr, self.codeItemLoadDefaultsStr] or not name:
            self.hintSignal.emit("warning", _("Warning"), _("Please input code profile name first"))
            self.editingDefaults = False
            return
        idx = self.codeItems.findText(name)
        if idx < 0:
            self.codeItems.insertItem(self.codeItems.count() - 2, name)
        self.editingDefaults = False
        code = self.codeWidget.toPlainText()
        ok, e, d= self.getEnDecodeMethod(code)
        if ok:
            self.encodeMethod = e
            self.decodeMethod = d
            self.config["code"][name] = code
            self.saveCodeBtn.setText(_("Save"))
            self.saveCodeBtn.setEnabled(False)

    def deleteCode(self):
        self.editingDefaults = True
        name = self.codeItems.currentText()
        itemsConfig = [self.codeItemCustomStr, self.codeItemLoadDefaultsStr]
        # QMessageBox.infomation()
        if name in itemsConfig or not name:
            self.hintSignal.emit("warning", _("Warning"), _("Please select a code profile name first to delete"))
            self.editingDefaults = False
            return
        idx = self.codeItems.findText(name)
        if idx < 0:
            self.editingDefaults = False
            return
        self.codeItems.removeItem(idx)
        self.config["code"].pop(name)
        name = list(self.config["code"].keys())
        if len(name) > 0:
            name = name[0]
            self.codeItems.setCurrentText(name)
            self.selectCode(name)
        self.editingDefaults = False

