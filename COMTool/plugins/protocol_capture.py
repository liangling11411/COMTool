import csv
import json
import os
import queue
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from numbers import Number

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QIntValidator
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGridLayout,
                             QGroupBox, QInputDialog, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QDialog, QSplitter, QTableWidget, QTableWidgetItem,
                             QTabWidget, QVBoxLayout, QWidget, QSizePolicy)

try:
    import pyqtgraph as pg
except Exception:
    pg = None

try:
    from i18n import _
    from widgets import PlainTextEdit
except ImportError:
    from COMTool.i18n import _
    from COMTool.widgets import PlainTextEdit


DEFAULT_CAPTURE_SCRIPT = ""


DEFAULT_TABLES = [{"id": "sheet1", "title": "sheet1"}]
DEFAULT_COLUMNS = ["time", "value"]
DEFAULT_PLOTS = [
    {"title": "graph1", "y": ["sheet1.value"]},
]

TIME_FORMATS = [
    ("unix_s", "Unix seconds"),
    ("unix_ms", "Unix milliseconds"),
    ("hms", "HH:mm:ss"),
    ("hms_ms", "HH:mm:ss.SSS"),
    ("elapsed_s", "elapsed seconds"),
    ("elapsed_ms", "elapsed milliseconds"),
]

X_AXIS_FIELDS = ["elapsed_s", "elapsed_ms", "unix_s", "unix_ms"]
TABLE_HIDDEN_FIELDS = {"table", "unix_s", "unix_ms", "elapsed_s", "elapsed_ms"}


def defaultCaptureConfig():
    return {
        "script": DEFAULT_CAPTURE_SCRIPT,
        "enabled": False,
        "tables": [dict(item) for item in DEFAULT_TABLES],
        "columns": list(DEFAULT_COLUMNS),
        "plots": [{"title": item["title"], "y": list(item["y"])} for item in DEFAULT_PLOTS],
        "timeFormat": "hms_ms",
        "xAxis": "elapsed_s",
        "maxRows": 10000,
        "maxPoints": 2000,
        "flushInterval": 200,
        "includeRawLine": False,
        "maxErrors": 3,
    }


