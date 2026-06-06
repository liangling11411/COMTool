import sys,os

if sys.version_info < (3, 7):
    print("only support python >= 3.7, but now is {}".format(sys.version_info))
    sys.exit(1)

# Init lanuage first to ensure use function _  works correctly
try:
    import parameters
    import i18n
except ImportError:
    from COMTool import parameters
    from COMTool import i18n

def loadConfig():
    paramObj = parameters.Parameters()
    paramObj.load(parameters.configFilePath)
    return paramObj

log = parameters.log
log.i("loading config from", parameters.configFilePath)
programConfig = loadConfig()
log.i("loading config complete")
i18n.set_locale(programConfig["locale"])

try:
    import helpAbout,autoUpdate
    from Combobox import ComboBox
    from i18n import _
    import version
    import utils_ui
    from conn import ConnectionStatus, conns
    from plugins import builtinPlugins
    from pluginItems import PluginItem
    from widgets import TitleBar, CustomTitleBarWindowMixin, EventFilter, ButtonCombbox, HelpWidget
except ImportError:
    from COMTool import helpAbout,autoUpdate, utils_ui
    from COMTool.Combobox import ComboBox
    from COMTool.i18n import _
    from COMTool import version
    from COMTool.conn import ConnectionStatus, conns
    from COMTool.plugins import builtinPlugins
    from COMTool.pluginItems import PluginItem
    from .widgets import TitleBar, CustomTitleBarWindowMixin, EventFilter, ButtonCombbox, HelpWidget

from PyQt5.QtCore import pyqtSignal, Qt, QRect, QMargins, QCoreApplication, QTimer, QEvent, QObject, QPoint
from PyQt5.QtWidgets import (QApplication, QWidget,QPushButton,QMessageBox,QDesktopWidget,QMainWindow,
                             QVBoxLayout,QHBoxLayout,QGridLayout,QTextEdit,QLabel,QRadioButton,QCheckBox,
                             QLineEdit,QGroupBox,QSplitter,QFileDialog, QScrollArea, QTabWidget, QMenu, QSplashScreen,
                             QInputDialog, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QFontComboBox,
                             QScrollBar)
from PyQt5.QtGui import QIcon,QFont,QTextCursor,QPixmap,QColor, QCloseEvent, QPainter
import qtawesome as qta # https://github.com/spyder-ide/qtawesome
import threading
import time
import copy
from datetime import datetime
import binascii,re
if sys.platform == "win32":
    import ctypes

g_all_windows = []

class BackgroundFrameWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.backgroundPath = ""
        self.backgroundPixmap = QPixmap()
        self.backgroundScaled = QPixmap()
        self.backgroundCropped = QPixmap()
        self.backgroundScaleKey = None
        self.backgroundCropKey = None
        self.backgroundOpacity = 0.35

    def setGlobalBackground(self, path, opacity):
        path = path or ""
        if path and os.path.exists(path):
            if path != self.backgroundPath:
                self.backgroundPixmap = QPixmap(path)
                self.backgroundPath = path
                self.backgroundScaleKey = None
                self.backgroundCropKey = None
        else:
            self.backgroundPath = ""
            self.backgroundPixmap = QPixmap()
            self.backgroundScaled = QPixmap()
            self.backgroundCropped = QPixmap()
            self.backgroundScaleKey = None
            self.backgroundCropKey = None
        try:
            opacity = int(opacity)
        except Exception:
            opacity = 35
        self.backgroundOpacity = max(0, min(100, opacity)) / 100
        self.update()

    def resizeEvent(self, event):
        self.backgroundScaleKey = None
        self.backgroundCropKey = None
        super().resizeEvent(event)

    def scaledBackground(self):
        if self.backgroundPixmap.isNull():
            return QPixmap()
        key = (self.backgroundPath, self.width(), self.height())
        if key != self.backgroundScaleKey or self.backgroundScaled.isNull():
            self.backgroundScaled = self.backgroundPixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self.backgroundScaleKey = key
            self.backgroundCropKey = None
        return self.backgroundScaled

    def croppedBackground(self):
        scaled = self.scaledBackground()
        if scaled.isNull():
            return QPixmap()
        key = (self.backgroundScaleKey, self.width(), self.height())
        if key != self.backgroundCropKey or self.backgroundCropped.isNull():
            x = max(0, int((scaled.width() - self.width()) / 2))
            y = max(0, int((scaled.height() - self.height()) / 2))
            self.backgroundCropped = scaled.copy(x, y, self.width(), self.height())
            self.backgroundCropKey = key
        return self.backgroundCropped

    def drawGlobalBackground(self, painter, targetWidget=None):
        if self.backgroundPixmap.isNull():
            return
        if targetWidget is not None and targetWidget.window() is not self.window():
            window = targetWidget.window()
            targetSize = window.size()
            scaled = self.backgroundPixmap.scaled(targetSize, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = max(0, int((scaled.width() - targetSize.width()) / 2))
            y = max(0, int((scaled.height() - targetSize.height()) / 2))
            source = scaled.copy(x, y, targetSize.width(), targetSize.height())
            origin = targetWidget.mapTo(window, QPoint(0, 0))
            drawX = -origin.x()
            drawY = -origin.y()
        else:
            source = self.croppedBackground()
            drawX = 0
            drawY = 0
            if targetWidget is not None and targetWidget is not self:
                origin = targetWidget.mapTo(self, QPoint(0, 0))
                drawX = -origin.x()
                drawY = -origin.y()
        if source.isNull():
            return
        painter.save()
        painter.setOpacity(self.backgroundOpacity)
        painter.drawPixmap(drawX, drawY, source)
        painter.restore()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        self.drawGlobalBackground(painter)


class BackgroundPaintFilter(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint and self.window.globalBackgroundEnabled():
            frame = getattr(self.window, "frameWidget", None)
            if frame is not None and not frame.backgroundPixmap.isNull():
                painter = QPainter(obj)
                frame.drawGlobalBackground(painter, obj)
        return False

class MainWindow(CustomTitleBarWindowMixin, QMainWindow):
    hintSignal = pyqtSignal(str, str, str) # type(error, warning, info), title, msg
    # statusBarSignal = pyqtSignal(str, str)
    updateSignal = pyqtSignal(object)
    # countUpdateSignal = pyqtSignal(int, int)
    reloadWindowSignal = pyqtSignal(str, str, object)
    receiveCount = 0
    sendCount = 0
    DataPath = "./"
    app = None
    needRestart = False

    def __init__(self,app, eventFilter, config):
        QMainWindow.__init__(self)
        self.app = app
        self.eventFilter = eventFilter
        self.DataPath = parameters.dataPath
        self.config = config
        log.i("init main window")
        self.initVar()
        self.initWindow()
        self.uiLoadConfigs()
        log.i("init main window complete")
        self.loadPluginsInfoList()
        self.loadPluginItems()
        log.i("load plugin items complete")
        self.updateFunctionalButton()
        self.initEvent()

    def initVar(self):
        self.loadPluginStr = _("Load plugin from file")
        self.closeTimerId = None
        self.items = []
        self.pluginClasses = []
        self.helpWindow = None
        self.configDefaults()

    def configDefaults(self):
        if "backgroundImage" not in self.config:
            self.config["backgroundImage"] = ""
        if "backgroundOpacity" not in self.config:
            self.config["backgroundOpacity"] = 35
        try:
            self.config["backgroundOpacity"] = max(0, min(100, int(self.config["backgroundOpacity"])))
        except Exception:
            self.config["backgroundOpacity"] = 35


    def loadPluginsInfoList(self):
        for id, pluginClass in builtinPlugins.items(): 
            self.addPluginInfo(pluginClass)
            self.pluginClasses.append(pluginClass)
        rm = []
        for uid, info in self.config["pluginsInfo"]["external"].items():
            pluginClass = self._importPlugin(info["path"], test=True)
            if pluginClass:
                self.addPluginInfo(pluginClass)
                self.pluginClasses.append(pluginClass)
            else:
                rm.append(uid)
        for uid in rm:
            self.config["pluginsInfo"]["external"].pop(uid)
        # find in python packages
        ignore_paths = ["DLLs"]
        for path in sys.path:
            if os.path.isdir(path) and not path in ignore_paths:
                for name in os.listdir(path):
                    if name.lower().startswith("comtool_plugin_") and not name.endswith("dist-info"):
                        log.i(f"find plugin package <{name}>")
                        pluginClass = __import__(name).Plugin
                        print(pluginClass, self.pluginClasses)
                        if not pluginClass in self.pluginClasses:
                            self.addPluginInfo(pluginClass)
                            self.pluginClasses.append(pluginClass)

    def getPluginClassById(self, id):
        '''
            must call after loadPluginsInfoList
        '''
        for pluginClass in self.pluginClasses:
            if id == pluginClass.id:
                return pluginClass
        return None

    def loadPluginItems(self):
        items = self.config["items"]
        if items:
            for item in items:
                log.i("load plugin item", item["name"])
                pluginClass = self.getPluginClassById(item["pluginId"])
                if pluginClass:
                    setCurr = False
                    if self.config["currItem"] == item["name"]:
                        setCurr = True
                    self.addItem(pluginClass, nameSaved=item["name"], setCurrent=setCurr, connsConfigs = item["config"]["conns"], pluginConfig=item["config"]["plugin"])
        else:  # load builtin plugins
            for id, pluginClass in builtinPlugins.items(): 
                self.addItem(pluginClass)

    def addItem(self, pluginClass, nameSaved = None, setCurrent = False, connsConfigs=None, pluginConfig=None):
        '''
            @name add saved item, not add new item
        '''
        # set here, not set in arg, cause arg can lead to multi item use one object
        if not connsConfigs:
            connsConfigs = {}
        if not pluginConfig:
            pluginConfig = {}
        if nameSaved:
            name = nameSaved
        else:
            numbers = []
            for item in self.items:
                if item.plugin.id == pluginClass.id:
                    if item.name == item.plugin.name:
                        numbers.append(0)
                    elif item.name.startswith(item.plugin.name + " "):
                        try:
                            numbers.append(int(item.name.split(" ")[-1]))
                        except Exception:
                            pass
            if numbers:
                numbers = sorted(numbers)
            if (not numbers) or numbers[0] != 0:
                name = pluginClass.name
            else:
                last = numbers[0]
                number = -1
                for n in numbers[1:]:
                    if n != last + 1:
                        number = last + 1
                        break
                    last = n
                if number < 0:
                    number = numbers[-1] + 1
                name = f'{pluginClass.name} {number}'
        item = PluginItem(name, pluginClass,
                        conns, connsConfigs,
                        self.config, pluginConfig,
                        self.hintSignal, self.reloadWindowSignal,
                        self.onConnChnaged, self.onItemNameChanged,
                        self.onSerialPortPageRequest)
        self.tabAddItem(item)
        self.items.append(item)
        self.updateImportPageButtons()
        if setCurrent:
            self.tabWidget.setCurrentWidget(item.widget)
        if not nameSaved:
            self.config["items"].append({
                    "name": name,
                    "pluginId": pluginClass.id,
                    "config": {
                        "conns": connsConfigs,
                        "plugin": pluginConfig
                        }
                })
        self.refreshSerialQuickPortStatuses()
        if self.globalBackgroundEnabled():
            self.applyGlobalBackgroundWidgetAttributes(True, polish=True)
        return item

    def tabAddItem(self, item):
        self.tabWidget.addTab(item.widget, item.name)
        self.setTabDisplay(self.tabWidget.count() - 1, item)

    def setTabDisplay(self, idx, item):
        self.tabWidget.setTabToolTip(idx, item.name + _(", Double click to detach as a window, right click to rename"))
        isDbg = getattr(item.plugin, "id", "") == "dbg"
        if isDbg:
            portName = self.serialPortForItem(item) or ""
            remark = item.plugin.config.get("portRemark", "") if hasattr(item.plugin, "config") else ""
            self.tabWidget.setTabText(idx, "{}  {}".format(portName, remark) if portName and remark else item.name)
        else:
            self.tabWidget.setTabText(idx, item.name)

    def uniqueItemName(self, name, currentItem=None):
        baseName = name.strip() if name else _("Page")
        if not baseName:
            baseName = _("Page")
        existing = {item.name for item in self.items if item is not currentItem}
        if baseName not in existing:
            return baseName
        number = 1
        while "{} {}".format(baseName, number) in existing:
            number += 1
        return "{} {}".format(baseName, number)

    def onItemNameChanged(self, item, name):
        oldName = item.name
        isDbg = getattr(item.plugin, "id", "") == "dbg"
        if isDbg:
            # For dbg pages: parse port part and remark part
            # name format: "COM1 STM32调试" or just "COM1"
            parts = name.split(" ", 1)
            portPart = parts[0].strip()
            remarkPart = parts[1].strip() if len(parts) > 1 else ""
            # Update the port in serial config if it changed
            conn = self.serialConnForItem(item)
            if conn and portPart:
                oldPort = conn.config.get("port", "")
                if portPart != oldPort:
                    conn.config["port"] = portPart
                    conn.selectSerialPort(portPart)
            # Store remark in plugin config
            if hasattr(item.plugin, "config"):
                item.plugin.config["portRemark"] = remarkPart
            # Ensure unique name by port only (allow same port with different remarks?)
            # Match by port prefix for uniqueness
            newName = self.uniqueDbgItemName(portPart, remarkPart, item)
        else:
            newName = self.uniqueItemName(name, item)
        item.name = newName
        for itemConfig in self.config["items"]:
            if itemConfig["name"] == oldName:
                itemConfig["name"] = newName
                break
        if self.config["currItem"] == oldName:
            self.config["currItem"] = newName
        idx = self.tabWidget.indexOf(item.widget)
        if idx >= 0:
            self.setTabDisplay(idx, item)
        if hasattr(item.plugin, "setPageName"):
            item.plugin.setPageName(newName)
        else:
            item.plugin.pageName = newName
        item.widget.setWindowTitle(newName)
        return newName

    def uniqueDbgItemName(self, portPart, remarkPart, currentItem=None):
        """Ensure unique dbg page name. Same port with different remarks allowed."""
        candidate = portPart
        if remarkPart:
            candidate = "{} {}".format(portPart, remarkPart)
        existing = set()
        for item in self.items:
            if item is not currentItem and getattr(item.plugin, "id", "") == "dbg":
                existing.add(item.name)
        if candidate not in existing:
            return candidate
        # If duplicate, append number
        number = 1
        base = candidate
        while "{} ({})".format(base, number) in existing:
            number += 1
        return "{} ({})".format(base, number)

    def updateImportPageButtons(self):
        for item in self.items:
            item.setImportPageEnabled(item.canImportPage())

    def serialConnForItem(self, item):
        if not item or not getattr(item, "isAddConn", False):
            return None
        for conn in item.conns:
            if getattr(conn, "id", "") == "serial":
                return conn
        return None

    def ensureSerialConnSelected(self, item):
        if not item or not getattr(item, "isAddConn", False):
            return None
        for idx, conn in enumerate(item.conns):
            if getattr(conn, "id", "") == "serial":
                if item.currConnIdx != idx and hasattr(item, "connSelectCommbox"):
                    item.connSelectCommbox.setCurrentIndex(idx)
                return conn
        return None

    def serialPortForItem(self, item):
        conn = self.serialConnForItem(item)
        if conn is not None:
            port = conn.config.get("port")
            if port:
                return port
        try:
            return item.connsConfigs.get("serial", {}).get("port")
        except Exception:
            return None

    def findSerialReceiveItem(self, port, preferConnected=False):
        fallback = None
        # Also check item name prefix for port match (e.g. "COM1 STM32调试")
        for item in self.items:
            if getattr(item.plugin, "id", "") != "dbg":
                continue
            itemPort = self.serialPortForItem(item)
            # Match by serial config port, or by item name prefix
            if itemPort == port:
                pass
            elif item.name.startswith(port + " "):
                pass
            elif item.name == port:
                pass
            else:
                continue
            if not preferConnected:
                return item
            conn = self.serialConnForItem(item)
            if conn is not None and conn.getConnStatus() in (ConnectionStatus.CONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.LOSE):
                return item
            if fallback is None:
                fallback = item
        return fallback

    def cloneSerialPageConfigs(self, sourceItem, port):
        connsConfigs = copy.deepcopy(getattr(sourceItem, "connsConfigs", {}) or {})
        connsConfigs["currConn"] = "serial"
        serialConfig = connsConfigs.get("serial", {})
        if not isinstance(serialConfig, dict):
            serialConfig = {}
        serialConfig["port"] = port
        connsConfigs["serial"] = serialConfig
        pluginConfig = {}
        if getattr(sourceItem.plugin, "id", "") == "dbg":
            pluginConfig = copy.deepcopy(sourceItem.plugin.config)
            pluginConfig["saveLog"] = False
        return connsConfigs, pluginConfig

    def showNewDbgPageDialog(self):
        """Show dialog to pick serial port and enter remark for new dbg page."""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QDialogButtonBox, QMessageBox
        # Gather available serial ports
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            QMessageBox.warning(self, _("Warning"), _("No serial ports detected. Please connect a device first."))
            return None
        # Collect ports already used by existing dbg pages
        usedPorts = set()
        for item in self.items:
            if getattr(item.plugin, "id", "") == "dbg":
                port = self.serialPortForItem(item)
                if port:
                    usedPorts.add(port)
        portItems = []
        for p in ports:
            if p.device in usedPorts:
                continue  # Skip ports that already have a dbg page
            showStr = "{} {} - {}".format(p.device, p.name, p.description)
            if p.manufacturer:
                showStr += " - {}".format(p.manufacturer)
            portItems.append((p.device, showStr))
        if not portItems:
            QMessageBox.warning(self, _("Warning"), _("All serial ports already have receive pages."))
            return None
        dialog = QDialog(self)
        dialog.setWindowTitle(_("New Receive Page"))
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        # Port selector
        portLabel = QLabel(_("Select serial port:"))
        layout.addWidget(portLabel)
        portCombo = QComboBox()
        for device, showStr in portItems:
            portCombo.addItem(showStr, device)
        layout.addWidget(portCombo)
        # Remark
        remarkLabel = QLabel(_("Remark (optional):"))
        layout.addWidget(remarkLabel)
        remarkInput = QLineEdit()
        remarkInput.setPlaceholderText(_("e.g. STM32 debug"))
        layout.addWidget(remarkInput)
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return None
        port = portCombo.currentData()
        remark = remarkInput.text().strip()
        return port, remark

    def createSerialReceiveItem(self, sourceItem, port, remark=None):
        pluginClass = self.getPluginClassById("dbg")
        if pluginClass is None:
            return None
        connsConfigs, pluginConfig = self.cloneSerialPageConfigs(sourceItem, port)
        # Store remark in plugin config
        if remark:
            pluginConfig["portRemark"] = remark
        item = self.addItem(pluginClass, setCurrent=True, connsConfigs=connsConfigs, pluginConfig=pluginConfig)
        name = port
        if remark:
            name = "{} {}".format(port, remark)
        self.onItemNameChanged(item, name)
        if sourceItem is not None and hasattr(item, "copyPanelStateFrom"):
            item.copyPanelStateFrom(sourceItem, forceVisible=True)
            QTimer.singleShot(0, lambda: item.copyPanelStateFrom(sourceItem, forceVisible=True))
        return item

    def setSerialItemOpen(self, item, openNow):
        conn = self.ensureSerialConnSelected(item) if openNow else self.serialConnForItem(item)
        if conn is None:
            return
        connected = conn.getConnStatus() in (ConnectionStatus.CONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.LOSE)
        if openNow and not connected:
            conn.openCloseSerial()
        elif (not openNow) and connected:
            conn.openCloseSerial()

    def onSerialPortPageRequest(self, sourceItem, port, action):
        if not port:
            return
        if action == "disconnect":
            item = self.findSerialReceiveItem(port, preferConnected=True)
            if item is not None:
                self.setSerialItemOpen(item, False)
            self.refreshSerialQuickPortStatuses()
            return

        item = self.findSerialReceiveItem(port)
        if item is None:
            item = self.createSerialReceiveItem(sourceItem, port)
        if item is None:
            return
        if action == "connect":
            self.tabWidget.setCurrentWidget(item.widget)
            self.setSerialItemOpen(item, True)
        elif action in ("focus", "open"):
            self.tabWidget.setCurrentWidget(item.widget)
        self.refreshSerialQuickPortStatuses()

    def serialPortStatusMap(self):
        statuses = {}
        lockedPorts = set()
        priority = {
            ConnectionStatus.CLOSED: 0,
            ConnectionStatus.CONNECTING: 1,
            ConnectionStatus.LOSE: 2,
            ConnectionStatus.CONNECTED: 3,
        }
        for item in self.items:
            conn = self.serialConnForItem(item)
            if conn is None:
                continue
            port = conn.config.get("port")
            if not port:
                continue
            status = conn.getConnStatus()
            old = statuses.get(port, ConnectionStatus.CLOSED)
            if priority.get(status, 0) >= priority.get(old, 0):
                statuses[port] = status
            # Track ports locked by non-dbg pages
            isDbg = getattr(item.plugin, "id", "") == "dbg"
            if not isDbg and status in (ConnectionStatus.CONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.LOSE):
                lockedPorts.add(port)
        return statuses, lockedPorts

    def refreshSerialQuickPortStatuses(self):
        statuses, lockedPorts = self.serialPortStatusMap()
        for item in self.items:
            if hasattr(item, "setSerialQuickPortStatuses"):
                item.setSerialQuickPortStatuses(statuses)
            # Pass locked ports to serial connections
            if getattr(item, "isAddConn", False):
                for conn in item.conns:
                    if hasattr(conn, "setLockedSerialPorts"):
                        conn.setLockedSerialPorts(lockedPorts)

    def onConnChnaged(self, plugin, status:ConnectionStatus, msg):
        for item in self.items:
            if item.plugin == plugin:
                for i in range(self.tabWidget.count()):
                    if self.tabWidget.widget(i) == item.widget:
                        self.setTabIcon(status, i)
                        break
                item.widget.setWindowTitle(item.name + " - {}".format(_("Connected" if status == ConnectionStatus.CONNECTED else _("Connection lose") if status == ConnectionStatus.LOSE else _("Disconnected"))))
        self.updateImportPageButtons()
        self.refreshSerialQuickPortStatuses()

    def setTabIcon(self, status:ConnectionStatus, i:int):
        if status == ConnectionStatus.CONNECTED:
            self.tabWidget.setTabIcon(i, qta.icon("fa.circle", color="#4caf50"))
        elif status == ConnectionStatus.LOSE:
            self.tabWidget.setTabIcon(i, qta.icon("fa.circle", color="orange"))
        else:
            self.tabWidget.setTabIcon(i, QIcon())

    def addPluginInfo(self, pluginClass):
        self.pluginsSelector.insertItem(self.pluginsSelector.count() - 1,
                                        f'{pluginClass.name} - {pluginClass.id}')

    def _importPlugin(self, path, test = False):
        if not os.path.exists(path):
            return None
        dir = os.path.dirname(path)
        name = os.path.splitext(os.path.basename(path))[0]
        sys.path.insert(0, dir)
        try:
            print("import")
            pluginClass = __import__(name).Plugin
        except Exception as e:
            import traceback
            msg = traceback.format_exc()
            self.hintSignal.emit("error", _("Error"), '{}: {}'.format(_("Load plugin failed"), msg))
            return None
        if test:
            sys.path.remove(dir)
        return pluginClass

    def loadExternalPlugin(self, path):
        extPlugsInfo = self.config["pluginsInfo"]["external"]
        found = False
        for uid, info in extPlugsInfo.items():
            if info["path"] == path:
                for pluginClass in self.pluginClasses:
                    # same plugin
                    if uid == pluginClass.id:
                        self.addItem(pluginClass, setCurrent = True)
                        found = True
                        break
                if found:
                    return True, ""
        pluginClass = self._importPlugin(path)
        if not pluginClass:
            return False, _("Load plugin fail")
        extPlugsInfo[pluginClass.id] = {
            "path": path
        }
        if not pluginClass in self.pluginClasses:
            self.pluginClasses.append(pluginClass)
            self.addPluginInfo(pluginClass)
        # find old item config for this plugin and recover
        oldFound = False
        for item in self.config["items"]:
            if item["pluginId"] == pluginClass.id:
                self.addItem(pluginClass, nameSaved=item["name"], setCurrent=True, connsConfigs=item["config"]["conns"], pluginConfig=item["config"]["plugin"])
                oldFound = True
                break
        if not oldFound:
            self.addItem(pluginClass, setCurrent=True)
        return True, ""

    def onPluginSelectorChanged(self, idx):
        text = self.pluginsSelector.currentText()
        if text == self.loadPluginStr:
            oldPath = os.getcwd()
            fileName_choose, filetype = QFileDialog.getOpenFileName(self,
                                    _("Select file"),
                                    oldPath,
                                    _("python script (*.py)"))
            if fileName_choose != "":
                ok, msg = self.loadExternalPlugin(fileName_choose)
                if not ok:
                    self.hintSignal.emit("error", _("Error"), f'{_("Load plugin error")}: {msg}')
        else:
            loadID = text.split("-")[-1].strip()
            for pluginClass in self.pluginClasses:
                if loadID == pluginClass.id:
                    if pluginClass.id == "dbg":
                        # Show dialog for dbg pages
                        result = self.showNewDbgPageDialog()
                        if result is None:
                            break
                        port, remark = result
                        connsConfigs = {"currConn": "serial", "serial": {"port": port}}
                        pluginConfig = {"portRemark": remark}
                        item = self.addItem(pluginClass, setCurrent=True, connsConfigs=connsConfigs, pluginConfig=pluginConfig)
                        name = port
                        if remark:
                            name = "{} {}".format(port, remark)
                        self.onItemNameChanged(item, name)
                    else:
                        self.addItem(pluginClass, setCurrent = True)
                    break

    def initWindow(self):
        # set skin for utils_ui
        utils_ui.setSkin(self.config["skin"])
        # menu layout
        self.settingsButton = QPushButton()
        self.skinButton = ButtonCombbox(icon=None, btnClass="menuItem", btnId="menuItem2")
        self.languageCombobox = ButtonCombbox(icon=None, btnClass="menuItem", btnId="menuItemLang")
        self.languages = i18n.get_languages()
        for locale in self.languages:
            self.languageCombobox.addItem(self.languages[locale])
        self.skinNames = utils_ui.get_skins()
        self.skinActionSelectBackground = len(self.skinNames)
        self.skinActionOpacity = self.skinActionSelectBackground + 1
        self.skinActionClearBackground = self.skinActionSelectBackground + 2
        self.ignoreSkinChange = False
        for skin_name in self.skinNames:
            self.skinButton.addItem(_(skin_name))
        self.skinButton.addItem(_("Select background image"))
        self.skinButton.addItem(_("Background opacity"))
        self.skinButton.addItem(_("Clear background image"))
        self.aboutButton = QPushButton()
        self.functionalButton = QPushButton()
        self.encodingCombobox = ComboBox()
        self.supportedEncoding = parameters.encodings
        for encoding in self.supportedEncoding:
            self.encodingCombobox.addItem(encoding)
        self.settingsButton.setProperty("class", "menuItem")
        self.aboutButton.setProperty("class", "menuItem")
        self.functionalButton.setProperty("class", "menuItem")
        self.settingsButton.setObjectName("menuItem1")
        self.aboutButton.setObjectName("menuItem3")
        self.functionalButton.setObjectName("menuItem4")
        self.settingsButton.setToolTip(_("Show or hide settings panel"))
        self.skinButton.setToolTip(_("Switch skin"))
        self.languageCombobox.setToolTip(_("Switch language"))
        self.aboutButton.setToolTip(_("About"))
        self.functionalButton.setToolTip(_("Show or hide custom send panel"))
        self.encodingCombobox.setToolTip(_("Text encoding for send and receive data"))
        # plugins slector
        self.pluginsSelector = ButtonCombbox(icon="fa.plus", btnClass="smallBtn2")
        self.pluginsSelector.setToolTip(_("Add plugin page"))
        self.pluginsSelector.addItem(self.loadPluginStr)
        self.pluginsSelector.activated.connect(self.onPluginSelectorChanged)

        # title bar
        title = parameters.appName+" v"+version.__version__
        iconPath = self.DataPath+"/"+parameters.appIcon
        log.i("icon path: " + iconPath)
        self.titleBar = TitleBar(self, icon=iconPath, title=title, brothers=[], widgets=[[self.skinButton, self.languageCombobox, self.aboutButton], []])
        CustomTitleBarWindowMixin.__init__(self, titleBar=self.titleBar, init = True)

        # root layout
        self.frameWidget = BackgroundFrameWidget()
        self.frameWidget.setObjectName("backgroundFrame")
        self.frameWidget.setMouseTracking(True)
        self.frameWidget.setLayout(self.rootLayout)
        self.setCentralWidget(self.frameWidget)
        self.contentWidget.setObjectName("contentWidget")
        # tab widgets
        self.tabWidget = QTabWidget()
        self.tabWidget.setTabsClosable(True)
        self.tabWidget.tabBar().setMovable(True)
        self.tabWidget.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        # tab left menu
        tabConerWidget = QWidget()
        tabConerWidget.setObjectName("tabConerWidget")
        tabConerLayout = QHBoxLayout()
        tabConerLayout.setSpacing(0)
        tabConerLayout.setContentsMargins(0, 0, 0, 0)
        tabConerWidget.setLayout(tabConerLayout)
        tabConerLayout.addWidget(self.settingsButton)
        # tab right menu
        tabConerWidgetRight = QWidget()
        tabConerWidgetRight.setObjectName("tabConerWidgetRight")
        tabConerLayoutRight = QHBoxLayout()
        tabConerLayoutRight.setSpacing(0)
        tabConerLayoutRight.setContentsMargins(0, 0, 0, 0)
        tabConerWidgetRight.setLayout(tabConerLayoutRight)
        tabConerLayoutRight.addWidget(self.pluginsSelector)
        tabConerLayoutRight.addWidget(self.encodingCombobox)
        tabConerLayoutRight.addWidget(self.functionalButton)
        self.tabWidget.setCornerWidget(tabConerWidget, Qt.TopLeftCorner)
        self.tabWidget.setCornerWidget(tabConerWidgetRight, Qt.TopRightCorner)
        self.contentLayout = QVBoxLayout()
        self.contentWidget.setLayout(self.contentLayout)
        self.contentLayout.setContentsMargins(10, 0, 10, 10)
        self.contentLayout.addWidget(self.tabWidget)

        if sys.platform == 'darwin':
            self.macOsAddDockMenu()

        windowSize = self.config["windowSize"] if "windowSize" in self.config else {}
        width = int(windowSize.get("width", 850)) if isinstance(windowSize, dict) else 850
        height = int(windowSize.get("height", 500)) if isinstance(windowSize, dict) else 500
        self.resize(max(640, width), max(420, height))
        self.MoveToCenter()
        self.show()

    def add_new_window(self):
        import copy
        mainWindow = MainWindow(self.app, self.eventFilter, copy.deepcopy(self.config))
        self.eventFilter.listenWindow(mainWindow)
        g_all_windows.append(mainWindow)

    def macOsAddDockMenu(self):
        self.dockMenu = QMenu(self)
        self.dockMenu.addAction(_('New Window'),
                                self.add_new_window)
        self.dockMenu.setAsDockMenu()
        self.app.setAttribute(Qt.AA_DontShowIconsInMenus, True)

    def initEvent(self):
        # menu
        self.settingsButton.clicked.connect(self.toggleSettings)
        self.languageCombobox.currentIndexChanged.connect(self.onLanguageChanged)
        self.encodingCombobox.currentIndexChanged.connect(lambda: self.bindVar(self.encodingCombobox, self.config, "encoding"))
        self.functionalButton.clicked.connect(self.toggleFunctional)
        self.skinButton.currentIndexChanged.connect(self.skinChange)
        self.aboutButton.clicked.connect(self.showAbout)
        # main
        self.tabWidget.currentChanged.connect(self.onSwitchTab)
        self.tabWidget.tabCloseRequested.connect(self.closeTab)
        self.tabWidget.tabBarDoubleClicked.connect(self.onTabDoubleClicked)
        self.tabWidget.tabBar().customContextMenuRequested.connect(self.showTabContextMenu)
        # others
        self.updateSignal.connect(self.showUpdate)
        self.hintSignal.connect(self.showHint)
        self.reloadWindowSignal.connect(self.onReloadWindow)

    def bindVar(self, uiObj, varObj, varName: str, vtype=None, vErrorMsg="", checkVar=lambda v:v, invert = False):
        objType = type(uiObj)
        if objType == QCheckBox:
            v = uiObj.isChecked()
            if hasattr(varObj, varName):
                varObj.__setattr__(varName, v if not invert else not v)
            else:
                varObj[varName] = v if not invert else not v
            return
        elif objType == QLineEdit:
            v = uiObj.text()
        elif objType == ComboBox:
            if hasattr(varObj, varName):
                varObj.__setattr__(varName, uiObj.currentText())
            else:
                varObj[varName] = uiObj.currentText()
            return
        elif objType == QRadioButton:
            v = uiObj.isChecked()
            if hasattr(varObj, varName):
                varObj.__setattr__(varName, v if not invert else not v)
            else:
                varObj[varName] = v if not invert else not v
            return
        else:
            raise Exception("not support this object")
        if vtype:
            try:
                v = vtype(v)
            except Exception:
                uiObj.setText(str(varObj.__getattribute__(varName)))
                self.hintSignal.emit("error", _("Error"), vErrorMsg)
                return
        try:
            v = checkVar(v)
        except Exception as e:
            self.hintSignal.emit("error", _("Error"), str(e))
            return
        varObj.__setattr__(varName, v)

    def onSwitchTab(self, idx):
        item = self.getCurrentItem()
        if item:
            self.config["currItem"] = item.name
            item.plugin.onActive()
        self.updateFunctionalButton()

    def itemByTabIndex(self, idx):
        if idx < 0:
            return None
        widget = self.tabWidget.widget(idx)
        for item in self.items:
            if item.widget == widget:
                return item
        return None

    def showTabContextMenu(self, pos):
        tabBar = self.tabWidget.tabBar()
        idx = tabBar.tabAt(pos)
        item = self.itemByTabIndex(idx)
        if item is None:
            return
        menu = QMenu(self)
        renameAction = menu.addAction(_("Rename"))
        saveAction = menu.addAction(_("Save page"))
        menu.addSeparator()
        moveLeftAction = menu.addAction(_("Move to leftmost"))
        moveRightAction = menu.addAction(_("Move to rightmost"))
        menu.addSeparator()
        closeOthersAction = menu.addAction(_("Close other pages"))
        closeAction = menu.addAction(_("Close page"))
        if self.tabWidget.count() <= 1:
            closeOthersAction.setEnabled(False)
            closeAction.setEnabled(False)
        action = menu.exec_(tabBar.mapToGlobal(pos))
        if action == renameAction:
            self.renameTab(idx)
        elif action == saveAction:
            item.selectSharefile()
        elif action == moveLeftAction:
            self.moveTabTo(idx, 0)
        elif action == moveRightAction:
            self.moveTabTo(idx, self.tabWidget.count() - 1)
        elif action == closeOthersAction:
            self.closeOtherTabs(idx)
        elif action == closeAction:
            self.closeTab(idx)

    def moveTabTo(self, fromIdx, toIdx):
        if fromIdx == toIdx:
            return
        tabBar = self.tabWidget.tabBar()
        tabBar.moveTab(fromIdx, toIdx)
        # Sync self.items order
        item = self.items.pop(fromIdx)
        self.items.insert(toIdx, item)

    def closeOtherTabs(self, keepIdx):
        for i in range(self.tabWidget.count() - 1, -1, -1):
            if i != keepIdx:
                self.closeTab(i)

    def renameTab(self, idx):
        item = self.itemByTabIndex(idx)
        if item is None:
            return
        isDbg = getattr(item.plugin, "id", "") == "dbg"
        if isDbg:
            # For dbg pages: only allow editing the remark part
            portPart = self.serialPortForItem(item) or item.name.split(" ")[0]
            oldRemark = item.plugin.config.get("portRemark", "") if hasattr(item.plugin, "config") else ""
            remark, ok = QInputDialog.getText(self, _("Rename remark"), _("Remark for") + " " + portPart, text=oldRemark)
            if not ok:
                return
            remark = remark.strip()
            newName = portPart
            if remark:
                newName = "{} {}".format(portPart, remark)
            if newName == item.name:
                return
        else:
            newName, ok = QInputDialog.getText(self, _("Rename"), _("Page name"), text=item.name)
            if not ok:
                return
            newName = newName.strip()
            if not newName or newName == item.name:
                return
            if self.uniqueItemName(newName, item) != newName:
                QMessageBox.warning(self, _("Warning"), _("Page name already exists"))
                return
        self.onItemNameChanged(item, newName)

    def closeTab(self, idx):
        # only one, ignore
        if self.tabWidget.count() == 1:
            return
        item = None
        for _item in self.items:
            if _item.widget == self.tabWidget.widget(idx):
                item = _item
                break
        if item is None:
            return
        reply = QMessageBox.question(self, _("Save page?"),
                                     _("Save this page before closing it?"),
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                                     QMessageBox.Yes)
        if reply == QMessageBox.Cancel:
            return
        if reply == QMessageBox.Yes and not item.selectSharefile():
            return
        self.tabWidget.removeTab(idx)
        for _item in self.config["items"]:
            if _item["name"] == item.name:
                self.config["items"].remove(_item)
                break
        item.onDel()
        self.items.remove(item)

    def onTabDoubleClicked(self, idx):
        item = self.getCurrentItem()
        self.tabWidget.removeTab(idx)
        parent = item.widget.parent()
        item.widget.setWindowFlag(Qt.Window) # this method is not stable in QT, do not use it
        # item.widget.setParent(None)
        item.widget.setWindowTitle(item.name)
        item.widget.closeEvent = lambda event: self.onPluginWindowClose(item, parent)
        item.widget.show()
        self.applyGlobalBackgroundWidgetAttributes(self.globalBackgroundEnabled(), polish=True)
        self.updateGlobalBackgroundContainers()

    def onPluginWindowClose(self, item, parent):
        self.recoverTab(item, parent)

    def recoverTab(self, item, parent):
        def add(i):
            self.tabWidget.insertTab(i, item.widget, item.name)
            self.setTabDisplay(i, item)
            self.tabWidget.setCurrentIndex(i)
            item.widget.setWindowFlag(Qt.Window, False)
            # item.widget.setParent(parent)
            status = item.plugin.getConnStatus()
            self.setTabIcon(status, i)
            self.applyGlobalBackgroundWidgetAttributes(self.globalBackgroundEnabled(), polish=True)
            self.updateGlobalBackgroundContainers()
        # prevent close and add this widget to tab
        insertIdx = self.tabWidget.count()
        idx = self.items.index(item)
        for i in range(self.tabWidget.count()):
            widget = self.tabWidget.widget(i)
            for _item in self.items:
                if _item.widget == widget:
                    idx2 = self.items.index(_item)
                    break
            if idx2 > idx:
                insertIdx = i
                break
        add(insertIdx)


    def updateStyle(self, widget):
        self.frameWidget.style().unpolish(widget)
        self.frameWidget.style().polish(widget)
        self.frameWidget.update()

    def onLanguageChanged(self):
        idx = self.languageCombobox.currentIndex()
        locale = list(self.languages.keys())[idx]
        self.config["locale"] = locale
        i18n.set_locale(locale)
        reply = QMessageBox.question(self, _('Restart now?'),
                                     _("language changed to: ") + self.languages[self.config["locale"]] + "\n" + _("Restart software to take effect now?"), QMessageBox.Yes |
                                     QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.needRestart = True
            self.close()

    def onReloadWindow(self, title, msg, callback):
        if not title:
            title = _('Restart now?')
        reply = QMessageBox.question(self, title, msg,
                            QMessageBox.Yes |
                            QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            callback(True)
            self.needRestart = True
            self.close()
        else:
            callback(False)

    def MoveToCenter(self):
        qr = self.frameGeometry()
        cp = QDesktopWidget().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def showHint(self, info_type: str, title: str, msg: str):
        if info_type == "info":
            QMessageBox.information(self, title, msg)
        elif info_type == "warning":
            QMessageBox.warning(self, title, msg)
        elif info_type == "error":
            QMessageBox.critical(self, title, msg)

    def closeEvent(self, event):
        if self.closeTimerId:
            event.accept()
            return
        print("----- close event")
        # reply = QMessageBox.question(self, 'Sure To Quit?',
        #                              "Are you sure to quit?", QMessageBox.Yes |
        #                              QMessageBox.No, QMessageBox.No)
        if 1: # reply == QMessageBox.Yes:
            geometry = self.normalGeometry() if self.windowState() != Qt.WindowNoState else self.geometry()
            if geometry.isValid():
                self.config["windowSize"] = {
                    "width": geometry.width(),
                    "height": geometry.height()
                }
            self.receiveProgressStop = True
            # inform plugins
            for item in self.items:
                item.onDel()
            self.saveConfig()
            # actual exit after 500ms
            self.closeTimerId = self.startTimer(500)
            self.setWindowTitle(_("Closing ..."))
            self.titleBar.setTitle(_("Closing ..."))
            self.setEnabled(False)
            if self.helpWindow:
                self.helpWindow.close()
            event.ignore()
        else:
            event.ignore()

    def timerEvent(self, e):
        if self.closeTimerId:
            log.i("Close window")
            self.killTimer(self.closeTimerId)
            self.close()

    def saveConfig(self):
        # print("save config:", self.config)
        self.config.save(parameters.configFilePath)
        print("save config compelte")

    def uiLoadConfigs(self):
        # language
        try:
            idx = list(self.languages.keys()).index(self.config["locale"])
        except Exception:
            idx = 0
        self.languageCombobox.setCurrentIndex(idx)
        # skin
        try:
            idx = self.skinNames.index(self.config["skin"])
        except Exception:
            idx = 0
        self.skinButton.setCurrentIndex(idx)
        # encoding
        self.encodingCombobox.setCurrentIndex(self.supportedEncoding.index(self.config["encoding"]))

    def keyPressEvent(self, event):
        CustomTitleBarWindowMixin.keyPressEvent(self, event)
        item = self.getCurrentItem()
        item.onKeyPressEvent(event)

    def keyReleaseEvent(self,event):
        CustomTitleBarWindowMixin.keyReleaseEvent(self, event)
        item = self.getCurrentItem()
        item.onKeyReleaseEvent(event)

    def getCurrentItem(self, idx = False):
        widget = self.tabWidget.currentWidget()
        for item in self.items:
            if item.widget == widget:
                if idx:
                    return self.tabWidget.indexOf(widget), item
                return item

    def toggleSettings(self):
        widget = self.getCurrentItem().settingWidget
        if widget.isVisible():
            self.hideSettings()
        else:
            self.showSettings()

    def showSettings(self):
        widget = self.getCurrentItem().settingWidget
        widget.show()
        self.settingsButton.setStyleSheet(
            parameters.strStyleShowHideButtonLeft.replace("$DataPath",self.DataPath))

    def hideSettings(self):
        widget = self.getCurrentItem().settingWidget
        widget.hide()
        self.settingsButton.setStyleSheet(
            parameters.strStyleShowHideButtonRight.replace("$DataPath", self.DataPath))

    def toggleFunctional(self):
        widget = self.getCurrentItem().functionalWidget
        if widget is None:
            return
        if widget.isVisible():
            self.hideFunctional()
        else:
            self.showFunctional()

    def showFunctional(self):
        widget = self.getCurrentItem().functionalWidget
        if not widget is None:
            widget.show()
        self.updateFunctionalButton()

    def hideFunctional(self):
        widget = self.getCurrentItem().functionalWidget
        if not widget is None:
            widget.hide()
        self.updateFunctionalButton()

    def updateFunctionalButton(self):
        item = self.getCurrentItem()
        if item and item.functionalWidget and item.functionalWidget.isVisible():
            self.functionalButton.setStyleSheet(
                parameters.strStyleShowHideButtonRight.replace("$DataPath",self.DataPath))
        else:
            self.functionalButton.setStyleSheet(
                parameters.strStyleShowHideButtonLeft.replace("$DataPath", self.DataPath))

    def skinChange(self):
        if self.ignoreSkinChange:
            return
        idx = self.skinButton.currentIndex()
        if idx == self.skinActionSelectBackground:
            self.selectGlobalBackgroundImage()
            self.restoreSkinButtonIndex()
            return
        if idx == self.skinActionOpacity:
            self.changeGlobalBackgroundOpacity()
            self.restoreSkinButtonIndex()
            return
        if idx == self.skinActionClearBackground:
            self.clearGlobalBackgroundImage()
            self.restoreSkinButtonIndex()
            return
        if idx < 0 or idx >= len(self.skinNames):
            self.restoreSkinButtonIndex()
            return
        skin = self.skinNames[idx]
        utils_ui.setSkin(skin)
        self.config["skin"] = skin
        self.applyAppStyle()
        for item in self.items:
            item.plugin.onSkinChanged(skin)

    def restoreSkinButtonIndex(self):
        try:
            idx = self.skinNames.index(self.config["skin"])
        except Exception:
            idx = 0
        self.ignoreSkinChange = True
        self.skinButton.setCurrentIndex(idx)
        self.ignoreSkinChange = False

    def configGet(self, key, default=None):
        return self.config[key] if key in self.config else default

    def backgroundPanelQss(self):
        path = self.configGet("backgroundImage", "")
        if not path or not os.path.exists(path):
            return ""
        dark = self.configGet("skin", "light") == "dark"
        groupPanel = "rgba(33,33,33,86)" if dark else "rgba(245,245,245,92)"
        edit = "rgba(58,58,58,116)" if dark else "rgba(255,255,255,132)"
        inputPanel = "rgba(58,58,58,138)" if dark else "rgba(255,255,255,156)"
        tabPanel = "rgba(58,58,58,96)" if dark else "rgba(230,230,230,112)"
        return """
*[globalBackgroundContainer="true"],
QWidget#backgroundFrame,
QWidget#contentWidget,
QWidget#tabConerWidget,
QWidget#tabConerWidgetRight,
QWidget[class="pageWrapper"] {
    background: transparent;
}
.TitleBar {
    background-color: transparent;
}
QFrame,
QSplitter,
QTabWidget::pane,
QStackedWidget,
QScrollArea,
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget,
QWidget[class="contentWrapper"],
QWidget[class="settingWidget"],
QWidget[class="functionalWidget"] {
    background-color: transparent;
}
QGroupBox {
    background-color: %s;
}
QAbstractScrollArea,
QTextEdit,
QPlainTextEdit,
QListView,
QTreeWidget,
QTableWidget,
QTableView,
QListWidget,
QTextBrowser {
    background-color: %s;
}
QAbstractScrollArea::viewport {
    background-color: transparent;
}
QLineEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox,
QFontComboBox {
    background-color: %s;
}
QTabBar::tab:!selected {
    background-color: %s;
}
*[globalBackgroundContainer="true"] QLabel,
*[globalBackgroundContainer="true"] QCheckBox,
*[globalBackgroundContainer="true"] QRadioButton,
*[globalBackgroundContainer="true"] QGroupBox {
    background: transparent;
}
*[globalBackgroundContainer="true"] QGroupBox::title {
    background: transparent;
}
""" % (groupPanel, edit, inputPanel, tabPanel)

    def globalBackgroundEnabled(self):
        path = self.configGet("backgroundImage", "")
        return bool(path and os.path.exists(path))

    def globalBackgroundRoots(self):
        roots = []
        if hasattr(self, "frameWidget"):
            roots.append(self.frameWidget)
        if hasattr(self, "items"):
            for item in self.items:
                widget = getattr(item, "widget", None)
                if widget is not None:
                    roots.append(widget)
        unique = []
        seen = set()
        for widget in roots:
            try:
                key = id(widget)
            except RuntimeError:
                continue
            if key in seen:
                continue
            seen.add(key)
            unique.append(widget)
        return unique

    def applyGlobalBackgroundWidgetAttributes(self, enabled, polish=False):
        if not hasattr(self, "frameWidget"):
            return
        if enabled and not hasattr(self, "backgroundPaintFilter"):
            self.backgroundPaintFilter = BackgroundPaintFilter(self)
        controls = (
            QPushButton, QLineEdit, QTextEdit, QPlainTextEdit, QCheckBox, QRadioButton,
            QComboBox, ComboBox, QSpinBox, QDoubleSpinBox, QFontComboBox, QScrollBar
        )
        widgets = []
        seen = set()
        for root in self.globalBackgroundRoots():
            candidates = [root]
            candidates.extend(root.findChildren(QWidget))
            for widget in candidates:
                if id(widget) in seen:
                    continue
                seen.add(id(widget))
                widgets.append(widget)
        for widget in widgets:
            isContainer = not isinstance(widget, controls)
            widget.setProperty("globalBackgroundContainer", "true" if enabled and isContainer else "")
            if isContainer:
                widget.setAutoFillBackground(False)
                widget.setAttribute(Qt.WA_TranslucentBackground, enabled)
                installed = bool(widget.property("globalBackgroundPaintFilterInstalled"))
                if enabled and not installed and widget is not self.frameWidget:
                    widget.installEventFilter(self.backgroundPaintFilter)
                    widget.setProperty("globalBackgroundPaintFilterInstalled", True)
                elif (not enabled) and installed and hasattr(self, "backgroundPaintFilter"):
                    widget.removeEventFilter(self.backgroundPaintFilter)
                    widget.setProperty("globalBackgroundPaintFilterInstalled", False)
            if polish:
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()

    def updateGlobalBackgroundContainers(self):
        if not hasattr(self, "frameWidget"):
            return
        seen = set()
        for root in self.globalBackgroundRoots():
            widgets = [root]
            widgets.extend(root.findChildren(QWidget))
            for widget in widgets:
                if id(widget) in seen:
                    continue
                seen.add(id(widget))
                if widget.property("globalBackgroundContainer") != "true" and not widget.property("globalBackgroundPaintFilterInstalled"):
                    continue
                widget.update()

    def applyAppStyle(self):
        skin = self.configGet("skin", "light")
        self.applyGlobalBackgroundWidgetAttributes(self.globalBackgroundEnabled())
        with open(self.DataPath + '/assets/qss/style-{}.qss'.format(skin), "r", encoding="utf-8") as file:
            qss = file.read().replace("$DataPath", self.DataPath) + self.backgroundPanelQss()
        self.app.setStyleSheet(qss)
        if hasattr(self, "frameWidget") and hasattr(self.frameWidget, "setGlobalBackground"):
            self.frameWidget.setGlobalBackground(self.configGet("backgroundImage", ""),
                                                 self.configGet("backgroundOpacity", 35))
            self.updateGlobalBackgroundContainers()
        if hasattr(self, "items"):
            for item in self.items:
                hook = getattr(item.plugin, "onGlobalStyleChanged", None)
                if hook:
                    hook()

    def selectGlobalBackgroundImage(self):
        oldPath = self.configGet("backgroundImage", "") or os.getcwd()
        fileName_choose, filetype = QFileDialog.getOpenFileName(
            self,
            _("Select background image"),
            oldPath,
            _("Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)")
        )
        if not fileName_choose:
            return
        hadBackground = bool(self.configGet("backgroundImage", "") and os.path.exists(self.configGet("backgroundImage", "")))
        self.config["backgroundImage"] = fileName_choose
        if hadBackground and hasattr(self, "frameWidget") and hasattr(self.frameWidget, "setGlobalBackground"):
            self.frameWidget.setGlobalBackground(fileName_choose, self.configGet("backgroundOpacity", 35))
            self.updateGlobalBackgroundContainers()
        else:
            self.applyAppStyle()

    def changeGlobalBackgroundOpacity(self):
        value, ok = QInputDialog.getInt(self, _("Background opacity"),
                                        _("Opacity 0-100"),
                                        int(self.configGet("backgroundOpacity", 35)),
                                        0, 100, 5)
        if not ok:
            return
        self.config["backgroundOpacity"] = value
        if hasattr(self, "frameWidget") and hasattr(self.frameWidget, "setGlobalBackground"):
            self.frameWidget.setGlobalBackground(self.configGet("backgroundImage", ""), value)
            self.updateGlobalBackgroundContainers()

    def clearGlobalBackgroundImage(self):
        self.config["backgroundImage"] = ""
        self.applyAppStyle()

    def showAbout(self):
        help = helpAbout.HelpInfo()
        pluginsHelp = {
            _("About"): help
        }
        for p in self.pluginClasses:
            if not p.help is None:
                pluginsHelp[p.name] = p.help
        iconPath = self.DataPath+"/"+parameters.appIcon
        self.helpWindow = HelpWidget(pluginsHelp, icon = iconPath)
        self.helpWindow.closed.connect(self.helpWindowClosed)
        self.eventFilter.listenWindow(self.helpWindow)

    def helpWindowClosed(self):
        self.eventFilter.unlistenWindow(self.helpWindow)
        self.helpWindow = None
        # self.helpWindow

    def showUpdate(self, versionInfo):
        versionInt = versionInfo.int()
        if self.config["skipVersion"] and self.config["skipVersion"] >= versionInt:
            return
        msgBox = QMessageBox()
        desc = versionInfo.desc if len(versionInfo.desc) < 300 else versionInfo.desc[:300] + " ... "
        link = '<a href="https://github.com/Neutree/COMTool/releases">github.com/Neutree/COMTool/releases</a>'
        info = '{}<br>{}<br><br>v{}: {}<br><br>{}'.format(_("New versioin detected, please click learn more to download"), link, '{}.{}.{}'.format(versionInfo.major, versionInfo.minor, versionInfo.dev), versionInfo.name, desc)
        learn = msgBox.addButton(_("Learn More"), QMessageBox.YesRole)
        skip = msgBox.addButton(_("Skip this version"), QMessageBox.YesRole)
        nextTime = msgBox.addButton(_("Remind me next time"), QMessageBox.NoRole)
        msgBox.setWindowTitle(_("Need update"))
        msgBox.setText(info)
        result = msgBox.exec_()
        if result == 0:
            auto = autoUpdate.AutoUpdate()
            auto.OpenBrowser()
        elif result == 1:
            self.config["skipVersion"] = versionInt



    def autoUpdateDetect(self):
        auto = autoUpdate.AutoUpdate()
        needUpdate, versionInfo = auto.detectNewVersion()
        if needUpdate:
            self.updateSignal.emit(versionInfo)

def load_fonts(paths):
    from PyQt5 import QtGui
    for path in paths:
        id = QtGui.QFontDatabase.addApplicationFont(path)
        fonts = QtGui.QFontDatabase.applicationFontFamilies(id)
        print("load fonts:", fonts)

class Splash(QSplashScreen):
    '''
        show splash when window is loading
    '''
    def __init__(self, app) -> None:
        super().__init__(QPixmap(os.path.join(parameters.assetsDir, "logo.png")))
        self.app = app
        self.exit = False
        self.show()
        t = threading.Thread(target=self._processEventsProcess)
        t.setDaemon(True)
        t.start()

    def event(self, e):
        if type(e) == QCloseEvent:
            self.exit = True
        return super().event(e)

    def finish(self, w):
        self.exit = True
        return super().finish(w)

    def _processEventsProcess(self):
        while not self.exit:
            self.app.processEvents()
            time.sleep(0.001)


def main():
    '''
        @retval None: need restart
                0: exit ok
                others: exit error
    '''
    ret = 1
    try:
        QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        app = QApplication(sys.argv)
        splash = Splash(app)
        eventFilter = EventFilter()
        mainWindow = MainWindow(app, eventFilter, programConfig)
        eventFilter.listenWindow(mainWindow)
        app.installEventFilter(eventFilter)
        g_all_windows.append(mainWindow)
        # path = os.path.join(mainWindow.DataPath, "assets", "fonts", "JosefinSans-Regular.ttf")
        # load_fonts([path])
        log.i("data path:"+mainWindow.DataPath)
        mainWindow.applyAppStyle()
        t = threading.Thread(target=mainWindow.autoUpdateDetect)
        t.setDaemon(True)
        t.start()
        splash.finish(mainWindow)
        ret = app.exec_()
        if mainWindow.needRestart:
            ret = None
        else:
            app.removeEventFilter(eventFilter)
            print("-- no need to restart, now exit")
    except Exception as e:
        import traceback
        exc = traceback.format_exc()
        show_error(_("Error"), exc)
    return ret

def show_error(title, msg):
    print("error:", msg)
    app = QApplication(sys.argv)
    window = QMainWindow()
    QMessageBox.information(window, title, msg)



