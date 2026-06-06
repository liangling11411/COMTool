
if __name__ == "__main__":
    import sys, os
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..")
    sys.path.insert(0, path)
    sys.path.insert(0, os.path.join(path, ".."))

from PyQt5.QtCore import pyqtSignal,Qt, QRect, QMargins, QObject, pyqtSlot, QEvent
from PyQt5.QtWidgets import (QWidget,QPushButton,QMessageBox,QDesktopWidget,QMainWindow,
                             QVBoxLayout,QHBoxLayout,QGridLayout,QTextEdit,QLabel,QRadioButton,QCheckBox,
                             QLineEdit,QGroupBox,QSplitter,QFileDialog, QScrollArea, QSizePolicy)
from PyQt5.QtGui import QIcon,QFont,QTextCursor,QPixmap,QColor,QFontMetrics
try:
    import parameters,helpAbout,autoUpdate
    from Combobox import ComboBox
    import i18n
    from i18n import _
    import version
    import utils
except ImportError:
    from COMTool import parameters,helpAbout,autoUpdate, utils
    from COMTool.Combobox import ComboBox
    from COMTool import i18n
    from COMTool.i18n import _
    from COMTool import version
try:
    from base import COMM, ConnectionStatus
except Exception:
    from .base import COMM, ConnectionStatus
import serial, threading, time, re, sys
import serial.tools.list_ports
import serial.tools.list_ports_common


class PortInfoButton(QPushButton):
    def __init__(self, port, detail, tooltip, parent=None):
        super().__init__(parent)
        self.port = port
        self.detail = detail
        self._lastText = ""
        self.setToolTip(tooltip)
        self.setMinimumHeight(54)
        self.setCursor(Qt.PointingHandCursor)
        self.updateText()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateText()

    def _textWidth(self, metrics, text):
        if hasattr(metrics, "horizontalAdvance"):
            return metrics.horizontalAdvance(text)
        return metrics.width(text)

    def _wrapDetail(self, width):
        detail = self.detail.strip()
        if not detail:
            return []
        metrics = QFontMetrics(self.font())
        maxWidth = max(48, width - 18)
        lines = []
        line = ""
        for ch in detail:
            if ch in "\r\n":
                if line:
                    lines.append(line)
                    line = ""
                continue
            candidate = line + ch
            if line and self._textWidth(metrics, candidate) > maxWidth:
                lines.append(line)
                line = ch
            else:
                line = candidate
            if len(lines) >= 3:
                break
        if line and len(lines) < 3:
            lines.append(line)
        if len(lines) == 3 and self._textWidth(metrics, lines[-1] + "...") > maxWidth:
            line = lines[-1]
            while line and self._textWidth(metrics, line + "...") > maxWidth:
                line = line[:-1]
            lines[-1] = line + "..."
        return lines

    def updateText(self):
        detailLines = self._wrapDetail(self.width())
        text = self.port if not detailLines else self.port + "\n" + "\n".join(detailLines)
        if text != self._lastText:
            self._lastText = text
            self.setText(text)

    def setColor(self, color, hoverColor=None, pressedColor=None):
        hoverColor = hoverColor or color
        pressedColor = pressedColor or color
        self.setStyleSheet(
            "QPushButton{"
            "text-align:left;background-color:%s;color:#ffffff;border:2px solid %s;border-radius:5px;"
            "padding:4px 8px;font-weight:normal;font-size:12px;min-height:54px;"
            "}"
            "QPushButton:hover{background-color:%s;border-color:%s;color:#ffffff;}"
            "QPushButton:pressed{background-color:%s;border-color:%s;color:#ffffff;}"
            % (color, color, hoverColor, hoverColor, pressedColor, pressedColor)
        )