class DataCaptureEngine:
    def __init__(self):
        self.codeGlobals = {}
        self.parseMethod = None
        self.tables = DEFAULT_TABLES.copy()
        self.columns = DEFAULT_COLUMNS.copy()
        self.plots = DEFAULT_PLOTS.copy()
        self.lineBuffer = ""
        self.lineCount = 0
        self.startTime = time.time()
        self.errorCount = 0

    def loadScript(self, code, requireParse=True):
        codeGlobals = {}
        exec(code, codeGlobals)
        parseMethod = codeGlobals.get("parse")
        if requireParse and not callable(parseMethod):
            raise ValueError(_("parse(line, ctx) method should be in code"))
        self.codeGlobals = codeGlobals
        self.parseMethod = parseMethod if callable(parseMethod) else None
        self.tables = self.normalizeTables(codeGlobals.get("tables", DEFAULT_TABLES))
        self.columns = self.normalizeColumns(codeGlobals.get("columns", DEFAULT_COLUMNS))
        self.plots = self.normalizePlots(codeGlobals.get("plots", DEFAULT_PLOTS))
        self.lineBuffer = ""
        self.lineCount = 0
        self.startTime = time.time()
        self.errorCount = 0

    def normalizeTables(self, tables):
        if not isinstance(tables, (list, tuple)):
            raise ValueError(_("tables should be a list"))
        result = []
        for item in tables:
            if isinstance(item, str):
                tableId = item
                title = item
            elif isinstance(item, dict):
                tableId = str(item.get("id", "")).strip()
                title = str(item.get("title", tableId)).strip() or tableId
            else:
                continue
            if tableId:
                result.append({"id": tableId, "title": title})
        return result or DEFAULT_TABLES.copy()

    def normalizeColumns(self, columns):
        if not isinstance(columns, (list, tuple)):
            raise ValueError(_("columns should be a list"))
        result = [str(item) for item in columns if str(item)]
        return result or DEFAULT_COLUMNS.copy()

    def normalizePlots(self, plots):
        if not isinstance(plots, (list, tuple)):
            raise ValueError(_("plots should be a list"))
        result = []
        for item in plots:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", _("Plot")))
            yFields = item.get("y", [])
            if isinstance(yFields, str):
                yFields = [yFields]
            yFields = [str(field) for field in yFields if str(field)]
            if yFields:
                result.append({"title": title, "y": yFields})
        return result or DEFAULT_PLOTS.copy()

    def buildCtx(self, now):
        unixS = int(now)
        unixMs = int(now * 1000)
        elapsedS = now - self.startTime
        elapsedMs = int(elapsedS * 1000)
        return {
            "time": now,
            "unix_s": unixS,
            "unix_ms": unixMs,
            "elapsed_s": elapsedS,
            "elapsed_ms": elapsedMs,
            "line": self.lineCount,
            "lineNo": self.lineCount,
        }

    def formatTime(self, now, ctx, timeFormat):
        if timeFormat == "unix_s":
            return ctx["unix_s"]
        if timeFormat == "unix_ms":
            return ctx["unix_ms"]
        if timeFormat == "elapsed_s":
            return round(ctx["elapsed_s"], 3)
        if timeFormat == "elapsed_ms":
            return ctx["elapsed_ms"]
        dt = datetime.fromtimestamp(now)
        if timeFormat == "hms":
            return dt.strftime("%H:%M:%S")
        return dt.strftime("%H:%M:%S.%f")[:-3]

    def parseLine(self, line, timeFormat="hms_ms", includeRawLine=True):
        if not self.parseMethod:
            raise ValueError(_("Capture script is not loaded"))
        self.lineCount += 1
        now = time.time()
        ctx = self.buildCtx(now)
        parsed = self.parseMethod(line, ctx)
        rows = self.normalizeParseResult(parsed)
        result = []
        for row in rows:
            tableId = str(row.get("table", "")).strip()
            if not tableId:
                raise ValueError(_("captured row missing table field"))
            enriched = dict(row)
            enriched["table"] = tableId
            enriched["time"] = self.formatTime(now, ctx, timeFormat)
            enriched["unix_s"] = ctx["unix_s"]
            enriched["unix_ms"] = ctx["unix_ms"]
            enriched["elapsed_s"] = ctx["elapsed_s"]
            enriched["elapsed_ms"] = ctx["elapsed_ms"]
            if includeRawLine:
                enriched.setdefault("raw_line", line)
            result.append(enriched)
        self.errorCount = 0
        return result

    def normalizeParseResult(self, parsed):
        if parsed is None:
            return []
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    raise ValueError(_("parse should return None, dict, or list[dict]"))
            return parsed
        raise ValueError(_("parse should return None, dict, or list[dict]"))

    def feed(self, text, timeFormat="hms_ms", includeRawLine=True):
        if not text:
            return []
        self.lineBuffer += text
        rows = []
        while True:
            end = self.lineBuffer.find("\n")
            if end < 0:
                break
            line = self.lineBuffer[:end].rstrip("\r")
            self.lineBuffer = self.lineBuffer[end + 1:]
            parsedRows = self.parseLine(line, timeFormat=timeFormat, includeRawLine=includeRawLine)
            rows.extend(parsedRows)
        if len(self.lineBuffer) > 1024 * 1024:
            self.lineBuffer = self.lineBuffer[-1024 * 1024:]
        return rows

