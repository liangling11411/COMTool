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
                             QColorDialog, QFontComboBox, QDialog, QScrollBar, QDialogButtonBox)
from PyQt5.QtGui import QIcon,QFont,QTextCursor,QPixmap,QColor, QDrag, QTextOption, QPalette, QKeySequence, QPainter
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

class FontSizeTextEdit(QTextEdit):
    def __init__(self, adjustFontSize, parent=None):
        super().__init__(parent)
        self.adjustFontSize = adjustFontSize

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.adjustFontSize(1 if delta > 0 else -1)
                event.accept()
                return
        super().wheelEvent(event)

class LogSettingsDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.setWindowTitle(_("More log settings"))
        self.setModal(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        self.setLayout(layout)

        self.timedCheck = QCheckBox(_("Timed log"))
        self.timedCheck.setToolTip(_("Stop saving log automatically after the configured duration"))
        self.appendInfoCheck = QCheckBox(_("Append log information at stop"))
        self.appendInfoCheck.setToolTip(_("Append start time, pause history, log size, and connection settings to the end of the log"))
        self.appendInfoItemChecks = {}

        duration = int(plugin.config.get("saveLogDuration", 60))
        hours, minutes, seconds = plugin.splitSeconds(duration)
        self.hoursInput = NoWheelSpinBox()
        self.minutesInput = NoWheelSpinBox()
        self.secondsInput = NoWheelSpinBox()
        for spin, value in [
            (self.hoursInput, hours),
            (self.minutesInput, minutes),
            (self.secondsInput, seconds)
        ]:
            spin.setRange(0, 999999)
            spin.setValue(value)
            spin.setToolTip(_("Only numbers are allowed"))
        self.minutesInput.setRange(0, 59)
        self.secondsInput.setRange(0, 59)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.addWidget(self.timedCheck, 0, 0, 1, 4)
        grid.addWidget(QLabel(_("Hours")), 1, 0)
        grid.addWidget(self.hoursInput, 1, 1)
        grid.addWidget(QLabel(_("Minutes")), 1, 2)
        grid.addWidget(self.minutesInput, 1, 3)
        grid.addWidget(QLabel(_("Seconds")), 2, 0)
        grid.addWidget(self.secondsInput, 2, 1)
        grid.addWidget(self.appendInfoCheck, 3, 0, 1, 4)
        self.appendItemsGroup = QGroupBox(_("Append information items"))
        appendItemsLayout = QGridLayout()
        self.appendItemsGroup.setLayout(appendItemsLayout)
        appendInfoItems = plugin.config.get("saveLogAppendInfoItems", {})
        for idx, (key, label) in enumerate(plugin.logAppendInfoOptions()):
            check = QCheckBox(label)
            check.setChecked(bool(appendInfoItems.get(key, True)))
            appendItemsLayout.addWidget(check, idx // 2, idx % 2)
            self.appendInfoItemChecks[key] = check
        grid.addWidget(self.appendItemsGroup, 4, 0, 1, 4)
        layout.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.timedCheck.setChecked(bool(plugin.config.get("saveLogTimed", False)))
        self.appendInfoCheck.setChecked(bool(plugin.config.get("saveLogAppendInfo", False)))
        self.timedCheck.toggled.connect(self.updateTimedInputs)
        self.appendInfoCheck.toggled.connect(self.updateAppendInputs)
        self.updateTimedInputs()
        self.updateAppendInputs()

    def updateTimedInputs(self):
        enabled = self.timedCheck.isChecked()
        for widget in [self.hoursInput, self.minutesInput, self.secondsInput]:
            widget.setEnabled(enabled)

    def updateAppendInputs(self):
        enabled = self.appendInfoCheck.isChecked()
        self.appendItemsGroup.setEnabled(enabled)

    def accept(self):
        duration = (
            self.hoursInput.value() * 3600 +
            self.minutesInput.value() * 60 +
            self.secondsInput.value()
        )
        if self.timedCheck.isChecked() and duration <= 0:
            QMessageBox.warning(self, _("Error"), _("Timed log duration must be greater than zero"))
            return
        self.plugin.config["saveLogTimed"] = self.timedCheck.isChecked()
        self.plugin.config["saveLogDuration"] = duration
        self.plugin.config["saveLogAppendInfo"] = self.appendInfoCheck.isChecked()
        self.plugin.config["saveLogAppendInfoItems"] = {
            key: check.isChecked()
            for key, check in self.appendInfoItemChecks.items()
        }
        self.plugin.updateLogSettingsSummary()
        super().accept()

class WrapRemarkButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__("", parent)
        self.rawText = ""
        self.setText(text)

    def text(self):
        return self.rawText

    def setText(self, text):
        self.rawText = "" if text is None else str(text)
        self.updateWrappedText()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateWrappedText()

    def updateWrappedText(self):
        metrics = self.fontMetrics()
        iconWidth = self.iconSize().width() if not self.icon().isNull() else 0
        width = max(24, self.width() - iconWidth - 24)
        lines = []
        for paragraph in (self.rawText or "").splitlines() or [""]:
            line = ""
            for ch in paragraph:
                if not line or metrics.horizontalAdvance(line + ch) <= width:
                    line += ch
                else:
                    lines.append(line)
                    line = ch
            lines.append(line)
        QPushButton.setText(self, "\n".join(lines))
        lineCount = max(1, len(lines))
        self.setMinimumHeight(max(parameters.customSendItemHeight, metrics.lineSpacing() * lineCount + 14))

class FindMarkerScrollBar(QScrollBar):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.markers = []

    def setMarkers(self, markers):
        self.markers = markers[:2000]
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.markers or self.orientation() != Qt.Vertical:
            return
        painter = QPainter(self)
        height = max(1, self.height() - 4)
        width = self.width()
        for ratio, color in self.markers:
            qcolor = QColor(color)
            if not qcolor.isValid():
                continue
            painter.setPen(qcolor)
            y = 2 + int(max(0, min(1, ratio)) * height)
            painter.drawLine(1, y, max(1, width - 2), y)
        painter.end()

class ReceiveFindItemWidget(QWidget):
    MIME_TYPE = "application/x-comtool-receive-find-index"

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.setAcceptDrops(True)
        self.setObjectName("receiveFindItem")

    def startDrag(self):
        idx = self.dialog.findItemsLayout.indexOf(self)
        if idx < 0:
            return
        mimeData = QMimeData()
        mimeData.setData(self.MIME_TYPE, str(idx).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.setPixmap(self.grab())
        drag.setHotSpot(self.rect().center())
        drag.exec_(Qt.MoveAction)
        self.dialog.clearDropTarget()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self.MIME_TYPE):
            self.dialog.setDropTarget(self)
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self.MIME_TYPE):
            self.dialog.setDropTarget(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.dialog.clearDropTarget(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(self.MIME_TYPE):
            return
        try:
            fromIdx = int(bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8"))
        except Exception:
            return
        toIdx = self.dialog.findItemsLayout.indexOf(self)
        self.dialog.clearDropTarget(self)
        self.dialog.moveRuleBefore(fromIdx, toIdx)
        event.acceptProposedAction()


class ReceiveFindDragHandle(QPushButton):
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


class ReceiveFindColorButton(QPushButton):
    def __init__(self, dialog, itemWidget, parent=None):
        super().__init__("", parent)
        self.dialog = dialog
        self.itemWidget = itemWidget

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            idx = self.dialog.findItemsLayout.indexOf(self.itemWidget)
            self.dialog.setRuleColor(idx, self.itemWidget, self, "")
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ReceiveFindAdvancedDialog(QDialog):
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.idx = -1
        self.item = None
        self.loading = False
        self.setWindowTitle(_("Advanced find settings"))
        self.resize(520, 320)

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.patternLabel = QLabel("")
        self.patternLabel.setWordWrap(True)
        layout.addWidget(self.patternLabel)

        actionLayout = QHBoxLayout()
        self.findNextButton = QPushButton(_("Find next"))
        self.findNextButton.setToolTip(_("Jump to the next match for this rule"))
        self.countButton = QPushButton(_("Count"))
        self.countButton.setToolTip(_("Count matches for this rule in the receive buffer"))
        self.countLabel = QLabel("")
        actionLayout.addWidget(self.findNextButton)
        actionLayout.addWidget(self.countButton)
        actionLayout.addWidget(self.countLabel, 1)
        layout.addLayout(actionLayout)

        optionGroup = QGroupBox(_("Find options"))
        optionLayout = QGridLayout()
        optionGroup.setLayout(optionLayout)
        self.reverseCheck = QCheckBox(_("Reverse find"))
        self.reverseCheck.setToolTip(_("Search upward when jumping to the next match"))
        self.wholeWordCheck = QCheckBox(_("Whole word"))
        self.wholeWordCheck.setToolTip(_("Match only whole words"))
        self.caseSensitiveCheck = QCheckBox(_("Case sensitive"))
        self.caseSensitiveCheck.setToolTip(_("Match uppercase and lowercase exactly"))
        self.wrapCheck = QCheckBox(_("Wrap around"))
        self.wrapCheck.setToolTip(_("Continue from the other end when no match is found"))
        self.regexCheck = QCheckBox(_("Regular expression"))
        self.regexCheck.setToolTip(_("Treat the find text as a Python regular expression"))
        self.dotAllCheck = QCheckBox(_("Dot matches newline"))
        self.dotAllCheck.setToolTip(_("Let '.' in regular expressions match line breaks"))
        optionLayout.addWidget(self.reverseCheck, 0, 0, 1, 1)
        optionLayout.addWidget(self.wholeWordCheck, 0, 1, 1, 1)
        optionLayout.addWidget(self.caseSensitiveCheck, 1, 0, 1, 1)
        optionLayout.addWidget(self.wrapCheck, 1, 1, 1, 1)
        optionLayout.addWidget(self.regexCheck, 2, 0, 1, 1)
        optionLayout.addWidget(self.dotAllCheck, 2, 1, 1, 1)
        layout.addWidget(optionGroup)

        bottomLayout = QHBoxLayout()
        bottomLayout.addStretch(1)
        self.closeButton = QPushButton(_("Close"))
        bottomLayout.addWidget(self.closeButton)
        layout.addLayout(bottomLayout)

        self.findNextButton.clicked.connect(self.findNext)
        self.countButton.clicked.connect(self.countMatches)
        self.closeButton.clicked.connect(self.close)
        for checkbox in [
            self.reverseCheck,
            self.wholeWordCheck,
            self.caseSensitiveCheck,
            self.wrapCheck,
            self.regexCheck,
            self.dotAllCheck
        ]:
            checkbox.clicked.connect(self.onChanged)
        self.regexCheck.clicked.connect(self.updateRegexOptions)

    def setRule(self, idx, item):
        self.idx = idx
        self.item = item
        self.loading = True
        if idx < 0 or idx >= len(self.dialog.plugin.config["receiveFindRules"]):
            self.patternLabel.setText(_("No find rule selected"))
            for obj in [
                self.findNextButton,
                self.countButton,
                self.reverseCheck,
                self.wholeWordCheck,
                self.caseSensitiveCheck,
                self.wrapCheck,
                self.regexCheck,
                self.dotAllCheck
            ]:
                obj.setEnabled(False)
            self.loading = False
            return
        for obj in [
            self.findNextButton,
            self.countButton,
            self.reverseCheck,
            self.wholeWordCheck,
            self.caseSensitiveCheck,
            self.wrapCheck,
            self.regexCheck
        ]:
            obj.setEnabled(True)
        rule = self.dialog.plugin.normalizeReceiveFindRule(self.dialog.plugin.config["receiveFindRules"][idx])
        self.patternLabel.setText(_("Find text") + ": " + (rule["pattern"] or _("Empty")))
        self.reverseCheck.setChecked(rule["reverse"])
        self.wholeWordCheck.setChecked(rule["wholeWord"])
        self.caseSensitiveCheck.setChecked(rule["caseSensitive"])
        self.wrapCheck.setChecked(rule["wrapFind"])
        self.regexCheck.setChecked(rule["isRegex"])
        self.dotAllCheck.setChecked(rule["dotMatchesNewline"])
        self.countLabel.setText("")
        self.updateRegexOptions()
        self.updateFindNextState()
        self.loading = False

    def currentValues(self):
        return {
            "reverse": self.reverseCheck.isChecked(),
            "wholeWord": self.wholeWordCheck.isChecked(),
            "caseSensitive": self.caseSensitiveCheck.isChecked(),
            "wrapFind": self.wrapCheck.isChecked(),
            "isRegex": self.regexCheck.isChecked(),
            "dotMatchesNewline": self.dotAllCheck.isChecked()
        }

    def updateRegexOptions(self):
        self.dotAllCheck.setEnabled(self.regexCheck.isChecked())

    def updateFindNextState(self):
        validRule = 0 <= self.idx < len(self.dialog.plugin.config.get("receiveFindRules", []))
        self.findNextButton.setEnabled(validRule and self.dialog.plugin.isConnectionClosed())

    def onChanged(self):
        if self.loading:
            return
        self.dialog.updateRuleAdvanced(self.idx, self.item, self.currentValues())

    def findNext(self):
        if not self.dialog.plugin.isConnectionClosed():
            return
        self.dialog.plugin.jumpToNextReceiveFindRule(self.idx)

    def countMatches(self):
        self.onChanged()
        count = self.dialog.plugin.countReceiveFindRuleMatches(self.idx)
        self.countLabel.setText(_("Matches") + ": {}".format(count))

    def closeEvent(self, event):
        super().closeEvent(event)
        QTimer.singleShot(0, self.dialog.plugin.updateReceiveFindMarkers)


class ReceiveFindDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.loading = False
        self.currentColor = "#fff176"
        self.dropTarget = None
        self.advancedDialog = None
        self.setWindowTitle(_("Find in receive area"))
        self.resize(760, 520)

        layout = QVBoxLayout()
        self.setLayout(layout)

        layout.addWidget(QLabel(_("Find rules (top rules have higher priority)")))

        batchLayout = QHBoxLayout()
        self.selectAll = QCheckBox(_("Select all"))
        self.selectAll.setToolTip(_("Select all find rules for batch actions"))
        self.colorButton = QPushButton(_("Highlight color"))
        self.colorButton.setToolTip(_("Choose highlight color for new rules or selected rules"))
        self.updateColorButton()
        self.applyColorButton = QPushButton(_("Apply color"))
        self.clearColorButton = QPushButton(_("Clear color"))
        self.deleteButton = QPushButton(_("Delete selected"))
        self.applyColorButton.setToolTip(_("Apply the current highlight color to all selected rules"))
        self.clearColorButton.setToolTip(_("Remove highlight color from all selected rules"))
        self.deleteButton.setToolTip(_("Delete all selected find rules"))
        batchLayout.addWidget(self.selectAll)
        batchLayout.addWidget(self.colorButton)
        batchLayout.addWidget(self.applyColorButton)
        batchLayout.addWidget(self.clearColorButton)
        batchLayout.addWidget(self.deleteButton)
        batchLayout.addStretch(1)
        layout.addLayout(batchLayout)

        self.findScroll = QScrollArea()
        self.findScroll.setWidgetResizable(True)
        self.findScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.findScroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.findItemsWrapper = QWidget()
        self.findItemsLayout = QVBoxLayout()
        self.findItemsLayout.setContentsMargins(0,0,0,0)
        self.findItemsLayout.setAlignment(Qt.AlignTop)
        self.findItemsWrapper.setLayout(self.findItemsLayout)
        self.findScroll.setWidget(self.findItemsWrapper)
        layout.addWidget(self.findScroll, 1)

        bottomLayout = QHBoxLayout()
        self.addButton = QPushButton("")
        self.addButton.setToolTip(_("Add find rule"))
        utils_ui.setButtonIcon(self.addButton, "fa.plus")
        self.closeButton = QPushButton(_("Close"))
        self.closeButton.setToolTip(_("Close find window"))
        bottomLayout.addWidget(self.addButton)
        bottomLayout.addStretch(1)
        bottomLayout.addWidget(self.closeButton)
        layout.addLayout(bottomLayout)

        self.selectAll.clicked.connect(self.setAllSelection)
        self.colorButton.clicked.connect(self.selectColor)
        self.addButton.clicked.connect(self.addRule)
        self.applyColorButton.clicked.connect(self.applyColorToSelected)
        self.clearColorButton.clicked.connect(self.clearSelectedColor)
        self.deleteButton.clicked.connect(self.deleteSelectedRules)
        self.closeButton.clicked.connect(self.close)
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

    def applyRuleColorButton(self, button, color):
        utils_ui.setButtonIcon(button, "fa.paint-brush")
        qcolor = QColor(color)
        if color and qcolor.isValid():
            textColor = "black" if (0.299 * qcolor.red() + 0.587 * qcolor.green() + 0.114 * qcolor.blue()) > 160 else "white"
            button.setStyleSheet("background-color: {}; border-color: {}; color: {};".format(color, color, textColor))
        else:
            button.setStyleSheet("")

    def selectedIndexes(self):
        indexes = []
        for idx, widget in self.iterRuleWidgets():
            if widget.selectCheckBox.isChecked():
                indexes.append(idx)
        return indexes

    def iterRuleWidgets(self):
        for idx in range(self.findItemsLayout.count()):
            layoutItem = self.findItemsLayout.itemAt(idx)
            widget = layoutItem.widget()
            if widget is not None:
                yield idx, widget

    def refreshRules(self, selectIndexes=None):
        selectIndexes = set(selectIndexes or [])
        if self.advancedDialog is not None and self.advancedDialog.isVisible():
            self.advancedDialog.close()
        self.loading = True
        self.clearRuleWidgets()
        self.plugin.config["receiveFindRules"] = [
            self.plugin.normalizeReceiveFindRule(rule)
            for rule in self.plugin.config.get("receiveFindRules", [])
        ]
        for idx, rule in enumerate(self.plugin.config["receiveFindRules"]):
            widget = self.insertRuleWidget(rule)
            if idx in selectIndexes:
                widget.selectCheckBox.setChecked(True)
        self.loading = False
        self.updateActionState()

    def insertRuleWidget(self, rule):
        rule = self.plugin.normalizeReceiveFindRule(rule)
        item = ReceiveFindItemWidget(self)
        layout = QHBoxLayout()
        layout.setContentsMargins(2,2,2,2)
        item.setLayout(layout)

        select = QCheckBox(_("Select"))
        select.setToolTip(_("Select this rule for batch edit actions"))
        dragHandle = ReceiveFindDragHandle(item)
        dragHandle.setProperty("class", "remark")
        dragHandle.setToolTip(_("Drag before another find rule to change priority"))
        utils_ui.setButtonIcon(dragHandle, "fa.bars")
        enabled = QCheckBox(_("Enable"))
        enabled.setToolTip(_("Enable this rule for highlighting, navigation, and scrollbar markers"))
        enabled.setChecked(rule["enabled"])
        pattern = QLineEdit(rule["pattern"])
        pattern.setPlaceholderText(_("Find text"))
        pattern.setToolTip(_("Plain text searches exact text. Use advanced settings for regular expressions."))
        colorButton = ReceiveFindColorButton(self, item)
        colorButton.setToolTip(_("Set highlight color, right click to clear"))
        self.applyRuleColorButton(colorButton, rule["color"])
        advancedButton = QPushButton("...")
        advancedButton.setToolTip(_("Advanced find settings"))
        deleteButton = QPushButton("")
        deleteButton.setProperty("class", "deleteBtn")
        deleteButton.setToolTip(_("Delete this find rule"))
        utils_ui.setButtonIcon(deleteButton, "fa.close")

        layout.addWidget(select)
        layout.addWidget(dragHandle)
        layout.addWidget(enabled)
        layout.addWidget(pattern, 1)
        layout.addWidget(advancedButton)
        layout.addWidget(colorButton)
        layout.addWidget(deleteButton)

        item.selectCheckBox = select
        item.enabledCheckBox = enabled
        item.patternEdit = pattern
        item.advancedButton = advancedButton
        item.colorButton = colorButton
        item.deleteButton = deleteButton
        item.findRuleData = rule
        self.applyRuleItemStyle(item, rule["color"])
        self.findItemsLayout.addWidget(item)

        select.stateChanged.connect(self.updateActionState)
        enabled.clicked.connect(lambda: self.onRuleWidgetChanged(item))
        pattern.textChanged.connect(lambda: self.onRuleWidgetChanged(item))
        advancedButton.clicked.connect(lambda: self.openAdvancedRule(self.findItemsLayout.indexOf(item), item))
        colorButton.clicked.connect(lambda: self.selectRuleColor(self.findItemsLayout.indexOf(item), item, colorButton))
        deleteButton.clicked.connect(lambda: self.deleteRule(self.findItemsLayout.indexOf(item), item))
        return item

    def clearRuleWidgets(self):
        while self.findItemsLayout.count():
            layoutItem = self.findItemsLayout.takeAt(0)
            widget = layoutItem.widget()
            if widget:
                for obj in widget.findChildren(QPushButton):
                    utils_ui.clearButtonIcon(obj)
                widget.setParent(None)
                widget.deleteLater()

    def onRuleWidgetChanged(self, item):
        if self.loading:
            return
        idx = self.findItemsLayout.indexOf(item)
        if idx < 0 or idx >= len(self.plugin.config["receiveFindRules"]):
            return
        self.plugin.config["receiveFindRules"][idx].update({
            "pattern": item.patternEdit.text(),
            "enabled": item.enabledCheckBox.isChecked()
        })
        item.findRuleData.update(self.plugin.config["receiveFindRules"][idx])
        if self.advancedDialog is not None and self.advancedDialog.isVisible() and self.advancedDialog.item is item:
            self.advancedDialog.setRule(idx, item)
        self.plugin.onReceiveFindRulesChanged()

    def openAdvancedRule(self, idx, item):
        if idx < 0 or idx >= len(self.plugin.config["receiveFindRules"]):
            return
        if self.advancedDialog is None:
            self.advancedDialog = ReceiveFindAdvancedDialog(self, self)
        self.advancedDialog.setRule(idx, item)
        self.advancedDialog.show()
        self.advancedDialog.raise_()
        self.advancedDialog.activateWindow()
        self.plugin.updateReceiveFindMarkers()

    def updateRuleAdvanced(self, idx, item, values):
        if idx < 0 or idx >= len(self.plugin.config["receiveFindRules"]):
            return
        self.plugin.config["receiveFindRules"][idx].update(values)
        if item is not None and hasattr(item, "findRuleData"):
            item.findRuleData.update(values)
        self.plugin.onReceiveFindRulesChanged()

    def updateActionState(self):
        hasSelection = bool(self.selectedIndexes())
        self.applyColorButton.setEnabled(hasSelection)
        self.clearColorButton.setEnabled(hasSelection)
        self.deleteButton.setEnabled(hasSelection)
        widgets = [widget for _idx, widget in self.iterRuleWidgets()]
        checkedWidgets = [widget for widget in widgets if widget.selectCheckBox.isChecked()]
        self.selectAll.blockSignals(True)
        self.selectAll.setChecked(bool(widgets) and len(widgets) == len(checkedWidgets))
        self.selectAll.blockSignals(False)

    def setAllSelection(self):
        checked = self.selectAll.isChecked()
        for _idx, widget in self.iterRuleWidgets():
            widget.selectCheckBox.setChecked(checked)
        self.updateActionState()

    def addRule(self):
        rule = self.plugin.normalizeReceiveFindRule({
            "pattern": "",
            "color": self.currentColor,
            "enabled": True,
            "isRegex": False
        })
        self.plugin.config["receiveFindRules"].append(rule)
        self.refreshRules({len(self.plugin.config["receiveFindRules"]) - 1})
        QTimer.singleShot(0, self.scrollToBottom)
        self.plugin.onReceiveFindRulesChanged()

    def scrollToBottom(self):
        bar = self.findScroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def selectRuleColor(self, idx, item, colorButton):
        if idx < 0 or idx >= len(self.plugin.config["receiveFindRules"]):
            return
        current = self.plugin.config["receiveFindRules"][idx].get("color") or self.currentColor
        color = QColorDialog.getColor(QColor(current), self, _("Select color"))
        if color.isValid():
            self.currentColor = color.name()
            self.updateColorButton()
            self.setRuleColor(idx, item, colorButton, color.name())

    def setRuleColor(self, idx, item, colorButton, color):
        if idx < 0 or idx >= len(self.plugin.config["receiveFindRules"]):
            return
        self.plugin.config["receiveFindRules"][idx]["color"] = color
        if hasattr(item, "findRuleData"):
            item.findRuleData["color"] = color
        self.applyRuleColorButton(colorButton, color)
        self.applyRuleItemStyle(item, color)
        self.plugin.onReceiveFindRulesChanged()

    def applyRuleItemStyle(self, item, color):
        qcolor = QColor(color)
        if color and qcolor.isValid():
            item.setStyleSheet(
                "QWidget#receiveFindItem {"
                "background: rgba(%d, %d, %d, 38);"
                "border: 1px solid %s;"
                "border-radius: 4px;"
                "}"
                % (qcolor.red(), qcolor.green(), qcolor.blue(), color)
            )
        else:
            item.setStyleSheet(
                "QWidget#receiveFindItem {"
                "background: transparent;"
                "border: 1px solid transparent;"
                "border-radius: 4px;"
                "}"
            )

    def applyColorToSelected(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        for idx in indexes:
            if idx < len(self.plugin.config["receiveFindRules"]):
                layoutItem = self.findItemsLayout.itemAt(idx)
                widget = layoutItem.widget()
                if widget:
                    self.setRuleColor(idx, widget, widget.colorButton, self.currentColor)
        self.plugin.onReceiveFindRulesChanged()

    def clearSelectedColor(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        for idx in indexes:
            if idx < len(self.plugin.config["receiveFindRules"]):
                layoutItem = self.findItemsLayout.itemAt(idx)
                widget = layoutItem.widget()
                if widget:
                    self.setRuleColor(idx, widget, widget.colorButton, "")
        self.plugin.onReceiveFindRulesChanged()

    def deleteRule(self, idx, item):
        if idx < 0 or idx >= len(self.plugin.config["receiveFindRules"]):
            return
        self.plugin.config["receiveFindRules"].pop(idx)
        for obj in item.findChildren(QPushButton):
            utils_ui.clearButtonIcon(obj)
        item.setParent(None)
        item.deleteLater()
        self.refreshRules()
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

    def setDropTarget(self, item):
        if self.dropTarget is item:
            return
        self.clearDropTarget()
        self.dropTarget = item
        item.setMinimumHeight(max(item.sizeHint().height() + 16, parameters.customSendItemHeight + 16))
        item.setStyleSheet(
            "QWidget#receiveFindItem {"
            "background: rgba(33, 150, 243, 55);"
            "border: 2px solid #2196f3;"
            "border-radius: 4px;"
            "}"
        )

    def clearDropTarget(self, item=None):
        if item is not None and self.dropTarget is not item:
            return
        target = self.dropTarget
        self.dropTarget = None
        if target is None:
            return
        target.setMinimumHeight(0)
        color = ""
        if hasattr(target, "findRuleData"):
            color = target.findRuleData.get("color", "")
        self.applyRuleItemStyle(target, color)

    def moveRuleBefore(self, fromIdx, toIdx):
        if fromIdx == toIdx:
            return
        if fromIdx < 0 or toIdx < 0:
            return
        if fromIdx >= len(self.plugin.config["receiveFindRules"]) or toIdx >= len(self.plugin.config["receiveFindRules"]):
            return
        scrollValue = self.findScroll.verticalScrollBar().value()
        rules = self.plugin.config["receiveFindRules"]
        rule = rules.pop(fromIdx)
        if fromIdx < toIdx:
            toIdx -= 1
        rules.insert(toIdx, rule)
        self.refreshRules({toIdx})
        self.findScroll.verticalScrollBar().setValue(min(scrollValue, self.findScroll.verticalScrollBar().maximum()))
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
            "saveLogAppendInfo": False,
            "saveLogAppendInfoItems": {},
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
            "receiveFindRules": [],
            "receiveBufferSizeKB": 4096
        }
        for k in default:
            if not k in self.config:
                self.config[k] = default[k]
        self.config["saveLog"] = False
        self.config["saveLogAutoNew"] = False
        self.normalizeLogAppendInfoItems()
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
        self.logSessionActive = False
        self.logPaused = False
        self.logSessionPath = ""
        self.logSessionStartDt = None
        self.logPauseStartTime = None
        self.logPauseStartDt = None
        self.logPausePeriods = []
        self.logConnectionEvents = []
        self.receiveClearRecords = []
        self.logTimedDeadline = None
        self.logTimedRemaining = None
        self.logLastSize = 0
        self.receiveFindDialog = None
        self.receiveFindRuleErrors = set()
        self.receiveFindMarkerTimer = None
        self.currentConnStatus = ConnectionStatus.CLOSED

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

    def normalizeLogAppendInfoItems(self):
        defaults = {key: True for key, _label in self.logAppendInfoOptions()}
        value = self.config.get("saveLogAppendInfoItems", {})
        if isinstance(value, dict):
            normalized = defaults.copy()
            for key in normalized:
                if key in value:
                    normalized[key] = bool(value[key])
        elif isinstance(value, list):
            normalized = {key: key in value for key in defaults}
        else:
            normalized = defaults
        self.config["saveLogAppendInfoItems"] = normalized
        return normalized

    def logAppendInfoEnabled(self, key):
        return bool(self.config.get("saveLogAppendInfoItems", {}).get(key, True))

    def globalConfigValue(self, key, default=None):
        config = self.configGlobal
        if hasattr(config, "get"):
            return config.get(key, default)
        try:
            return config[key]
        except Exception:
            return default

    def ensureMainActionButtons(self):
        if hasattr(self, "clearReceiveButtion") and hasattr(self, "clearSendButtion"):
            return
        self.clearReceiveButtion = QPushButton(_("Clear RX"))
        self.clearReceiveButtion.setToolTip(_("Clear receive area"))
        utils_ui.setButtonIcon(self.clearReceiveButtion, "mdi6.broom")
        self.clearSendButtion = QPushButton(_("Clear TX"))
        self.clearSendButtion.setToolTip(_("Clear TX input"))
        utils_ui.setButtonIcon(self.clearSendButtion, "mdi6.broom")

    def onWidgetMain(self, parent):
        self.mainWidget = QSplitter(Qt.Vertical)
        # widgets receive and send area
        self.receiveArea = FontSizeTextEdit(self.adjustReceiveFontSize)
        self.receiveArea.setObjectName("receiveArea")
        self.receiveArea.setToolTip(_("Received RX/TX log output"))
        self.receiveArea.setReadOnly(True)
        self.receiveArea.setStyleSheet(
            "QTextEdit#receiveArea QScrollBar::handle:vertical { min-height: 48px; }"
            "QTextEdit#receiveArea QScrollBar::handle:horizontal { min-width: 48px; }"
        )
        self.receiveFindScrollBar = FindMarkerScrollBar(Qt.Vertical, self.receiveArea)
        self.receiveArea.setVerticalScrollBar(self.receiveFindScrollBar)
        font = QFont(self.config.get("receiveFontFamily", DEFAULT_TEXT_FONT), self.config["receiveFontSize"])
        self.receiveArea.setFont(font)
        self.sendArea = FontSizeTextEdit(self.adjustSendFontSize)
        self.sendArea.setToolTip(_("Input data to send"))
        self.sendArea.setAcceptRichText(False)
        self.ensureMainActionButtons()
        self.receiveFindButton = QPushButton("")
        self.receiveFindButton.setToolTip(_("Find and highlight receive text"))
        utils_ui.setButtonIcon(self.receiveFindButton, "fa.search")
        self.receiveScrollBottomButton = QPushButton("")
        self.receiveScrollBottomButton.setToolTip(_("Scroll receive area to bottom"))
        utils_ui.setButtonIcon(self.receiveScrollBottomButton, "fa.arrow-down")
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
        buttonLayout.addWidget(self.receiveFindButton)
        buttonLayout.addWidget(self.receiveScrollBottomButton)
        buttonLayout.addWidget(self.clearReceiveButtion)
        buttonLayout.addWidget(self.clearSendButtion)
        buttonLayout.addWidget(self.clearHistoryButton)
        buttonLayout.addWidget(self.sendButton)
        buttonLayout.addStretch(1)
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
        self.receiveScrollBottomButton.clicked.connect(self.scrollReceiveToBottom)
        self.sendButton.clicked.connect(self.onSendData)
        self.clearReceiveButtion.clicked.connect(self.clearReceiveBufferWithConfirm)
        self.clearSendButtion.clicked.connect(self.clearSendInputWithConfirm)
        self.receiveUpdateSignal.connect(self.updateReceivedDataDisplay)
        self.sendHistory.activated.connect(self.onSendHistoryIndexChanged)
        if self.receiveFindMarkerTimer is None:
            self.receiveFindMarkerTimer = QTimer(self)
            self.receiveFindMarkerTimer.setSingleShot(True)
            self.receiveFindMarkerTimer.timeout.connect(self.updateReceiveFindMarkers)

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
        self.logFileBtn.clicked.connect(self.selectLogFile)
        self.logFilePath.editingFinished.connect(self.onLogFilePathChanged)
        self.saveLogStartButton.clicked.connect(self.toggleSaveLogRecording)
        self.saveLogStopButton.clicked.connect(self.confirmStopSaveLog)
        self.logMoreSettingsButton.clicked.connect(self.openLogSettingsDialog)
        self.openFileButton.clicked.connect(self.selectFile)
        self.clearHistoryButton.clicked.connect(self.clearHistoryWithConfirm)
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
        self.clearHistoryButton = QPushButton(_("Clear TX History"))
        self.clearHistoryButton.setToolTip(_("Clear TX send history"))
        self.fileSendGroupBox = QGroupBox(_("Send File"))
        fileSendGridLayout = QGridLayout()
        fileSendGridLayout.addWidget(self.filePathWidget, 0, 0, 1, 1)
        fileSendGridLayout.addWidget(self.openFileButton, 0, 1, 1, 1)
        fileSendGridLayout.addWidget(self.sendFileButton, 1, 0, 1, 2)
        self.fileSendGroupBox.setLayout(fileSendGridLayout)

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
        parentLayout.addWidget(self.fileSendGroupBox)

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
        try:
            paramObj["receiveBufferSizeKB"] = int(paramObj["receiveBufferSizeKB"])
        except Exception:
            paramObj["receiveBufferSizeKB"] = 4096
        self.receiveBufferSizeInput.setValue(paramObj["receiveBufferSizeKB"])
        self.updateDefaultFontColorButton(self.receiveFontColorButton, paramObj["receiveFontColor"])
        self.updateDefaultFontColorButton(self.sendFontColorButton, paramObj["sendFontColor"])
        self.applyReceiveFont()
        self.applySendFont()
        paramObj["receiveFindRules"] = [
            self.normalizeReceiveFindRule(rule)
            for rule in paramObj.get("receiveFindRules", [])
        ]
        self.updateClosedOnlyControls()

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
        if not hasattr(self, "receiveArea"):
            return
        self.receiveArea.moveCursor(QTextCursor.End)
        self.receiveArea.ensureCursorVisible()
        bar = self.receiveArea.verticalScrollBar()
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
        if rule is None or not hasattr(self, "receiveArea"):
            return 0
        return len(self.receiveFindRuleRanges(rule, self.receiveArea.toPlainText()))

    def jumpToNextReceiveFindRule(self, idx):
        rule = self.receiveFindRuleByIndex(idx)
        if rule is None or not hasattr(self, "receiveArea"):
            return
        text = self.receiveArea.toPlainText()
        ranges = self.receiveFindRuleRanges(rule, text)
        if not ranges:
            self.hintSignal.emit("info", _("Find"), _("No match found"))
            return
        cursor = self.receiveArea.textCursor()
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
        self.receiveArea.setTextCursor(cursor)
        self.receiveArea.ensureCursorVisible()

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

    def isConnectionClosed(self):
        return self.currentConnStatus == ConnectionStatus.CLOSED

    def updateClosedOnlyControls(self):
        closed = self.isConnectionClosed()
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
        font = self.receiveArea.currentFont()
        font.setFamily(self.config.get("receiveFontFamily", DEFAULT_TEXT_FONT))
        font.setPointSize(self.config["receiveFontSize"])
        self.receiveArea.setFont(font)
        self.defaultColor = None
        self.defaultBg = None
        self.setTextEditPaletteColor(self.receiveArea, self.config["receiveFontColor"], updateDocument=True)

    def applySendFont(self):
        font = self.sendArea.currentFont()
        font.setFamily(self.config.get("sendFontFamily", DEFAULT_TEXT_FONT))
        font.setPointSize(self.config["sendFontSize"])
        self.sendArea.setFont(font)
        self.setTextEditPaletteColor(self.sendArea, self.config["sendFontColor"], updateDocument=True)

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

    def adjustReceiveFontSize(self, delta):
        if not self.isConnectionClosed():
            return
        size = max(1, min(100, int(self.config.get("receiveFontSize", 10)) + delta))
        if hasattr(self, "receiveFontSizeInput"):
            self.receiveFontSizeInput.setValue(size)
        else:
            self.config["receiveFontSize"] = size
            self.applyReceiveFont()
            self.rerenderReceiveArea()

    def adjustSendFontSize(self, delta):
        if not self.isConnectionClosed():
            return
        size = max(1, min(100, int(self.config.get("sendFontSize", 10)) + delta))
        if hasattr(self, "sendFontSizeInput"):
            self.sendFontSizeInput.setValue(size)
        else:
            self.config["sendFontSize"] = size
            self.config["fontSize"] = size
            self.applySendFont()

    def onSendSettingsHexClicked(self):
        if not self.config.get("sendAscii", True):
            self.sendSettingsHex.setChecked(True)
            return
        self.config["sendAscii"] = False
        data = self.sendArea.toPlainText().replace("\n","\r\n")
        data = utils.bytes_to_hex_str(data.encode())
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

    def confirmClearAction(self, message):
        return QMessageBox.question(self.mainWidget, _("Confirm clear"), message,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def clearReceiveBufferWithConfirm(self):
        if self.confirmClearAction(_("Clear receive area?")):
            self.clearReceiveBuffer()

    def clearSendInputWithConfirm(self):
        if self.confirmClearAction(_("Clear send input?")):
            self.sendArea.clear()

    def clearHistoryWithConfirm(self):
        if self.confirmClearAction(_("Clear TX history?")):
            self.clearHistory()

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
        self.toggleSaveLogRecording()

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
        if self.config.get("saveLogAppendInfo", False):
            self.appendLogInformation(endDt)
        self.config["saveLog"] = False
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
        return "", "", {}

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
            lines = [
                "",
                "",
                "========== {} ==========".format(_("Log information")),
            ]
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

    def onLog(self, text):
        path = self.currentLogPath()
        if self.logSessionActive and (not self.logPaused) and self.config["saveLog"] and path:
            with open(path, "a+", encoding=self.configGlobal["encoding"], newline="\n") as f:
                f.write(text)
            self.updateSaveLogStatus()

    def onConnChanged(self, status:ConnectionStatus, msg:str):
        previousStatus = self.currentConnStatus
        self.recordLogConnectionEvent(previousStatus, status, msg)
        self.currentConnStatus = status
        super().onConnChanged(status, msg)
        self.updateClosedOnlyControls()
        dialog = getattr(self, "receiveFindDialog", None)
        advanced = getattr(dialog, "advancedDialog", None) if dialog is not None else None
        if advanced is not None:
            advanced.updateFindNextState()
        self.updateReceiveFindMarkers()
        if status == ConnectionStatus.CONNECTED and self.logSessionActive:
            self.logSessionPath = self.configuredLogPath()
            self.ensureLogFileReady(self.logSessionPath)
            self.updateSaveLogStatus()

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

    def receiveRecordText(self, record):
        parts = [record.get("head", "")]
        encoding = self.globalConfigValue("encoding", "utf-8")
        for data in record.get("datas", []):
            if isinstance(data, str):
                parts.append(data)
            elif isinstance(data, bytes):
                parts.append(data.decode(encoding=encoding, errors="ignore"))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, (list, tuple)) and len(item) >= 3:
                        value = item[2]
                    else:
                        value = item
                    if isinstance(value, bytes):
                        parts.append(value.decode(encoding=encoding, errors="ignore"))
                    else:
                        parts.append(str(value))
            else:
                parts.append(str(data))
        return "".join(parts)

    def receiveRecordSize(self, record):
        encoding = self.globalConfigValue("encoding", "utf-8")
        return len(self.receiveRecordText(record).encode(encoding, errors="ignore"))

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
            if total >= limit:
                break
        kept.reverse()
        if len(kept) == len(records):
            return False
        self.receiveDisplayRecords = kept
        return True

    def scheduleReceiveFindMarkersUpdate(self):
        if self.receiveFindMarkerTimer is not None:
            self.receiveFindMarkerTimer.start(200)

    def shouldShowReceiveFindMarkers(self):
        if not self.isConnectionClosed():
            return False
        dialog = getattr(self, "receiveFindDialog", None)
        advanced = getattr(dialog, "advancedDialog", None) if dialog is not None else None
        return bool(advanced is not None and advanced.isVisible())

    def updateReceiveFindMarkers(self):
        if not hasattr(self, "receiveFindScrollBar"):
            return
        if not self.shouldShowReceiveFindMarkers():
            self.receiveFindScrollBar.setMarkers([])
            return
        text = self.receiveArea.toPlainText() if hasattr(self, "receiveArea") else ""
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
            self.receiveArea.ensureCursorVisible()
        self.receiveArea.horizontalScrollBar().setValue(curHorizontalValue)
        self.receiveArea.viewport().update()

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
        if self.trimReceiveDisplayRecords():
            self.rerenderReceiveArea()
        else:
            self.scheduleReceiveFindMarkersUpdate()

    def rerenderReceiveArea(self):
        if not hasattr(self, "receiveArea") or self.rerenderingReceiveArea:
            return
        self.rerenderingReceiveArea = True
        try:
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
                self.receiveArea.ensureCursorVisible()
            else:
                scrollBar.setValue(min(oldValue, scrollBar.maximum()))
        finally:
            self.rerenderingReceiveArea = False
            self.scheduleReceiveFindMarkersUpdate()

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
        self.recordReceiveClear()
        self.receiveArea.clear()
        self.receiveDisplayRecords.clear()
        if hasattr(self, "receiveFindScrollBar"):
            self.receiveFindScrollBar.setMarkers([])
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
        if self.logSessionActive:
            self.finishSaveLogRecording()
        self.receiveProgressStop = True
        self.stopSaveLogTimer()
        self.stopSaveLogStatus()