class SerialPortRowWidget(QWidget):
    def __init__(self, owner, port, text, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.port = port
        self.text = text
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        self.setLayout(layout)
        self._locked = False
        self.setCursor(Qt.PointingHandCursor)
        detail = text[len(port):].strip() if text.startswith(port) else text
        if detail.startswith(port):
            detail = detail[len(port):].strip()
        detail = detail.strip(" -")
        detail = detail or text
        self.nameButton = PortInfoButton(port, detail, text)
        self.nameButton.installEventFilter(self)
        self.actionButton = QPushButton(_("Connect"))
        self.actionButton.setToolTip(_("Open this port in a receive page"))
        self.actionButton.setMinimumWidth(72)
        layout.addWidget(self.nameButton, 1)
        layout.addWidget(self.actionButton)
        self.nameButton.clicked.connect(lambda: self.owner.requestSerialPortPage(self.port, "focus"))
        self.actionButton.clicked.connect(self.onActionClicked)

    def eventFilter(self, obj, event):
        if obj is self.nameButton and event.type() == QEvent.MouseButtonDblClick:
            self.owner.requestSerialPortPage(self.port, "focus")
            event.accept()
            return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if self._locked:
            return
        if event.button() == Qt.LeftButton:
            self.owner.requestSerialPortPage(self.port, "focus")
        super().mousePressEvent(event)

    def onActionClicked(self):
        status = self.owner.quickPortStatus.get(self.port, ConnectionStatus.CLOSED)
        if status in (ConnectionStatus.CONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.LOSE):
            self.owner.requestSerialPortPage(self.port, "disconnect")
        else:
            self.owner.requestSerialPortPage(self.port, "connect")

    def mouseDoubleClickEvent(self, event):
        if self._locked:
            return
        if event.button() == Qt.LeftButton:
            self.owner.requestSerialPortPage(self.port, "focus")
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def setStatus(self, status, currentPort=None):
        isCurrentPort = self.port == currentPort
        isOpened = status in (ConnectionStatus.CONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.LOSE)
        if isCurrentPort:
            if isOpened:
                self.nameButton.setColor("#2e7d32", "#36963b", "#1b5e20")
            else:
                self.nameButton.setColor("#d32f2f", "#e04a4a", "#9a1d1d")
        else:
            self.nameButton.setColor("#0865b1", "#0f88eb", "#044174")
        if status in (ConnectionStatus.CONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.LOSE):
            self.actionButton.setText(_("Disconnect"))
            self.actionButton.setToolTip(_("Close this port but keep the receive page"))
            self.actionButton.setStyleSheet("background:#d32f2f;color:#ffffff;")
        else:
            self.actionButton.setText(_("Connect"))
            self.actionButton.setToolTip(_("Open this port in a receive page"))
            self.actionButton.setStyleSheet("background:#2e7d32;color:#ffffff;")

    def setSelected(self, selected):
        if selected:
            self.setStyleSheet("SerialPortRowWidget{background:rgba(33,150,243,55);border:1px solid #2196f3;border-radius:5px;}")
        else:
            self.setStyleSheet("SerialPortRowWidget{background:transparent;border:1px solid transparent;border-radius:5px;}")
    
    def setLocked(self, locked):
        self._locked = locked
        self.nameButton.setEnabled(not locked)
        self.actionButton.setEnabled(not locked)
        if locked:
            self.setCursor(Qt.ArrowCursor)
            self.nameButton.setStyleSheet(
                "QPushButton{"
                "text-align:left;background-color:#555555;color:#888888;border:2px solid #555555;border-radius:5px;"
                "padding:4px 8px;font-weight:normal;font-size:12px;min-height:54px;"
                "}"
            )
            self.actionButton.setText(_("Locked"))
            self.actionButton.setStyleSheet("background:#555555;color:#888888;")
        else:
            self.setCursor(Qt.PointingHandCursor)
            self.nameButton.setEnabled(True)
            self.actionButton.setEnabled(True)
            self.setStatus(self.owner.quickPortStatus.get(self.port, ConnectionStatus.CLOSED), self.owner.config.get("port"))


class Serial(COMM):
    '''
        call sequence:
            onInit
            onWidget
            onUiInitDone
                isConnected or getConnStatus
                send
            getConfig
    '''
    id = "serial"
    name = _("Serial")
    showSerialComboboxSignal = pyqtSignal(list)
    showSwitchSignal = pyqtSignal(ConnectionStatus)
    def onInit(self, config):
        self.com = serial.Serial()
        self.config = config
        default = {
            "port" : None,
            "baudrate" : 115200,
            "bytesize" : 8,
            "parity" : "None",
            "stopbits" : "1",
            "flowcontrol" : "None",
            "rts" : False,
            "dtr" : False,
        }
        for k in default:
            if not k in self.config:
                self.config[k] = default[k]
        self.widgetConfMap = {
            "port" : None,
            "baudrate" : None,
            "bytesize" : None,
            "parity" : None,
            "stopbits" : None,
            "flowcontrol" : None,
            "rts" : None,
            "dtr" : None,
        }
        self.isOpened = False
        self.busy = False
        self.status = ConnectionStatus.CLOSED
        self.isDetectSerialPort = False
        self.widget = None
        self.baudrateCustomStr = _("Custom, input baudrate")
        self.serialPageRequestCallback = None
        self.quickPortStatus = {}
        self.serialPortRowWidgets = {}
        self.usePortRows = False  # True for dbg page (port rows), False for dropdown
        self.lockedPorts = set()  # ports locked by non-dbg pages

    def disconnect(self):
        if self.isConnected():
            self.openCloseSerial()

    def onDel(self):
        if self.isConnected():
            self.openCloseSerial()

    def __del__(self):
        try:
            self.com.close()
            self.status = ConnectionStatus.CLOSED
            time.sleep(0.05)  # wait for child threads, not wait also ok, cause child threads are daemon
        except Exception:
            pass

    def getConfig(self):
        '''
            get config, dict type
        '''
        return self.config

    def onUiInitDone(self):
        for key in self.config:
            self.setSerialConfig(key, self.widgetConfMap[key], self.config[key])
        self.detectSerialPort()

    def onWidget(self):
        self.widget = QWidget()
        serialSettingsLayout = QGridLayout()
        serialPortLabek = QLabel(_("Port"))
        serailBaudrateLabel = QLabel(_("Baudrate"))
        serailBytesLabel = QLabel(_("DataBytes"))
        serailParityLabel = QLabel(_("Parity"))
        serailStopbitsLabel = QLabel(_("Stopbits"))
        serialFlowControlLabel = QLabel(_("Flow control"))
        self.serialPortCombobox = ComboBox()
        self.serailBaudrateCombobox = ComboBox()
        for baud in parameters.defaultBaudrates:
            self.serailBaudrateCombobox.addItem(str(baud))
        self.serailBaudrateCombobox.addItem(self.baudrateCustomStr)
        self.serailBaudrateCombobox.setCurrentIndex(5)
        self.serailBaudrateCombobox.setEditable(True)
        self.serailBytesCombobox = ComboBox()
        self.serailBytesCombobox.addItem("5")
        self.serailBytesCombobox.addItem("6")
        self.serailBytesCombobox.addItem("7")
        self.serailBytesCombobox.addItem("8")
        self.serailBytesCombobox.setCurrentIndex(3)
        self.serailParityCombobox = ComboBox()
        self.serailParityCombobox.addItem("None")
        self.serailParityCombobox.addItem("Odd")
        self.serailParityCombobox.addItem("Even")
        self.serailParityCombobox.addItem("Mark")
        self.serailParityCombobox.addItem("Space")
        self.serailParityCombobox.setCurrentIndex(0)
        self.serailStopbitsCombobox = ComboBox()
        self.serailStopbitsCombobox.addItem("1")
        self.serailStopbitsCombobox.addItem("1.5")
        self.serailStopbitsCombobox.addItem("2")
        self.serailStopbitsCombobox.setCurrentIndex(0)
        self.serialFlowControlCombobox = ComboBox()
        self.serialFlowControlCombobox.addItem("None")
        self.serialFlowControlCombobox.addItem("XON/XOFF")
        self.serialFlowControlCombobox.addItem("RTS/CTS")
        self.serialFlowControlCombobox.addItem("DSR/DTR")
        self.serialFlowControlCombobox.setCurrentIndex(0)
        self.checkBoxRTS = QCheckBox("rts")
        self.checkBoxDTR = QCheckBox("dtr")
        self.checkBoxRTS.setToolTip(_("Check to enable(usually output low level)"))
        self.checkBoxDTR.setToolTip(_("Check to enable(usually output low level)"))
        self.serialOpenCloseButton = QPushButton(_("OPEN"))
        self.serialRefreshButton = QPushButton(_("Refresh ports"))
        self.serialRefreshButton.setToolTip(_("Refresh available serial ports"))
        self.serialPortListScroll = QScrollArea()
        self.serialPortListScroll.setWidgetResizable(True)
        self.serialPortListScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.serialPortListScroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.serialPortListScroll.setFixedHeight(84)
        self.serialPortListScroll.setToolTip(_("Available serial ports"))
        self.serialPortListWidget = QWidget()
        self.serialPortListLayout = QVBoxLayout()
        self.serialPortListLayout.setContentsMargins(0, 0, 0, 0)
        self.serialPortListLayout.setSpacing(4)
        self.serialPortListWidget.setLayout(self.serialPortListLayout)
        self.serialPortListScroll.setWidget(self.serialPortListWidget)
        # row 0: refresh button above port selection
        serialSettingsLayout.addWidget(self.serialRefreshButton, 0, 0, 1, 2)
        if self.usePortRows:
            # Port rows mode (dbg page): show port list, hide dropdown and open/close
            self.serialPortCombobox.hide()
            self.serialOpenCloseButton.hide()
            self.serialPortListScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            serialSettingsLayout.addWidget(self.serialPortListScroll, 1, 0, 1, 2)
            serialSettingsLayout.addWidget(serailBaudrateLabel, 2, 0)
            serialSettingsLayout.addWidget(self.serailBaudrateCombobox, 2, 1)
            serialSettingsLayout.addWidget(serailBytesLabel, 3, 0)
            serialSettingsLayout.addWidget(self.serailBytesCombobox, 3, 1)
            serialSettingsLayout.addWidget(serailParityLabel, 4, 0)
            serialSettingsLayout.addWidget(self.serailParityCombobox, 4, 1)
            serialSettingsLayout.addWidget(serailStopbitsLabel, 5, 0)
            serialSettingsLayout.addWidget(self.serailStopbitsCombobox, 5, 1)
            serialSettingsLayout.addWidget(serialFlowControlLabel, 6, 0)
            serialSettingsLayout.addWidget(self.serialFlowControlCombobox, 6, 1)
            serialSettingsLayout.addWidget(self.checkBoxRTS, 7, 0, 1, 1)
            serialSettingsLayout.addWidget(self.checkBoxDTR, 7, 1, 1, 1)
        else:
            # Dropdown mode (other pages): show dropdown and open/close, hide port rows
            serialSettingsLayout.addWidget(serialPortLabek, 1, 0)
            serialSettingsLayout.addWidget(self.serialPortCombobox, 1, 1)
            self.serialPortListScroll.hide()
            serialSettingsLayout.addWidget(serailBaudrateLabel, 2, 0)
            serialSettingsLayout.addWidget(self.serailBaudrateCombobox, 2, 1)
            serialSettingsLayout.addWidget(serailBytesLabel, 3, 0)
            serialSettingsLayout.addWidget(self.serailBytesCombobox, 3, 1)
            serialSettingsLayout.addWidget(serailParityLabel, 4, 0)
            serialSettingsLayout.addWidget(self.serailParityCombobox, 4, 1)
            serialSettingsLayout.addWidget(serailStopbitsLabel, 5, 0)
            serialSettingsLayout.addWidget(self.serailStopbitsCombobox, 5, 1)
            serialSettingsLayout.addWidget(serialFlowControlLabel, 6, 0)
            serialSettingsLayout.addWidget(self.serialFlowControlCombobox, 6, 1)
            serialSettingsLayout.addWidget(self.checkBoxRTS, 7, 0, 1, 1)
            serialSettingsLayout.addWidget(self.checkBoxDTR, 7, 1, 1, 1)
            serialSettingsLayout.addWidget(self.serialOpenCloseButton, 8, 0, 1, 2)
        self.widget.setLayout(serialSettingsLayout)
        self.widgetConfMap["port"]       = self.serialPortCombobox
        self.widgetConfMap["baudrate"]    = self.serailBaudrateCombobox
        self.widgetConfMap["bytesize"]    = self.serailBytesCombobox
        self.widgetConfMap["parity"]      = self.serailParityCombobox
        self.widgetConfMap["stopbits"]    = self.serailStopbitsCombobox
        self.widgetConfMap["flowcontrol"] = self.serialFlowControlCombobox
        self.widgetConfMap["rts"]         = self.checkBoxRTS
        self.widgetConfMap["dtr"]         = self.checkBoxDTR
        self.initEvet()
        return self.widget

    def initEvet(self):
        self.serialPortCombobox.clicked.connect(self.detectSerialPort)
        self.serialRefreshButton.clicked.connect(self.detectSerialPort)
        self.showSerialComboboxSignal.connect(self.showCombobox)
        self.serialPortCombobox.currentIndexChanged.connect(lambda: self.onSerialConfigChanged("port", self.serialPortCombobox, str))
        self.serailBaudrateCombobox.currentIndexChanged.connect(lambda: self.onSerialConfigChanged("baudrate", self.serailBaudrateCombobox, int, caller="index change"))
        self.serailBaudrateCombobox.editTextChanged.connect(lambda: self.onSerialConfigChanged("baudrate", self.serailBaudrateCombobox, int, caller="text change"))
        self.serailBytesCombobox.currentIndexChanged.connect(lambda: self.onSerialConfigChanged("bytesize", self.serailBytesCombobox, int))
        self.serailParityCombobox.currentIndexChanged.connect(lambda: self.onSerialConfigChanged("parity", self.serailParityCombobox, str))
        self.serailStopbitsCombobox.currentIndexChanged.connect(lambda: self.onSerialConfigChanged("stopbits", self.serailStopbitsCombobox, str))
        self.serialFlowControlCombobox.currentIndexChanged.connect(lambda: self.onSerialConfigChanged("flowcontrol", self.serialFlowControlCombobox, str))
        self.checkBoxRTS.clicked.connect(lambda: self.onSerialConfigChanged("rts", self.checkBoxRTS, bool))
        self.checkBoxDTR.clicked.connect(lambda: self.onSerialConfigChanged("dtr", self.checkBoxDTR, bool))
        self.serialOpenCloseButton.clicked.connect(self.openCloseSerial)
        self.showSwitchSignal.connect(self.showSwitch)

    def setSerialPageRequestCallback(self, callback):
        self.serialPageRequestCallback = callback

    def selectSerialPort(self, port):
        if not port:
            return
        for idx in range(self.serialPortCombobox.count()):
            if self.serialPortCombobox.itemText(idx).split(" ")[0] == port:
                self.serialPortCombobox.setCurrentIndex(idx)
                self.highlightSelectedSerialPort()
                return
        self.serialPortCombobox.addItem(port)
        self.serialPortCombobox.setCurrentIndex(self.serialPortCombobox.count() - 1)
        self.highlightSelectedSerialPort()

    def requestSerialPortPage(self, port, action):
        if self.serialPageRequestCallback is not None:
            self.serialPageRequestCallback(port, action)
            return
        if action == "focus":
            self.selectSerialPort(port)
            return
        self.selectSerialPort(port)
        if action == "connect" and not self.isConnected():
            self.openCloseSerial()
        elif action == "disconnect" and self.isConnected():
            self.openCloseSerial()

    def setQuickPortStatuses(self, statuses):
        self.quickPortStatus = statuses.copy() if isinstance(statuses, dict) else {}
        self.refreshSerialPortRows()
        port = self.config.get("port")
        if not port or port not in self.quickPortStatus:
            return
        crossStatus = self.quickPortStatus[port]
        currentText = self.serialOpenCloseButton.text()
        if crossStatus in (ConnectionStatus.CONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.LOSE):
            if currentText != _("CLOSE"):
                self.showSwitchSignal.emit(crossStatus)
        elif crossStatus == ConnectionStatus.CLOSED:
            if currentText != _("OPEN"):
                self.showSwitchSignal.emit(crossStatus)

    def setLockedSerialPorts(self, lockedPorts):
        self.lockedPorts = set(lockedPorts) if lockedPorts else set()
        self.refreshSerialPortRows()

    def refreshSerialPortRows(self):
        for port, row in self.serialPortRowWidgets.items():
            row.setStatus(self.quickPortStatus.get(port, ConnectionStatus.CLOSED), self.config.get("port"))
            row.setLocked(port in self.lockedPorts)

    def updateSerialPortRows(self, items):
        while self.serialPortListLayout.count():
            layoutItem = self.serialPortListLayout.takeAt(0)
            widget = layoutItem.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.serialPortRowWidgets = {}
        for item in items:
            port = item.split(" ")[0].strip()
            if not port:
                continue
            row = SerialPortRowWidget(self, port, item)
            self.serialPortListLayout.addWidget(row)
            self.serialPortRowWidgets[port] = row
        rowHeight = 72
        self.refreshSerialPortRows()
        self.highlightSelectedSerialPort()

    def highlightSelectedSerialPort(self):
        selected = self.config.get("port")
        for port, row in self.serialPortRowWidgets.items():
            row.setSelected(port == selected)
        self.refreshSerialPortRows()

    def onSerialConfigChanged(self, conf_type, obj, value_type, caller=""):
        if conf_type == "port":
            obj.setToolTip(obj.currentText())
            newPort = obj.currentText().split(" ")[0]
            if newPort and not self.isDetectSerialPort and (newPort != self.config["port"] or  not self.com.port):
                self.config["port"] = newPort
                print("-- set to new port:", self.config["port"])
                try:
                    self.com.port = self.config["port"]
                except Exception as e:
                    msg = _("Open Failed") +"\n"+ str(e)
                    self.status = ConnectionStatus.CLOSED
                    self.onConnectionStatus.emit(self.status, msg)
                    self.showSwitchSignal.emit(self.status)
            self.highlightSelectedSerialPort()
        elif conf_type in ["baudrate", "bytesize", "parity", "stopbits"]:
            # custom baudrate input
            text = obj.currentText()
            if conf_type == "baudrate" and ((not text) or text == self.baudrateCustomStr):
                self.serailBaudrateCombobox.clearEditText()
                return
            self.config[conf_type] = value_type(text.split(" ")[0])
            print("-- set serial {} to {}".format(conf_type, self.config[conf_type]))
            if conf_type == "parity":
                self.com.__setattr__(conf_type, self.config[conf_type][0])
            elif conf_type == "stopbits":
                self.com.__setattr__(conf_type, float(self.config[conf_type]))
            else:
                self.com.__setattr__(conf_type, self.config[conf_type])
        elif conf_type == "flowcontrol":
            self.config[conf_type] = value_type(obj.currentText().split(" ")[0])
            if self.config[conf_type] == "XON/XOFF":
                self.com.xonxoff = True
            else:
                self.com.xonxoff = False
            if self.config[conf_type] == "RTS/CTS":
                self.com.rtscts = True
            else:
                self.com.rtscts = False
            if self.config[conf_type] == "DSR/DTR":
                self.com.dsrdtr = True
            else:
                self.com.dsrdtr = False
        elif conf_type in ["rts", "dtr"]:
            self.config[conf_type] = obj.isChecked()
            self.com.__setattr__(conf_type, self.config[conf_type])

    def setSerialConfig(self, conf_type, obj, value):
        def getCommboboxItems(obj):
            values = []
            for i in range(len(obj)):
                values.append(obj.itemText(i))
            return values
        if conf_type == "port":
            values = getCommboboxItems(obj)
            idx = 0
            try:
                idx = values.index(str(value))
            except Exception:
                # print(f"-- set {obj} index {idx} error, value {value}, items {values}")
                pass
            if values:
                obj.setCurrentIndex(idx)
            if value:
                self.config["port"] = str(value).split(" ")[0]
                self.com.port = self.config["port"]
        elif conf_type in ["baudrate", "bytesize", "parity", "stopbits"]:
            values = getCommboboxItems(obj)
            idx = 0
            try:
                idx = values.index(str(value))
            except Exception:
                print(f"-- set {obj} index {idx} error, value {value}, items {values}")
            obj.setCurrentIndex(idx)
            if conf_type == "parity":
                value = value[0]
            elif conf_type == "stopbits":
                value = float(value)
            self.com.__setattr__(conf_type, value)
            if conf_type == "baudrate":
                self.oneByteTime = 1 / (self.com.baudrate / (self.com.bytesize + 2 + self.com.stopbits)) # 1 byte use time
        elif conf_type == "flowcontrol":
            values = getCommboboxItems(obj)
            idx = 0
            try:
                idx = values.index(str(value))
            except Exception:
                print(f"-- set {obj} index {idx} error, value {value}, items {values}")
            obj.setCurrentIndex(idx)
            if value == "XON/XOFF":
                self.com.xonxoff = True
            else:
                self.com.xonxoff = False
            if value == "RTS/CTS":
                self.com.rtscts = True
            else:
                self.com.rtscts = False
            if value == "DSR/DTR":
                self.com.dsrdtr = True
            else:
                self.com.dsrdtr = False
        elif conf_type in ["rts", "dtr"]:
            obj.setChecked(value)
            self.com.__setattr__(conf_type, value)

    def openCloseSerial(self):
        if self.busy:
            return
        self.busy = True
        if self.serialOpenCloseButton.text() == _("OPEN"):
            self.isOpened = False
        else:
            self.isOpened = True
        t = threading.Thread(target=self.openCloseSerialProcess)
        t.setDaemon(True)
        t.start()

    def openCloseSerialProcess(self):
        if self.isOpened:
            print("-- close serial")
            try:
                # set status first to prevent auto reconnect
                self.status = ConnectionStatus.CLOSED
                self.com.close()
            except Exception:
                pass
            self.onConnectionStatus.emit(self.status, "")
            self.showSwitchSignal.emit(self.status)
        else:
            try:
                print("-- open serial")
                self.onConnectionStatus.emit(ConnectionStatus.CONNECTING, "")
                self.com.open()
                self.status = ConnectionStatus.CONNECTED
                self.onConnectionStatus.emit(self.status, "")
                self.showSwitchSignal.emit(self.status)
                self.receiveProcess = threading.Thread(target=self.receiveDataProcess)
                self.receiveProcess.setDaemon(True)
                self.receiveProcess.start()
            except Exception as e:
                try:
                    self.com.close()
                except Exception:
                    pass
                msg = _("Open Failed") +"\n"+ str(e)
                self.hintSignal.emit("error", _("Error"), msg)
                self.status = ConnectionStatus.CLOSED
                self.onConnectionStatus.emit(self.status, msg)
                self.showSwitchSignal.emit(self.status)
        self.busy = False

    def detectSerialPort(self):
        if not self.isDetectSerialPort:
            self.isDetectSerialPort = True
            t = threading.Thread(target=self.detectSerialPortProcess)
            t.setDaemon(True)
            t.start()

    def detectSerialPortProcess(self):
        items = []
        while 1:
            portList = self.findSerialPort()
            if len(portList)>0:
                for p in portList:
                    showStr = "{} {} - {}".format(p.device, p.name, p.description)
                    if p.manufacturer:
                        showStr += ' - {}'.format(p.manufacturer)
                    if p.pid:
                        showStr += ' - pid(0x{:04X})'.format(p.pid)
                    if p.vid:
                        showStr += ' - vid(0x{:04X})'.format(p.vid)
                    if p.serial_number:
                        showStr += ' - v{}'.format(p.serial_number)
                    if p.device.startswith("/dev/cu.Bluetooth-Incoming-Port"):
                        continue
                    items.append(showStr)
                break
            time.sleep(0.5)
        self.showSerialComboboxSignal.emit(items)

    # @pyqtSlot(list)
    def showCombobox(self, items):
        set = -1
        self.serialPortCombobox.clear()
        for item in items:
            self.serialPortCombobox.addItem(item)
            if self.config["port"]:
                index = self.serialPortCombobox.findText(self.config["port"], Qt.MatchContains)
                if index>=0:
                    set = index
        if self.usePortRows:
            self.updateSerialPortRows(items)
        self.isDetectSerialPort = False
        if set >= 0:
            self.serialPortCombobox.setCurrentIndex(set)
        elif self.serialPortCombobox.count() > 0:
            # set to first port in list
            self.serialPortCombobox.setCurrentIndex(0)
            self.onSerialConfigChanged("port", self.serialPortCombobox, str)
        self.highlightSelectedSerialPort()

    # @pyqtSlot(ConnectionStatus)
    def showSwitch(self, status):
        if self.com.port:
            self.quickPortStatus[self.com.port] = status
            self.refreshSerialPortRows()
        if status == ConnectionStatus.CLOSED:
            self.serialOpenCloseButton.setText(_("OPEN"))
            self.serialOpenCloseButton.setProperty("class", "")
        elif status == ConnectionStatus.CONNECTED:
            self.serialOpenCloseButton.setText(_("CLOSE"))
            self.serialOpenCloseButton.setProperty("class", "")
        else:
            self.serialOpenCloseButton.setText(_("CLOSE"))
            self.serialOpenCloseButton.setProperty("class", "warning")
        self.updateStyle(self.serialOpenCloseButton)

    def updateStyle(self, widget):
        self.widget.style().unpolish(widget)
        self.widget.style().polish(widget)
        self.widget.update()

    def findSerialPort(self):
        self.port_list = self.mergeSerialPortsWithRegistry(list(serial.tools.list_ports.comports()))
        return self.port_list

    def mergeSerialPortsWithRegistry(self, ports):
        if not sys.platform.startswith("win"):
            return ports
        known = set(p.device.upper() for p in ports)
        for device, description in self.registrySerialPorts():
            if device.upper() in known:
                continue
            info = serial.tools.list_ports_common.ListPortInfo(device)
            info.name = device
            info.description = description
            info.hwid = description
            ports.append(info)
            known.add(device.upper())
        return sorted(ports, key=lambda p: self.serialPortSortKey(p.device))

    def registrySerialPorts(self):
        ports = []
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
                idx = 0
                while True:
                    try:
                        name, device, _valueType = winreg.EnumValue(key, idx)
                    except OSError:
                        break
                    idx += 1
                    if isinstance(device, str) and device.upper().startswith("COM"):
                        ports.append((device, "{} ({})".format(name, device)))
        except Exception as e:
            print("-- read registry serial ports failed:", e)
        return ports

    def serialPortSortKey(self, device):
        match = re.match(r"COM(\d+)$", device.upper())
        if match:
            return (0, int(match.group(1)))
        return (1, device)

    def portExits(self, port):
        ports = self.findSerialPort()
        devices = []
        for p in ports:
            devices.append(p.device)
        if port in devices:
            return True
        return False

    def receiveDataProcess(self):
        waitingReconnect = False
        self.com.timeout = 0.001
        buffer = b''
        t = 0
        while self.status != ConnectionStatus.CLOSED:
            if waitingReconnect:
                if self.portExits(self.com.port):
                    try:
                        self.onConnectionStatus.emit(ConnectionStatus.CONNECTING, "")
                        self.com.open()
                        print("-- reopen serial")
                        waitingReconnect = False
                        self.onConnectionStatus.emit(ConnectionStatus.CONNECTED, _("Reconnected"))
                        self.showSwitchSignal.emit(ConnectionStatus.CONNECTED)
                        continue
                    except Exception as e:
                        pass
                time.sleep(0.01)
                continue
            try:
                length = max(1, self.com.in_waiting)
                data = self.com.read(length)
                if data:
                    t = time.time()
                    if length == 1 and not buffer: # just start receive
                        buffer += data
                        continue
                    buffer += data
                if buffer and (time.time() - t > self.oneByteTime * 2): # no new data in next frame
                    try:
                        self.onReceived(buffer)
                    except Exception as e:
                        print("-- error in onReceived callback:", e)
                    buffer = b''
            except Exception as e:
                if (self.status != ConnectionStatus.CLOSED):
                    # close as fast as we can to release port
                    try:
                        self.com.close()
                    except Exception:
                        pass
                    waitingReconnect = True
                    self.status = ConnectionStatus.LOSE
                    self.onConnectionStatus.emit(ConnectionStatus.LOSE, _("Connection lose!"))
                    self.showSwitchSignal.emit(ConnectionStatus.LOSE)


    def send(self, data : bytes):
        self.com.write(data)

    def isConnected(self):
        return (self.status == ConnectionStatus.CONNECTED) or (self.status == ConnectionStatus.LOSE)

    def getConnStatus(self):
        return self.status

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)

    conn = Serial()
    conn.onInit({})

    def onReceived(data):
        print(data)
        conn.send(data)

    conn.onReceived = onReceived
    window = conn.onWidget()
    window.show()
    ret = app.exec_()