class CaptureTableManager:
    def __init__(self, tabWidget, hintSignal=None):
        self.tabWidget = tabWidget
        self.hintSignal = hintSignal
        self.tables = {}
        self.columns = {}

    def setup(self, tableConfigs, columns):
        self.clearAll(removeTabs=True)
        for item in tableConfigs:
            self.ensureTable(item["id"], item.get("title", item["id"]), columns)

    def ensureTable(self, tableId, title=None, baseColumns=None):
        if tableId in self.tables:
            return self.tables[tableId]
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        columns = list(baseColumns or DEFAULT_COLUMNS)
        columns = [col for col in columns if col != "table"]
        self.tables[tableId] = table
        self.columns[tableId] = []
        self.tabWidget.addTab(table, title or tableId)
        self.ensureColumns(tableId, columns)
        return table

    def ensureColumns(self, tableId, keys):
        table = self.tables[tableId]
        columns = self.columns[tableId]
        changed = False
        for key in keys:
            key = str(key)
            if key in TABLE_HIDDEN_FIELDS:
                continue
            if key not in columns:
                columns.append(key)
                changed = True
        if changed:
            table.setColumnCount(len(columns))
            table.setHorizontalHeaderLabels(columns)

    def appendRows(self, rows, tableConfigs, baseColumns, maxRows):
        titles = {item["id"]: item.get("title", item["id"]) for item in tableConfigs}
        for row in rows:
            tableId = str(row.get("table", "")).strip()
            if not tableId:
                continue
            table = self.ensureTable(tableId, titles.get(tableId, tableId), baseColumns)
            displayRow = {str(key): value for key, value in row.items() if str(key) not in TABLE_HIDDEN_FIELDS}
            self.ensureColumns(tableId, list(displayRow.keys()))
            rowIdx = table.rowCount()
            table.insertRow(rowIdx)
            columns = self.columns[tableId]
            for colIdx, key in enumerate(columns):
                value = displayRow.get(key, "")
                table.setItem(rowIdx, colIdx, QTableWidgetItem(str(value)))
            while table.rowCount() > maxRows:
                table.removeRow(0)

    def currentTableId(self):
        widget = self.tabWidget.currentWidget()
        for tableId, table in self.tables.items():
            if table is widget:
                return tableId
        return None

    def clearTable(self, tableId):
        table = self.tables.get(tableId)
        if table is not None:
            table.setRowCount(0)

    def clearAll(self, removeTabs=False):
        if removeTabs:
            self.tabWidget.clear()
            self.tables.clear()
            self.columns.clear()
            return
        for table in self.tables.values():
            table.setRowCount(0)

    def exportTable(self, tableId, path, encoding):
        table = self.tables.get(tableId)
        if table is None:
            raise ValueError(_("No data to export"))
        columns = self.columns.get(tableId, [])
        with open(path, "w", newline="", encoding=encoding) as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for rowIdx in range(table.rowCount()):
                writer.writerow([
                    table.item(rowIdx, colIdx).text() if table.item(rowIdx, colIdx) else ""
                    for colIdx in range(len(columns))
                ])

    def exportAll(self, folder, encoding):
        now = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        paths = []
        for tableId in self.tables:
            path = os.path.join(folder, "capture_{}_{}.csv".format(now, tableId))
            self.exportTable(tableId, path, encoding)
            paths.append(path)
        return paths


class CapturePlotManager:
    def __init__(self, tabWidget):
        self.tabWidget = tabWidget
        self.plotItems = {}
        self.curves = {}
        self.data = {}
        self.colors = [
            "#BD4B4B", "#3BB273", "#307473", "#3C6997", "#746D75",
            "#228CDB", "#824C71", "#7768AE", "#DC6BAD", "#607d8b",
            "#F18701", "#912F40", "#414288", "#ED4D6E", "#B56576",
        ]

    def setup(self, plots):
        self.tabWidget.clear()
        self.plotItems = {}
        self.curves = {}
        self.data = {}
        if not pg:
            self.tabWidget.addTab(QLabel(_("pyqtgraph is not installed")), _("Plot"))
            return
        pg.setConfigOptions(antialias=True)
        for plot in plots:
            title = plot.get("title", _("Plot"))
            widget = pg.PlotWidget()
            item = widget.getPlotItem()
            item.addLegend()
            item.showGrid(x=True, y=True, alpha=0.3)
            self.tabWidget.addTab(widget, title)
            self.plotItems[title] = item
            self.curves[title] = {}
            self.data[title] = {}

    def clear(self):
        for title, item in self.plotItems.items():
            item.clear()
            item.addLegend()
            self.curves[title] = {}
            self.data[title] = {}

    def appendRows(self, rows, plots, xAxis, maxPoints):
        if not pg:
            return
        for row in rows:
            tableId = str(row.get("table", "")).strip()
            if not tableId:
                continue
            for plot in plots:
                title = plot.get("title", _("Plot"))
                if title not in self.plotItems:
                    continue
                for ref in plot.get("y", []):
                    if "." not in ref:
                        continue
                    refTable, field = ref.split(".", 1)
                    if refTable != tableId or field not in row or not self.isNumber(row[field]):
                        continue
                    xValue = row.get(xAxis)
                    if not self.isNumber(xValue):
                        continue
                    series = self.data[title].setdefault(ref, {"x": [], "y": []})
                    series["x"].append(float(xValue))
                    series["y"].append(float(row[field]))
                    if len(series["x"]) > maxPoints:
                        series["x"] = series["x"][-maxPoints:]
                        series["y"] = series["y"][-maxPoints:]
        self.updateCurves()

    def updateCurves(self):
        for title, seriesMap in self.data.items():
            item = self.plotItems[title]
            curves = self.curves[title]
            for idx, (name, values) in enumerate(seriesMap.items()):
                if name not in curves:
                    color = self.colors[idx % len(self.colors)]
                    curves[name] = item.plot(pen=pg.mkPen(color=color, width=2), name=name)
                curves[name].setData(x=values["x"], y=values["y"])

    def isNumber(self, value):
        return isinstance(value, Number) and not isinstance(value, bool)


