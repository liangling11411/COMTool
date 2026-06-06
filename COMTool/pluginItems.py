from PyQt5.QtCore import pyqtSignal, Qt, QRect, QMargins
from PyQt5.QtWidgets import (QApplication, QWidget,QPushButton,QMessageBox,QDesktopWidget,QMainWindow,
                             QVBoxLayout,QHBoxLayout,QGridLayout,QTextEdit,QLabel,QRadioButton,QCheckBox,
                             QLineEdit,QGroupBox,QSplitter,QFileDialog, QScrollArea, QTabWidget, QMenu, QSplashScreen)
from PyQt5.QtGui import QIcon,QFont,QTextCursor,QPixmap,QColor, QCloseEvent
import threading
import time
import os
import json

try:
    from i18n import _
    from Combobox import ComboBox
    from conn import ConnectionStatus, conns
    from parameters import log, configFilePath
except ImportError:
    from COMTool.Combobox import ComboBox
    from COMTool.conn import ConnectionStatus, conns
    from COMTool.i18n import _
    from COMTool.parameters import log, configFilePath

class PluginItem:
    # display name
    name = ''
    widget = None
    def __init__(self, name, pluginClass,
                    connClasses, connsConfigs,
                    globalConfig, itemConfig,
                    hintSignal, reloadWindowSignal,
                    connCallback, itemNameChanged=None,
                    serialPageCallback=None):
        '''
            item show name, e.g. dbg-1
        '''
        self.reloadWindowSignal = reloadWindowSignal
        self.hintSignal = hintSignal
        self.name = name
        self.itemNameChanged = itemNameChanged
        self.serialPageCallback = serialPageCallback
        self.connClasses = connClasses
        self.connsConfigs = connsConfigs
        self.currConnWidget = None
        self.currConnIdx = 0
        self.sendProcess = None
        self.dataToSend = []
        self.fileToSend = []
        # widgets
        self.settingWidget = None
        self.mainWidget = None
        self.functionalWidget = None
        # init plugin
        self.plugin = pluginClass()
        self.plugin.configGlobal = globalConfig
        self.plugin.send = self.sendData
        self.plugin.ctrlConn = self.ctrlConn
        self.plugin.hintSignal = self.hintSignal
        self.plugin.reloadWindowSignal = self.reloadWindowSignal
        self.plugin.connCallbak = connCallback
        self.plugin.pageName = name
        self.plugin.onInit(config=itemConfig)
        if not "version" in itemConfig:
            raise Exception("{} {}".format(_("version not found in config of plugin:"), self.plugin.id))
        # conn
        self.isAddConn = self.plugin.onIsAddConnWidget()
        if self.isAddConn:
            self.conns, self.connWidgets = self.newConnWidgets()
        # frame
        self.widget = self.newFrame(self.isAddConn)
        self.uiLoadConfigs()
        self.initEvent()
    
    def newConnWidgets(self):
        connsWidgets = []
        conns = []
        for Conn in self.connClasses:
            # conn.onInit()
            conn = Conn()
            conns.append(conn)
            if conn.id in self.connsConfigs:
                connConfig = self.connsConfigs[conn.id]
            else:
                connConfig = {}
                self.connsConfigs[conn.id] = connConfig
            conn.onInit(connConfig)
            if hasattr(conn, "usePortRows") and self.plugin.id == "dbg":
                conn.usePortRows = True
            widget = conn.onWidget()
            if hasattr(conn, "setSerialPageRequestCallback"):
                conn.setSerialPageRequestCallback(lambda port, action, owner=self: owner.onSerialPortPageRequest(port, action))
            conn.onUiInitDone()
            connsWidgets.append(widget)
        return conns, connsWidgets

    def newFrame(self, isAddConn):
        wrapper = QWidget()
        wrapper.setProperty("class", "pageWrapper")
        wrapperLayout = QVBoxLayout()
        wrapperLayout.setContentsMargins(0, 0, 0, 0)
        widget = QSplitter(Qt.Horizontal)
        widget.setProperty("class", "contentWrapper")
        self.contentSplitter = widget
        statusBar = self.plugin.onWidgetStatusBar(wrapper)
        wrapper.setLayout(wrapperLayout)
        wrapperLayout.addWidget(widget)
        if not statusBar is None:
            wrapperLayout.addWidget(statusBar)
        # widgets settings
        self.settingWidget = QWidget()
        self.settingWidget.setProperty("class","settingWidget")
        self.settingWidget.setMinimumWidth(0)
        settingWrapperLayout = QVBoxLayout()
        settingWrapperLayout.setContentsMargins(0, 0, 0, 0)
        self.settingWidget.setLayout(settingWrapperLayout)
        settingsScrollTogether = getattr(self.plugin, "onSettingsWidgetScrollTogether", lambda: False)
        if settingsScrollTogether():
            settingContentWidget = QWidget()
            settingLayout = QVBoxLayout()
            settingContentWidget.setLayout(settingLayout)
            settingScroll = QScrollArea()
            settingScroll.setWidgetResizable(True)
            settingScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            settingScroll.setWidget(settingContentWidget)
            settingWrapperLayout.addWidget(settingScroll)
        else:
            settingLayout = settingWrapperLayout
        #    get connection settings widgets
        if isAddConn:
            connSettingsGroupBox = QGroupBox(_("Connection"))
            layout = QVBoxLayout()
            connSettingsGroupBox.setLayout(layout)
            self.connSelectCommbox = ComboBox()
            for conn in self.conns:
                self.connSelectCommbox.addItem(conn.name)
            layout.addWidget(self.connSelectCommbox)
            layout.setContentsMargins(1, 6, 0, 0)
            self.connsParent = QWidget()
            layout2 = QVBoxLayout()
            layout2.setContentsMargins(0, 0, 0, 0)
            self.connsParent.setLayout(layout2)
            layout.addWidget(self.connsParent)
            settingLayout.addWidget(connSettingsGroupBox)
        #    get settings widgets
        subSettingWidget = self.plugin.onWidgetSettings(widget)
        if not subSettingWidget is None:
            settingsWidgetStretch = getattr(self.plugin, "onSettingsWidgetStretch", lambda: 0)
            settingLayout.addWidget(subSettingWidget, settingsWidgetStretch())
        # widgets main
        self.mainWidget = self.plugin.onWidgetMain(widget)
        # widgets functional
        self.functionalWidget = QWidget()
        self.functionalWidget.setProperty("class", "functionalWidget")
        layout3 = QVBoxLayout()
        self.functionalWidget.setLayout(layout3)
        loadConfigBtn = QPushButton(_("Import page"))
        shareConfigBtn = QPushButton(_("Save page"))
        self.loadConfigBtn = loadConfigBtn
        loadConfigBtn.setToolTip(_("Import this page name, connection settings, and plugin settings from a page file"))
        shareConfigBtn.setToolTip(_("Save this page name, connection settings, and plugin settings to a page file"))
        configButtonsInSettings = getattr(self.plugin, "onConfigButtonsInSettings", lambda: False)
        if configButtonsInSettings():
            settingLayout.addWidget(loadConfigBtn)
            settingLayout.addWidget(shareConfigBtn)
        else:
            layout3.addWidget(loadConfigBtn)
            layout3.addWidget(shareConfigBtn)
        settingLayout.addStretch()
        loadConfigBtn.clicked.connect(lambda : self.selectLoadfile())
        shareConfigBtn.clicked.connect(lambda : self.selectSharefile())
        pluginFuncWidget = self.plugin.onWidgetFunctional(widget)
        if not pluginFuncWidget is None:
            layout3.addWidget(pluginFuncWidget, 1)
        layout3.addStretch()
        # add to frame
        widget.addWidget(self.settingWidget)
        widget.addWidget(self.mainWidget)
        widget.addWidget(self.functionalWidget)
        widget.setStretchFactor(0, 1)
        widget.setStretchFactor(1, 2)
        widget.setStretchFactor(2, 1)
        widget.splitterMoved.connect(self.onContentSplitterMoved)
        defaultFunctionalVisible = getattr(self.plugin, "onFunctionalWidgetDefaultVisible", lambda: False)
        if defaultFunctionalVisible():
            self.functionalWidget.show()
        else:
            self.functionalWidget.hide()
        # UI init done
        self.plugin.onUiInitDone()
        return wrapper

    def onContentSplitterMoved(self, pos, index):
        if index != 1 or not self.settingWidget or not self.settingWidget.isVisible():
            return
        sizes = self.panelSizes()
        if sizes and sizes[0] <= 36:
            self.settingWidget.hide()

    def panelSizes(self):
        if hasattr(self, "contentSplitter") and self.contentSplitter:
            return self.contentSplitter.sizes()
        return []

    def setPanelSizes(self, sizes):
        if hasattr(self, "contentSplitter") and self.contentSplitter and len(sizes) == 3:
            self.contentSplitter.setSizes(sizes)

    def copyPanelStateFrom(self, sourceItem, forceVisible=False):
        if not sourceItem:
            return
        if sourceItem.settingWidget and self.settingWidget:
            self.settingWidget.setVisible(True if forceVisible else sourceItem.settingWidget.isVisible())
        if sourceItem.functionalWidget and self.functionalWidget:
            self.functionalWidget.setVisible(True if forceVisible else sourceItem.functionalWidget.isVisible())
        sizes = sourceItem.panelSizes() if hasattr(sourceItem, "panelSizes") else []
        if sizes:
            if forceVisible:
                if sizes[0] <= 40 or sizes[2] <= 40:
                    sizes = [260, max(360, sizes[1]), 360]
            self.setPanelSizes(sizes)
        elif forceVisible:
            self.setPanelSizes([260, 640, 360])

    def setImportPageEnabled(self, enabled):
        if hasattr(self, "loadConfigBtn"):
            self.loadConfigBtn.setEnabled(enabled)

    def canImportPage(self):
        try:
            return self.plugin.getConnStatus() == ConnectionStatus.CLOSED
        except Exception:
            return True

    # event
    def selectSharefile(self):
        oldPath = os.getcwd()
        fileName_choose, filetype = QFileDialog.getSaveFileName(self.functionalWidget,
                            _("Save page"),
                            os.path.join(oldPath, f"comtool.{self.name}.json"),
                            _("json file (*.json);;config file (*.conf);;All Files (*)"))
        if fileName_choose != "":
            with open(fileName_choose, "w", encoding="utf-8") as f:
                for item in self.plugin.configGlobal["items"]:
                    if item["name"] == self.name:
                        json.dump(item, f, indent=4, ensure_ascii=False)
                        break
            return True
        return False

    def selectLoadfile(self):
        if not self.canImportPage():
            self.hintSignal.emit("warning", _("Warning"), _("Close the current connection before importing this page"))
            return
        oldPath = os.getcwd()
        fileName_choose, filetype = QFileDialog.getOpenFileName(self.functionalWidget,
                                _("Import page"),
                                oldPath,
                                _("json file (*.json);;config file (*.conf);;All Files (*)"))
        if fileName_choose != "":
            with open(fileName_choose, "r", encoding="utf-8") as f:
                config = json.load( f)
                if "pluginsInfo" in config: # global config file
                    self.hintSignal.emit("error", _("Error"), _("Not support load global config file, you can copy config file mannually to " + configFilePath))
                    return
                if config["pluginId"] != self.plugin.id:
                    self.hintSignal.emit("error", _("Error"), _("Config is not for this plugin, config is for plugin:") + " " + config["pluginId"])
                    return
                if config["config"]["plugin"]["version"] != self.plugin.config["version"]:
                    self.hintSignal.emit("warning", _("Warning"), "{} {}, {}: {}, {}: {}".format(
                            _("Config version not same, plugin config version:"), config["config"]["plugin"]["version"],
                            _("now"), self.plugin.config["version"],
                            _("this maybe lead to some problem, if happened, please remove it manually from config file"),
                            configFilePath))
                    return
                self.oldConnConfigs = self.connsConfigs.copy()
                self.oldPluginConfigs = self.plugin.config.copy()
                self.oldName = self.name
                self.connsConfigs.clear()
                self.plugin.config.clear()
                for k, v in config["config"]["conns"].items():
                    self.connsConfigs[k] = v
                for k, v in config["config"]["plugin"].items():
                    self.plugin.config[k] = v
                importedName = config.get("name", self.name)
                if importedName and self.itemNameChanged:
                    self.itemNameChanged(self, importedName)
                def onClose(ok):
                    if not ok:
                        self.connsConfigs.clear()
                        self.connsConfigs.update(self.oldConnConfigs)
                        self.plugin.config.clear()
                        self.plugin.config.update(self.oldPluginConfigs)
                        if self.itemNameChanged:
                            self.itemNameChanged(self, self.oldName)
                self.reloadWindowSignal.emit("", _("Restart to load config?"), onClose)

    def _setConn(self, idx):
        if not self.isAddConn:
            return
        if self.currConnWidget:
            self.currConnWidget.setParent(None)
            self.conns[self.currConnIdx].onReceived = lambda x:None
            self.conns[self.currConnIdx].onConnectionStatus.disconnect(self.onConnStatus)
        self.currConnWidget = self.connWidgets[idx]
        self.connsParent.layout().addWidget(self.currConnWidget)
        self.conns[idx].onReceived = self.onReceived
        self.plugin.isConnected = self.conns[idx].isConnected
        self.plugin.getConnStatus = self.conns[idx].getConnStatus
        self.conns[idx].onConnectionStatus.connect(self.onConnStatus)
        self.connsConfigs["currConn"] = self.conns[idx].id
        self.currConnIdx = idx


    def uiLoadConfigs(self):
        if self.isAddConn:
            loadedIdx = 0
            if "currConn" in self.connsConfigs:
                for idx, conn in enumerate(self.conns):
                    if conn.id == self.connsConfigs["currConn"]:
                        loadedIdx = idx
            self.connSelectCommbox.setCurrentIndex(loadedIdx)
            self._setConn(loadedIdx)

    def initEvent(self):
        if self.isAddConn:
            self.connSelectCommbox.currentIndexChanged.connect(self.onConnChanged)

    def onConnChanged(self, idx):
        self.conns[self.currConnIdx].disconnect()
        self._setConn(idx)
        self.onConnStatus(ConnectionStatus.CLOSED, _("Change connection, auto close old connection"))

    def ctrlConn(self, k, v):
        if self.isAddConn:
            self.conns[self.currConnIdx].ctrl(k, v)

    def onSerialPortPageRequest(self, port, action):
        if self.serialPageCallback is not None:
            self.serialPageCallback(self, port, action)
            return
        if not self.isAddConn:
            return
        conn = self.conns[self.currConnIdx]
        if getattr(conn, "id", "") != "serial":
            return
        if action == "disconnect" and conn.isConnected():
            conn.openCloseSerial()
        elif action == "connect" and not conn.isConnected():
            conn.openCloseSerial()

    def setSerialQuickPortStatuses(self, statuses):
        if not self.isAddConn:
            return
        for conn in self.conns:
            if hasattr(conn, "setQuickPortStatuses"):
                conn.setQuickPortStatuses(statuses)

    def onConnStatus(self, status:ConnectionStatus, msg):
        self.plugin.onConnChanged(status, msg)
        if self.sendProcess is None:
            self.sendProcess = threading.Thread(target=self.sendDataProcess)
            self.sendProcess.setDaemon(True)
            self.sendProcess.start()

    def sendData(self, data_bytes=None, file_path=None, callback=lambda ok, msg, length, path:None):
        if data_bytes:
            self.dataToSend.insert(0, (data_bytes, callback))
        if file_path:
            self.fileToSend.insert(0, (file_path, callback))

    def onReceived(self, data):
        self.plugin.onReceived(data)

    def onKeyPressEvent(self, e):
        self.plugin.onKeyPressEvent(e)

    def onKeyReleaseEvent(self, e):
        self.plugin.onKeyReleaseEvent(e)

    def sendDataProcess(self):
        self.receiveProgressStop = False
        while not self.receiveProgressStop:
            try:
                if not self.conns[self.currConnIdx].isConnected():
                    time.sleep(0.001)
                    continue
                while len(self.dataToSend) > 0:
                    data, callback = self.dataToSend.pop()
                    self.conns[self.currConnIdx].send(data)
                    callback(True, "", len(data), "")
                while len(self.fileToSend) > 0:
                    file_path, callback = self.fileToSend.pop()
                    ok = False
                    length = 0
                    if file_path and os.path.exists(file_path):
                        data = None
                        try:
                            with open(file_path, "rb") as f:
                                data = f.read()
                        except Exception as e:
                            self.hintSignal.emit("error", _("Error"), _("Open file failed!") + "\n%s\n%s" %(file_path, str(e)))
                        if data:
                            self.conns[self.currConnIdx].send(data)
                            length = len(data)
                            ok = True
                    callback(ok, "", length, file_path)
                time.sleep(0.001)
            except Exception as e:
                import traceback
                exc = traceback.format_exc()
                log.e(exc)
                if 'multiple access' in str(e):
                    self.hintSignal.emit("error", _("Error"), "device disconnected or multiple access on port?")
                continue

    def onDel(self):
        self.receiveProgressStop = True
        if self.isAddConn:
            for conn in self.conns:
                conn.onDel()
        self.plugin.onDel()