class CaptureDataStore:
    def __init__(self, encoding="utf-8", rootDir=None):
        self.encoding = encoding
        self.rootDir = rootDir or os.path.join(os.getcwd(), "capture_data")
        self.dbPath = ""
        self.conn = None
        self.lock = threading.RLock()
        self.writeQueue = None
        self.writerThread = None
        self.active = False
        self.columns = {}
        self.baseColumns = list(DEFAULT_COLUMNS)

    def start(self, baseColumns=None):
        self.stop()
        self.baseColumns = [str(item) for item in (baseColumns or DEFAULT_COLUMNS) if str(item) not in TABLE_HIDDEN_FIELDS]
        os.makedirs(self.rootDir, exist_ok=True)
        name = "capture_{}.db".format(datetime.now().strftime("%Y-%m-%d_%H%M%S"))
        self.dbPath = os.path.join(self.rootDir, name)
        self.conn = sqlite3.connect(self.dbPath, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("CREATE TABLE IF NOT EXISTS rows (seq INTEGER PRIMARY KEY AUTOINCREMENT, table_id TEXT NOT NULL, row_json TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS columns (table_id TEXT NOT NULL, col_name TEXT NOT NULL, ord INTEGER NOT NULL, PRIMARY KEY(table_id, col_name))")
        self.conn.commit()
        self.columns = {}
        self.writeQueue = queue.Queue(maxsize=2048)
        self.active = True
        self.writerThread = threading.Thread(target=self.writerLoop)
        self.writerThread.daemon = True
        self.writerThread.start()

    def stop(self):
        if self.writeQueue is not None:
            try:
                self.writeQueue.put(None, timeout=1)
            except Exception:
                pass
        if self.writerThread is not None and self.writerThread.is_alive():
            self.writerThread.join(timeout=5)
        self.writeQueue = None
        self.writerThread = None
        self.active = False
        with self.lock:
            if self.conn is not None:
                self.conn.commit()
                self.conn.close()
                self.conn = None

    def writerLoop(self):
        while True:
            batch = self.writeQueue.get()
            if batch is None:
                self.writeQueue.task_done()
                break
            self.writeRows(batch)
            self.writeQueue.task_done()

    def enqueueRows(self, rows):
        if not self.active or not rows:
            return
        batch = [dict(row) for row in rows]
        try:
            self.writeQueue.put_nowait(batch)
        except queue.Full:
            self.writeRows(batch)

    def displayRow(self, row):
        return {str(key): value for key, value in row.items() if str(key) not in TABLE_HIDDEN_FIELDS}

    def ensureColumnLocked(self, conn, tableId, key):
        columns = self.columns.setdefault(tableId, [])
        if key in columns:
            return
        columns.append(key)
        conn.execute(
            "INSERT OR IGNORE INTO columns(table_id, col_name, ord) VALUES(?, ?, ?)",
            (tableId, key, len(columns) - 1)
        )

    def writeRows(self, rows):
        with self.lock:
            if self.conn is None:
                return
            payload = []
            for row in rows:
                tableId = str(row.get("table", "")).strip()
                if not tableId:
                    continue
                for key in self.baseColumns:
                    self.ensureColumnLocked(self.conn, tableId, key)
                for key in self.displayRow(row):
                    self.ensureColumnLocked(self.conn, tableId, key)
                payload.append((tableId, json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
            if payload:
                self.conn.executemany("INSERT INTO rows(table_id, row_json) VALUES(?, ?)", payload)
                self.conn.commit()

    def tableIds(self):
        if not self.dbPath or not os.path.exists(self.dbPath):
            return []
        conn = sqlite3.connect(self.dbPath)
        try:
            return [row[0] for row in conn.execute("SELECT DISTINCT table_id FROM rows ORDER BY table_id")]
        finally:
            conn.close()

    def tableColumns(self, conn, tableId):
        rows = list(conn.execute("SELECT col_name FROM columns WHERE table_id=? ORDER BY ord", (tableId,)))
        return [row[0] for row in rows]

    def exportTable(self, tableId, path):
        if not self.dbPath or not os.path.exists(self.dbPath):
            raise ValueError(_("No data to export"))
        conn = sqlite3.connect(self.dbPath)
        try:
            columns = self.tableColumns(conn, tableId)
            if not columns:
                raise ValueError(_("No data to export"))
            with open(path, "w", newline="", encoding=self.encoding) as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                cursor = conn.execute("SELECT row_json FROM rows WHERE table_id=? ORDER BY seq", (tableId,))
                for (rowJson,) in cursor:
                    row = json.loads(rowJson)
                    displayRow = self.displayRow(row)
                    writer.writerow([displayRow.get(key, "") for key in columns])
        finally:
            conn.close()

    def exportAll(self, folder):
        now = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        paths = []
        for tableId in self.tableIds():
            path = os.path.join(folder, "capture_{}_{}.csv".format(now, tableId))
            self.exportTable(tableId, path)
            paths.append(path)
        return paths

    def clear(self):
        with self.lock:
            if self.conn is not None:
                self.conn.execute("DELETE FROM rows")
                self.conn.execute("DELETE FROM columns")
                self.conn.commit()
            elif self.dbPath and os.path.exists(self.dbPath):
                conn = sqlite3.connect(self.dbPath)
                try:
                    conn.execute("DELETE FROM rows")
                    conn.execute("DELETE FROM columns")
                    conn.commit()
                finally:
                    conn.close()
            self.columns = {}


class CaptureViewerDialog(QDialog):
    def __init__(self, title, tableTabs, plotTabs, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title or _("protocol"))
        self.resize(1100, 720)
        layout = QVBoxLayout()
        self.setLayout(layout)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(tableTabs)
        splitter.addWidget(plotTabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)


class DataCaptureWidget(QWidget):
    captureErrorSignal = pyqtSignal(str)
    captureActiveChanged = pyqtSignal(bool)

    def __init__(self, config, hintSignal=None, encoding="utf-8", pageTitle="", parent=None):
        super().__init__(parent)
        default = defaultCaptureConfig()
        for k in default:
            if not k in config:
                config[k] = default[k]
        self.config = config
        self.hintSignal = hintSignal
        self.encoding = encoding
        self.pageTitle = pageTitle or _("protocol")
        self.engine = DataCaptureEngine()
        self.engineLock = threading.Lock()
        self.pendingRows = deque()
        self.pendingRowsLock = threading.Lock()
        self.enabled = False
        self.captureState = "stopped"
        self.dataStore = CaptureDataStore(encoding=encoding)
        self.flushTimer = QTimer(self)
        self.flushTimer.timeout.connect(self.flushRows)
        self.setupUi()
        self.captureErrorSignal.connect(self.onCaptureError)
        self.flushTimer.start(self.safeInt(self.config.get("flushInterval"), 200, 50))
        self.applyScriptConfig(loadOnly=True)

    def setupUi(self):
        rootLayout = QVBoxLayout()
        rootLayout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(rootLayout)
        group = QGroupBox(_("Multi-channel Data Capture"))
        rootLayout.addWidget(group)
        layout = QGridLayout()
        group.setLayout(layout)

        self.scriptEdit = PlainTextEdit()
        font = QFont('Menlo,Consolas,Bitstream Vera Sans Mono,Courier New,monospace, Microsoft YaHei', 10)
        self.scriptEdit.setFont(font)
        self.scriptEdit.setMinimumHeight(100)
        self.scriptEdit.insertPlainText(self.config["script"])

        self.enableBtn = QPushButton(_("Enable Capture"))
        self.stopCaptureBtn = QPushButton(_("Stop Capture"))
        self.saveScriptBtn = QPushButton(_("Apply Script"))
        self.testScriptBtn = QPushButton(_("Test Script"))
        self.viewChartsBtn = QPushButton(_("View Charts"))
        self.clearTablesBtn = QPushButton(_("Clear Tables"))
        self.clearPlotsBtn = QPushButton(_("Clear Plots"))
        self.exportCurrentBtn = QPushButton(_("Export Current Table CSV"))
        self.exportAllBtn = QPushButton(_("Export All Tables CSV"))

        self.timeFormatCombo = QComboBox()
        for key, label in TIME_FORMATS:
            self.timeFormatCombo.addItem(_(label), key)
        self.xAxisCombo = QComboBox()
        for field in X_AXIS_FIELDS:
            self.xAxisCombo.addItem(field)
        self.maxRowsInput = QLineEdit(str(self.config["maxRows"]))
        self.maxPointsInput = QLineEdit(str(self.config["maxPoints"]))
        self.flushIntervalInput = QLineEdit(str(self.config["flushInterval"]))
        for edit in [self.maxRowsInput, self.maxPointsInput, self.flushIntervalInput]:
            edit.setValidator(QIntValidator(1, 1000000))
        self.statusLabel = QLabel(_("Disabled"))

        controlLayout = QVBoxLayout()
        controlLayout.setContentsMargins(0, 0, 0, 0)
        controlLayout.setSpacing(6)
        buttons = [
            self.enableBtn, self.stopCaptureBtn, self.saveScriptBtn, self.testScriptBtn,
            self.viewChartsBtn, self.clearTablesBtn, self.clearPlotsBtn,
            self.exportCurrentBtn, self.exportAllBtn,
        ]
        for button in buttons:
            button.setMinimumHeight(30)
            button.setMinimumWidth(145)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            controlLayout.addWidget(button)
        optionsLayout = QGridLayout()
        optionsLayout.setContentsMargins(0, 6, 0, 0)
        optionsLayout.addWidget(QLabel(_("Time format")), 0, 0)
        optionsLayout.addWidget(self.timeFormatCombo, 0, 1)
        optionsLayout.addWidget(QLabel(_("X axis")), 1, 0)
        optionsLayout.addWidget(self.xAxisCombo, 1, 1)
        optionsLayout.addWidget(QLabel(_("Max rows")), 2, 0)
        optionsLayout.addWidget(self.maxRowsInput, 2, 1)
        optionsLayout.addWidget(QLabel(_("Max points")), 3, 0)
        optionsLayout.addWidget(self.maxPointsInput, 3, 1)
        optionsLayout.addWidget(QLabel(_("Flush ms")), 4, 0)
        optionsLayout.addWidget(self.flushIntervalInput, 4, 1)
        controlLayout.addLayout(optionsLayout)
        controlLayout.addWidget(self.statusLabel)
        controlLayout.addStretch(1)

        self.tableTabs = QTabWidget()
        self.plotTabs = QTabWidget()
        self.tableManager = CaptureTableManager(self.tableTabs, self.hintSignal)
        self.plotManager = CapturePlotManager(self.plotTabs)
        self.viewerDialog = CaptureViewerDialog(self.pageTitle, self.tableTabs, self.plotTabs, self)
        controlWidget = QWidget()
        controlWidget.setLayout(controlLayout)
        controlWidget.setMinimumWidth(170)
        controlWidget.setMaximumWidth(260)
        contentSplitter = QSplitter(Qt.Horizontal)
        contentSplitter.addWidget(self.scriptEdit)
        contentSplitter.addWidget(controlWidget)
        contentSplitter.setStretchFactor(0, 1)
        contentSplitter.setStretchFactor(1, 0)
        layout.addWidget(contentSplitter, 0, 0, 1, 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(0, 1)

        self.enableBtn.clicked.connect(self.toggleCapture)
        self.stopCaptureBtn.clicked.connect(self.stopCapture)
        self.saveScriptBtn.clicked.connect(self.saveScript)
        self.testScriptBtn.clicked.connect(self.testScript)
        self.viewChartsBtn.clicked.connect(self.showCharts)
        self.clearTablesBtn.clicked.connect(self.clearTables)
        self.clearPlotsBtn.clicked.connect(self.clearPlots)
        self.exportCurrentBtn.clicked.connect(self.exportCurrentTable)
        self.exportAllBtn.clicked.connect(self.exportAllTables)
        self.scriptEdit.textChanged.connect(self.onScriptChanged)
        self.timeFormatCombo.currentIndexChanged.connect(self.saveOptions)
        self.xAxisCombo.currentIndexChanged.connect(self.saveOptions)
        self.maxRowsInput.textChanged.connect(self.saveOptions)
        self.maxPointsInput.textChanged.connect(self.saveOptions)
        self.flushIntervalInput.textChanged.connect(self.saveOptions)
        self.setComboValue(self.timeFormatCombo, self.config["timeFormat"])
        self.setComboText(self.xAxisCombo, self.config["xAxis"])
        self.updateEnabledUi()

    def setComboValue(self, combo, value):
        for idx in range(combo.count()):
            if combo.itemData(idx) == value:
                combo.setCurrentIndex(idx)
                return

    def setComboText(self, combo, value):
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def safeInt(self, value, default, minimum=1):
        try:
            value = int(value)
        except Exception:
            return default
        return max(minimum, value)

    def emitHint(self, hintType, title, msg):
        if self.hintSignal:
            self.hintSignal.emit(hintType, title, msg)

    def onScriptChanged(self):
        self.saveScriptBtn.setText(_("Apply Script") + " *")

    def saveOptions(self):
        self.config["timeFormat"] = self.timeFormatCombo.currentData()
        self.config["xAxis"] = self.xAxisCombo.currentText()
        self.config["maxRows"] = self.safeInt(self.maxRowsInput.text(), 10000)
        self.config["maxPoints"] = self.safeInt(self.maxPointsInput.text(), 2000)
        self.config["flushInterval"] = self.safeInt(self.flushIntervalInput.text(), 200, 50)
        if self.flushTimer.interval() != self.config["flushInterval"]:
            self.flushTimer.start(self.config["flushInterval"])

    def showCharts(self):
        self.viewerDialog.setWindowTitle(self.pageTitle)
        self.viewerDialog.show()
        self.viewerDialog.raise_()
        self.viewerDialog.activateWindow()

    def applyScriptConfig(self, loadOnly=False):
        try:
            engine = DataCaptureEngine()
            engine.loadScript(self.scriptEdit.toPlainText(), requireParse=False)
        except Exception as e:
            if not loadOnly:
                self.emitHint("error", _("Error"), _("Run capture script error") + " " + str(e))
            return False
        self.config["tables"] = engine.tables
        self.config["columns"] = engine.columns
        self.config["plots"] = engine.plots
        self.tableManager.setup(engine.tables, engine.columns)
        self.plotManager.setup(engine.plots)
        return True

    def saveScript(self):
        if self.isSessionActive():
            return
        self.saveOptions()
        self.config["script"] = self.scriptEdit.toPlainText()
        if not self.applyScriptConfig():
            return
        self.saveScriptBtn.setText(_("Apply Script"))
        self.emitHint("info", _("Info"), _("Capture script applied"))

    def testScript(self):
        if self.isSessionActive():
            return
        line, ok = QInputDialog.getMultiLineText(
            self,
            _("Test Script"),
            _("Input received line"),
            ""
        )
        if not ok:
            return
        engine = DataCaptureEngine()
        try:
            engine.loadScript(self.scriptEdit.toPlainText())
            rows = []
            for item in line.splitlines():
                rows.extend(engine.parseLine(item, timeFormat=self.config["timeFormat"], includeRawLine=True))
        except Exception as e:
            self.emitHint("error", _("Error"), _("Run capture script error") + " " + str(e))
            return
        if not rows:
            self.emitHint("info", _("Info"), _("No data captured"))
        else:
            self.emitHint("info", _("Info"), _("Captured") + " " + str(rows[:6]))

    def toggleCapture(self):
        if self.captureState == "stopped":
            self.startCapture()
        elif self.captureState == "running":
            self.pauseCapture()
        else:
            self.resumeCapture()

    def setCaptureEnabled(self, enabled):
        if enabled:
            self.startCapture()
        else:
            self.stopCapture()

    def isSessionActive(self):
        return self.captureState != "stopped"

    def startCapture(self):
        self.saveOptions()
        code = self.scriptEdit.toPlainText()
        try:
            with self.engineLock:
                self.engine.loadScript(code, requireParse=True)
                self.enabled = True
        except Exception as e:
            self.enabled = False
            self.captureState = "stopped"
            self.updateEnabledUi()
            self.emitHint("error", _("Error"), _("Run capture script error") + " " + str(e))
            return
        self.config["script"] = code
        self.config["enabled"] = True
        self.config["tables"] = self.engine.tables
        self.config["columns"] = self.engine.columns
        self.config["plots"] = self.engine.plots
        self.tableManager.setup(self.engine.tables, self.engine.columns)
        self.plotManager.setup(self.engine.plots)
        try:
            self.dataStore.start(self.engine.columns)
        except Exception as e:
            with self.engineLock:
                self.enabled = False
                self.captureState = "stopped"
                self.config["enabled"] = False
            self.updateEnabledUi()
            self.emitHint("error", _("Error"), _("Open capture storage failed") + " " + str(e))
            return
        self.captureState = "running"
        self.saveScriptBtn.setText(_("Apply Script"))
        self.captureActiveChanged.emit(True)
        self.updateEnabledUi()

    def pauseCapture(self):
        if self.captureState != "running":
            return
        with self.engineLock:
            self.enabled = False
            self.captureState = "paused"
        self.updateEnabledUi()

    def resumeCapture(self):
        if self.captureState != "paused":
            return
        with self.engineLock:
            self.enabled = True
            self.captureState = "running"
        self.updateEnabledUi()

    def stopCapture(self):
        wasActive = self.isSessionActive()
        with self.engineLock:
            self.enabled = False
            self.captureState = "stopped"
            self.config["enabled"] = False
        self.dataStore.stop()
        if wasActive:
            self.captureActiveChanged.emit(False)
        self.updateEnabledUi()

    def updateEnabledUi(self):
        active = self.isSessionActive()
        running = self.captureState == "running"
        paused = self.captureState == "paused"
        if running:
            self.enableBtn.setText(_("Pause Capture"))
            self.statusLabel.setText(_("Enabled"))
        elif paused:
            self.enableBtn.setText(_("Resume Capture"))
            self.statusLabel.setText(_("Paused"))
        else:
            self.enableBtn.setText(_("Enable Capture"))
            self.statusLabel.setText(_("Disabled"))
        self.stopCaptureBtn.setEnabled(active)
        for obj in [
            self.scriptEdit,
            self.saveScriptBtn,
            self.testScriptBtn,
            self.exportCurrentBtn,
            self.exportAllBtn,
            self.timeFormatCombo,
            self.xAxisCombo,
            self.maxRowsInput,
            self.maxPointsInput
        ]:
            obj.setEnabled(not active)

    def onCaptureError(self, msg):
        self.stopCapture()
        self.updateEnabledUi()
        self.emitHint("error", _("Error"), _("Run capture script error") + " " + msg)

    def onData(self, text):
        if self.captureState != "running":
            return
        try:
            with self.engineLock:
                if self.captureState != "running":
                    return
                rows = self.engine.feed(
                    text,
                    timeFormat=self.config.get("timeFormat", "hms_ms"),
                    includeRawLine=bool(self.config.get("includeRawLine", True))
                )
        except Exception as e:
            with self.engineLock:
                self.engine.errorCount += 1
                tooMany = self.engine.errorCount >= self.safeInt(self.config.get("maxErrors"), 3)
                if tooMany:
                    self.enabled = False
                    self.captureState = "stopped"
                    self.config["enabled"] = False
            if tooMany:
                self.dataStore.stop()
                self.captureActiveChanged.emit(False)
                self.captureErrorSignal.emit(str(e))
            else:
                self.emitHint("warning", _("Warning"), _("Run capture script error") + " " + str(e))
            return
        if not rows:
            return
        self.dataStore.enqueueRows(rows)
        with self.pendingRowsLock:
            self.pendingRows.extend(rows)
            maxPending = max(self.config["maxRows"] * 2, 1000)
            while len(self.pendingRows) > maxPending:
                self.pendingRows.popleft()

    def flushRows(self):
        with self.pendingRowsLock:
            if not self.pendingRows:
                return
            rows = list(self.pendingRows)
            self.pendingRows.clear()
        self.appendRows(rows)

    def appendRows(self, rows):
        if not rows:
            return
        self.tableManager.appendRows(rows, self.config["tables"], self.config["columns"], self.config["maxRows"])
        self.plotManager.appendRows(rows, self.config["plots"], self.config["xAxis"], self.config["maxPoints"])
        self.statusLabel.setText("{}: {}".format(_("Rows"), len(rows)))

    def clearTables(self):
        if QMessageBox.question(self, _("Confirm clear"), _("Clear tables?"),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        with self.pendingRowsLock:
            self.pendingRows.clear()
        self.tableManager.clearAll()
        self.dataStore.clear()

    def clearPlots(self):
        if QMessageBox.question(self, _("Confirm clear"), _("Clear plots?"),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.plotManager.clear()

    def exportCurrentTable(self):
        if self.isSessionActive():
            return
        tableId = self.tableManager.currentTableId()
        if not tableId:
            self.emitHint("warning", _("Warning"), _("No data to export"))
            return
        defaultName = "capture_{}_{}.csv".format(datetime.now().strftime("%Y-%m-%d_%H%M%S"), tableId)
        path, _filetype = QFileDialog.getSaveFileName(self, _("Export CSV"), defaultName, _("CSV file (*.csv);;All Files (*)"))
        if not path:
            return
        try:
            if self.dataStore.dbPath:
                self.dataStore.exportTable(tableId, path)
            else:
                self.tableManager.exportTable(tableId, path, self.encoding)
        except Exception as e:
            self.emitHint("error", _("Error"), _("Export CSV failed") + " " + str(e))
            return
        self.emitHint("info", _("Info"), _("Export CSV success"))

    def exportAllTables(self):
        if self.isSessionActive():
            return
        folder = QFileDialog.getExistingDirectory(self, _("Export All Tables CSV"), os.getcwd())
        if not folder:
            return
        try:
            if self.dataStore.dbPath:
                paths = self.dataStore.exportAll(folder)
            else:
                paths = self.tableManager.exportAll(folder, self.encoding)
        except Exception as e:
            self.emitHint("error", _("Error"), _("Export CSV failed") + " " + str(e))
            return
        self.emitHint("info", _("Info"), _("Export CSV success") + " ({})".format(len(paths)))
