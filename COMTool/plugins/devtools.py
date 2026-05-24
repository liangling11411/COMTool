import base64
import codecs
from datetime import datetime
import hashlib
import html
import ast
import json
import os
import re
import time
from urllib.parse import quote, unquote

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTextEdit, QLabel, QLineEdit, QFileDialog, QStackedWidget, QScrollArea,
    QCheckBox, QRadioButton, QButtonGroup, QTreeWidget, QTreeWidgetItem,
    QSpinBox, QFrame, QSizePolicy
)
from PyQt5.QtGui import QColor, QPainter, QImage, QPen, QFont

try:
    from Combobox import ComboBox
    from plugins.base import Plugin_Base
    from i18n import _
    from widgets import statusBar
except ImportError:
    from COMTool.Combobox import ComboBox
    from COMTool.plugins.base import Plugin_Base
    from COMTool.i18n import _
    from COMTool.widgets import statusBar

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.backends import default_backend
except Exception:
    Cipher = None
    AESGCM = None
    ec = None
    HKDF = None
    hashes = None
    serialization = None


class ToolCard(QWidget):
    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        self.description = description
        self.knowledgeAdded = False
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(18, 16, 18, 16)
        self.layout.setSpacing(10)
        self.setLayout(self.layout)
        self.setObjectName("ip33ToolCard")
        self.setStyleSheet("""
            QLabel#ip33Title {
                font-size: 18px;
                font-weight: 600;
                padding: 0 0 8px 0;
            }
            QLabel[class="ip33Label"] {
                min-width: 96px;
            }
            QLabel#ip33Tip {
                padding: 2px 0 6px 0;
            }
            QPushButton#ip33Primary {
                background: #2f75c1;
                color: #ffffff;
                border: 1px solid #1f65af;
                border-radius: 2px;
                min-height: 28px;
                padding: 3px 18px;
            }
            QPushButton#ip33Primary:hover {
                background: #1f65af;
            }
            QPushButton#ip33Secondary {
                min-height: 28px;
                padding: 3px 14px;
            }
        """)

        titleLabel = QLabel(title)
        titleLabel.setObjectName("ip33Title")
        titleLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.layout.addWidget(titleLabel)

    def addLabel(self, text):
        label = QLabel(text)
        label.setProperty("class", "ip33Label")
        return label

    def addTip(self, text):
        tip = QLabel(text)
        tip.setObjectName("ip33Tip")
        tip.setWordWrap(True)
        tip.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.layout.addWidget(tip)
        return tip

    def createTextEdit(self, placeholder=None, readOnly=False, minHeight=120):
        edit = QTextEdit()
        edit.setAcceptRichText(False)
        edit.setPlaceholderText(placeholder or "")
        edit.setReadOnly(readOnly)
        edit.setObjectName("ip33OutputArea" if readOnly else "ip33TextArea")
        edit.setMinimumHeight(minHeight)
        return edit

    def addTextArea(self, labelText, placeholder=None, readOnly=False, minHeight=120):
        self.layout.addWidget(self.addLabel(labelText))
        edit = self.createTextEdit(placeholder, readOnly, minHeight)
        self.layout.addWidget(edit)
        return edit

    def addInputOutput(self, inputPlaceholder=None, outputPlaceholder=None, inputLabel=None, outputLabel=None):
        self.input = self.addTextArea(inputLabel or _("Original text") + ":", inputPlaceholder or _("Input text"), False, 130)
        self.buttonLayout = QHBoxLayout()
        self.layout.addLayout(self.buttonLayout)
        self.output = self.addTextArea(outputLabel or _("Conversion result") + ":", outputPlaceholder or _("Result"), True, 130)
        return self.input, self.output, self.buttonLayout

    def addFormRow(self, labelText, widgets, tip=None):
        row = QHBoxLayout()
        row.addWidget(self.addLabel(labelText))
        if not isinstance(widgets, (list, tuple)):
            widgets = [widgets]
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        self.layout.addLayout(row)
        if tip:
            self.addTip(tip)

    def ensureButtonLayout(self):
        if not hasattr(self, "buttonLayout"):
            self.buttonLayout = QHBoxLayout()
            self.layout.addLayout(self.buttonLayout)

    def addButton(self, text, callback, primary=True):
        self.ensureButtonLayout()
        button = QPushButton(text)
        button.setObjectName("ip33Primary" if primary else "ip33Secondary")
        button.setToolTip(text)
        button.clicked.connect(callback)
        self.buttonLayout.addWidget(button)
        return button

    def finishButtons(self):
        self.ensureButtonLayout()
        self.buttonLayout.addStretch(1)

    def addResultLine(self, labelText):
        row = QHBoxLayout()
        row.addWidget(self.addLabel(labelText))
        line = QLineEdit()
        line.setReadOnly(True)
        line.setObjectName("ip33ResultLine")
        copyButton = QPushButton(_("Copy"))
        copyButton.setObjectName("ip33Secondary")
        copyButton.setToolTip(_("Copy result"))
        copyButton.clicked.connect(lambda: QApplication.clipboard().setText(line.text()))
        row.addWidget(line, 1)
        row.addWidget(copyButton)
        self.layout.addLayout(row)
        return line


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class HsvColorPlane(QWidget):
    def __init__(self, changedCallback=None, parent=None):
        super().__init__(parent)
        self.hue = 0
        self.saturation = 255
        self.value = 255
        self.changedCallback = changedCallback
        self._image = None
        self._imageHue = None
        self._imageSize = None
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setToolTip(_("Drag to choose saturation and value"))

    def setHsv(self, hue, saturation, value):
        hue = self._clamp(int(hue), 0, 359)
        saturation = self._clamp(int(saturation), 0, 255)
        value = self._clamp(int(value), 0, 255)
        if hue != self.hue:
            self._image = None
        self.hue = hue
        self.saturation = saturation
        self.value = value
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self._colorImage())
        x = round(self.saturation * (self.width() - 1) / 255)
        y = round((255 - self.value) * (self.height() - 1) / 255)
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.drawLine(x - 6, y, x + 6, y)
        painter.drawLine(x, y - 6, x, y + 6)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawLine(x - 5, y, x + 5, y)
        painter.drawLine(x, y - 5, x, y + 5)

    def mousePressEvent(self, event):
        self.pick(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.pick(event.pos())

    def pick(self, pos):
        width = max(1, self.width() - 1)
        height = max(1, self.height() - 1)
        x = self._clamp(pos.x(), 0, width)
        y = self._clamp(pos.y(), 0, height)
        saturation = round(x * 255 / width)
        value = round(255 - y * 255 / height)
        self.setHsv(self.hue, saturation, value)
        if self.changedCallback:
            self.changedCallback(self.hue, self.saturation, self.value)

    def _colorImage(self):
        size = (self.width(), self.height())
        if self._image is not None and self._imageHue == self.hue and self._imageSize == size:
            return self._image
        width, height = size
        image = QImage(width, height, QImage.Format_RGB32)
        maxX = max(1, width - 1)
        maxY = max(1, height - 1)
        for y in range(height):
            value = round(255 - y * 255 / maxY)
            for x in range(width):
                saturation = round(x * 255 / maxX)
                image.setPixelColor(x, y, QColor.fromHsv(self.hue, saturation, value))
        self._image = image
        self._imageHue = self.hue
        self._imageSize = size
        return self._image

    @staticmethod
    def _clamp(value, low, high):
        return max(low, min(high, value))


class HueBar(QWidget):
    def __init__(self, changedCallback=None, parent=None):
        super().__init__(parent)
        self.hue = 0
        self.changedCallback = changedCallback
        self._image = None
        self._imageHeight = None
        self.setFixedWidth(24)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setToolTip(_("Drag to choose hue"))

    def setHue(self, hue):
        self.hue = max(0, min(359, int(hue)))
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self._colorImage())
        y = round(self.hue * (self.height() - 1) / 359)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawRect(0, max(0, y - 2), self.width() - 1, 4)
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.drawLine(0, y, self.width() - 1, y)

    def mousePressEvent(self, event):
        self.pick(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.pick(event.pos())

    def pick(self, pos):
        height = max(1, self.height() - 1)
        y = max(0, min(height, pos.y()))
        self.setHue(round(y * 359 / height))
        if self.changedCallback:
            self.changedCallback(self.hue)

    def _colorImage(self):
        height = self.height()
        if self._image is not None and self._imageHeight == height:
            return self._image
        image = QImage(self.width(), height, QImage.Format_RGB32)
        maxY = max(1, height - 1)
        for y in range(height):
            hue = round(y * 359 / maxY)
            color = QColor.fromHsv(hue, 255, 255)
            for x in range(self.width()):
                image.setPixelColor(x, y, color)
        self._image = image
        self._imageHeight = height
        return self._image



class Plugin(Plugin_Base):
    id = "devtools"
    name = _("Programming Tools")

    def onInit(self, config):
        super().onInit(config)
        self.bitCalculatorFrames = []

    def globalConfigValue(self, key, default=None):
        config = self.configGlobal
        if hasattr(config, "get"):
            return config.get(key, default)
        try:
            return config[key]
        except Exception:
            return default

    def onIsAddConnWidget(self):
        return False

    def onWidgetStatusBar(self, parent):
        self.statusBar = statusBar(rxTxCount=False)
        return self.statusBar

    def onSettingsWidgetScrollTogether(self):
        return True

    def onSettingsWidgetStretch(self):
        return 1

    def onSkinChanged(self, skin):
        style = self.bitCalculatorStyleSheet(skin)
        aliveFrames = []
        for frame in self.bitCalculatorFrames:
            try:
                frame.setStyleSheet(style)
                frame.style().unpolish(frame)
                frame.style().polish(frame)
                aliveFrames.append(frame)
            except RuntimeError:
                pass
        self.bitCalculatorFrames = aliveFrames

    def onWidgetSettings(self, parent):
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        panel.setLayout(layout)

        self.toolTree = QTreeWidget()
        self.toolTree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolTree.setHeaderHidden(True)
        self.toolTree.setRootIsDecorated(True)
        self.toolTree.setIndentation(16)
        self.toolTree.setToolTip(_("Select a programming tool"))
        self.toolTree.itemClicked.connect(self.onToolTreeItemClicked)
        self.toolItems = []
        parentFont = QFont()
        parentFont.setBold(True)
        index = 0
        for category, tools in self.toolCategories():
            parentItem = QTreeWidgetItem([category])
            parentItem.setFlags(parentItem.flags() & ~Qt.ItemIsSelectable)
            parentItem.setToolTip(0, category)
            parentItem.setFont(0, parentFont)
            self.toolTree.addTopLevelItem(parentItem)
            for key, title in tools:
                child = QTreeWidgetItem([title])
                child.setData(0, Qt.UserRole, index)
                child.setToolTip(0, _("Open tool") + ": " + title)
                parentItem.addChild(child)
                self.toolItems.append(child)
                index += 1
            parentItem.setExpanded(True)
        layout.addWidget(self.toolTree, 1)
        self.toolSettingsPanel = panel
        return panel

    def onWidgetMain(self, parent):
        self.stack = QStackedWidget()
        for key, _title in self.toolDefinitions():
            self.stack.addWidget(self.wrapTool(self.createTool(key)))
        self.setTool(0)
        return self.stack

    def toolCategories(self):
        return [
            (_("Check"), [
                ("lrc", _("LRC check")),
                ("bcc", _("BCC check")),
                ("crc", _("CRC check")),
            ]),
            (_("Color"), [
                ("rgb", _("Color format convert")),
            ]),
            (_("Bit operations"), [
                ("bit_calculator", _("Bit calculator")),
                ("bitwise", _("Multi-bit operations")),
            ]),
            (_("String processing"), [
                ("case_convert", _("English case convert")),
                ("string_reverse", _("String reverse")),
                ("char_count", _("Character count")),
            ]),
            (_("Encoding"), [
                ("unicode", _("Unicode")),
                ("url", _("URLEncode")),
                ("base64", _("Base64")),
                ("punycode", _("Punycode")),
                ("domain", _("Chinese domain encoding")),
                ("image_base64", _("Image to Base64")),
            ]),
            (_("Time"), [
                ("timestamp", _("Unix timestamp")),
            ]),
            (_("Crypto"), [
                ("md5", _("MD5 encrypt/decrypt")),
                ("aes", _("AES encrypt/decrypt")),
                ("ecc", _("ECC encrypt/decrypt")),
                ("codec", _("Encode/decode collection")),
                ("hash", _("Hash collection")),
            ]),
        ]

    def toolDefinitions(self):
        return [tool for _category, tools in self.toolCategories() for tool in tools]

    def wrapTool(self, widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(widget)
        return scroll

    def setTool(self, index):
        if hasattr(self, "stack"):
            self.stack.setCurrentIndex(index)
        if hasattr(self, "toolTree") and index < len(getattr(self, "toolItems", [])):
            item = self.toolItems[index]
            if self.toolTree.currentItem() != item:
                self.toolTree.setCurrentItem(item)

    def onToolTreeItemClicked(self, item, _column):
        index = item.data(0, Qt.UserRole)
        if index is not None:
            self.setTool(int(index))

    def createTool(self, key):
        creators = {
            "lrc": self.createLrcTool,
            "bcc": self.createBccTool,
            "crc": self.createCrcTool,
            "rgb": self.createRgbTool,
            "bit_calculator": self.createBitCalculatorTool,
            "bitwise": self.createBitwiseTool,
            "case_convert": self.createCaseConvertTool,
            "string_reverse": self.createStringReverseTool,
            "char_count": self.createCharCountTool,
            "ecc": self.createEccTool,
            "unicode": self.createUnicodeTool,
            "url": self.createUrlTool,
            "base64": self.createBase64Tool,
            "punycode": self.createPunycodeTool,
            "timestamp": self.createTimestampTool,
            "image_base64": self.createImageBase64Tool,
            "domain": self.createDomainTool,
            "md5": self.createMd5Tool,
            "aes": self.createAesTool,
            "codec": self.createCodecTool,
            "hash": self.createHashTool,
        }
        return creators[key]()

    def setOutput(self, output, value):
        text = "" if value is None else str(value)
        if hasattr(output, "setPlainText"):
            output.setPlainText(text)
        else:
            output.setText(text)

    def showStatus(self, level, msg):
        if hasattr(self, "statusBar"):
            self.statusBar.setMsg(level, str(msg))
        elif getattr(self, "hintSignal", None):
            self.hintSignal.emit(level, _("Info"), str(msg))

    def showInfo(self, msg):
        self.showStatus("info", msg)

    def showWarning(self, msg):
        self.showStatus("warning", msg)

    def showError(self, err):
        self.showStatus("error", err)

    def copyText(self, text):
        QApplication.clipboard().setText(text)
        self.showInfo(_("Copied"))

    def fail(self, output, err):
        self.showError(err)

    def addInputModeRadios(self, card):
        hexRadio = QRadioButton(_("Hex"))
        textRadio = QRadioButton(_("Text"))
        hexRadio.setChecked(True)
        group = QButtonGroup(card)
        group.addButton(hexRadio)
        group.addButton(textRadio)
        card.addFormRow(
            _("Data format") + ":",
            [hexRadio, textRadio],
            _("Hex mode accepts values like 01 02 AF; text mode uses UTF-8 bytes.")
        )
        return hexRadio, textRadio

    def createByteTool(self, title, description, actionText, handler):
        card = ToolCard(title, description)
        hexRadio, _textRadio = self.addInputModeRadios(card)
        inp = card.addTextArea(_("Data to check") + ":", _("Input hex bytes or text"), False, 120)
        resultFields = {
            "hex": card.addResultLine("Hex:"),
            "dec": card.addResultLine("Dec:"),
            "oct": card.addResultLine("Oct:"),
            "bin": card.addResultLine("Bin:"),
            "appendHex": card.addResultLine(_("Input HEX + check") + ":"),
        }
        card.addButton(actionText, lambda: handler(inp, resultFields, hexRadio.isChecked()))
        card.addButton(_("Clear"), lambda: self.clearByteTool(inp, resultFields), primary=False)
        card.finishButtons()
        return card

    def clearByteTool(self, inp, resultFields):
        inp.clear()
        for field in resultFields.values():
            field.clear()

    def parseBytes(self, text, isHex):
        value = text.strip()
        if not value:
            return b""
        if not isHex:
            return value.encode("utf-8")
        cleaned = re.sub(r"(?i)0x", "", value)
        cleaned = re.sub(r"[\s,;:_-]+", "", cleaned)
        if not cleaned or len(cleaned) % 2 != 0 or re.search(r"[^0-9a-fA-F]", cleaned):
            raise ValueError(_("Format error, should be like 00 01 02 03"))
        return bytes.fromhex(cleaned)

    def bytesInfo(self, data):
        return _("Input bytes") + ": " + data.hex(" ").upper()

    def formatBytes(self, data):
        return data.hex(" ").upper()

    def intToBytes(self, value, byteWidth, lowFirst=False):
        if byteWidth <= 0:
            return b""
        data = value.to_bytes(byteWidth, "big")
        return data[::-1] if lowFirst else data

    def appendCheckHex(self, data, value, byteWidth, lowFirst=False):
        checkBytes = self.intToBytes(value, byteWidth, lowFirst=lowFirst)
        return self.formatBytes(data + checkBytes)

    def createLrcTool(self):
        return self.createByteTool(
            _("LRC check"),
            _("Calculate the longitudinal redundancy check byte. The result is the two's complement of the byte sum, often used by serial text protocols."),
            _("Calculate LRC"),
            self.calcLrc
        )

    def calcLrc(self, inp, resultFields, isHex):
        try:
            data = self.parseBytes(inp.toPlainText(), isHex)
            value = (-sum(data)) & 0xFF
            self.fillByteResult(resultFields, value, 1, data if isHex else None)
        except Exception as e:
            self.fillErrorResult(resultFields, e)

    def createBccTool(self):
        return self.createByteTool(
            _("BCC check"),
            _("Calculate the block check character by XORing every input byte. It is useful for simple serial protocol frame checks."),
            _("Calculate BCC"),
            self.calcBcc
        )

    def calcBcc(self, inp, resultFields, isHex):
        try:
            data = self.parseBytes(inp.toPlainText(), isHex)
            value = 0
            for byte in data:
                value ^= byte
            self.fillByteResult(resultFields, value, 1, data if isHex else None)
        except Exception as e:
            self.fillErrorResult(resultFields, e)

    def fillByteResult(self, resultFields, value, byteWidth, inputData=None, bitWidth=None):
        hexWidth = max(1, (bitWidth + 3) // 4) if bitWidth else byteWidth * 2
        binWidth = bitWidth if bitWidth else byteWidth * 8
        self.setOutput(resultFields["hex"], "0x{:0{}X}".format(value, hexWidth))
        self.setOutput(resultFields["dec"], str(value))
        self.setOutput(resultFields["oct"], "0o{:o}".format(value))
        self.setOutput(resultFields["bin"], "0b{:0{}b}".format(value, binWidth))
        if "appendHex" in resultFields:
            self.setOutput(
                resultFields["appendHex"],
                self.appendCheckHex(inputData, value, byteWidth) if inputData is not None else ""
            )

    def fillErrorResult(self, resultFields, err):
        self.showError(err)
        for field in resultFields.values():
            field.clear()

    def createCrcTool(self):
        card = ToolCard(
            _("CRC check"),
            _("Calculate common cyclic redundancy checks for byte data. Hex input accepts spaces, commas, 0x prefixes, and line breaks.")
        )
        hexRadio, _textRadio = self.addInputModeRadios(card)
        crcBox = ComboBox()
        crcModels = self.crcModels()
        crcBox.addItems([model["name"] for model in crcModels])
        crcBox.setToolTip(_("Choose CRC algorithm"))
        card.addFormRow(_("Algorithm") + ":", crcBox)
        widthInput = QLineEdit()
        polyInput = QLineEdit()
        initInput = QLineEdit()
        xoroutInput = QLineEdit()
        for edit in (widthInput, polyInput, initInput, xoroutInput):
            edit.setObjectName("ip33ResultLine")
            edit.setMaximumWidth(95)
        refinCheck = QCheckBox("REFIN")
        refoutCheck = QCheckBox("REFOUT")
        paramRow1 = QHBoxLayout()
        paramRow1.addWidget(card.addLabel("WIDTH:"))
        paramRow1.addWidget(widthInput)
        paramRow1.addWidget(card.addLabel("POLY:"))
        paramRow1.addWidget(polyInput)
        paramRow1.addWidget(card.addLabel("INIT:"))
        paramRow1.addWidget(initInput)
        paramRow1.addStretch(1)
        paramRow2 = QHBoxLayout()
        paramRow2.addWidget(card.addLabel("XOROUT:"))
        paramRow2.addWidget(xoroutInput)
        paramRow2.addWidget(refinCheck)
        paramRow2.addWidget(refoutCheck)
        paramRow2.addStretch(1)
        card.layout.addLayout(paramRow1)
        card.layout.addLayout(paramRow2)
        crcBox.activated.connect(lambda _idx: self.applyCrcModel(crcBox, widthInput, polyInput, initInput, xoroutInput, refinCheck, refoutCheck))
        self.applyCrcModel(crcBox, widthInput, polyInput, initInput, xoroutInput, refinCheck, refoutCheck)
        inp = card.addTextArea(_("Data to check") + ":", _("Input hex bytes or text"), False, 120)
        resultFields = {
            "hex": card.addResultLine("Hex:"),
            "dec": card.addResultLine("Dec:"),
            "oct": card.addResultLine("Oct:"),
            "bin": card.addResultLine("Bin:"),
            "lowHigh": card.addResultLine(_("Low byte first") + ":"),
            "highLow": card.addResultLine(_("High byte first") + ":"),
            "appendHex": card.addResultLine(_("Input HEX + check") + ":"),
            "appendHexLow": card.addResultLine(_("Input HEX + low byte first") + ":"),
        }
        card.addButton(
            _("Calculate CRC"),
            lambda: self.calcCrc(
                inp, resultFields, hexRadio.isChecked(), widthInput.text(), polyInput.text(),
                initInput.text(), xoroutInput.text(), refinCheck.isChecked(), refoutCheck.isChecked()
            )
        )
        card.addButton(_("Clear"), lambda: self.clearByteTool(inp, resultFields), primary=False)
        card.finishButtons()
        return card

    def crcModels(self):
        return [
            {"name": "CRC-4/ITU", "width": 4, "poly": 0x03, "init": 0x00, "xorout": 0x00, "refin": True, "refout": True},
            {"name": "CRC-5/EPC", "width": 5, "poly": 0x09, "init": 0x09, "xorout": 0x00, "refin": False, "refout": False},
            {"name": "CRC-5/ITU", "width": 5, "poly": 0x15, "init": 0x00, "xorout": 0x00, "refin": True, "refout": True},
            {"name": "CRC-5/USB", "width": 5, "poly": 0x05, "init": 0x1F, "xorout": 0x1F, "refin": True, "refout": True},
            {"name": "CRC-6/ITU", "width": 6, "poly": 0x03, "init": 0x00, "xorout": 0x00, "refin": True, "refout": True},
            {"name": "CRC-7/MMC", "width": 7, "poly": 0x09, "init": 0x00, "xorout": 0x00, "refin": False, "refout": False},
            {"name": "CRC-8", "width": 8, "poly": 0x07, "init": 0x00, "xorout": 0x00, "refin": False, "refout": False},
            {"name": "CRC-8/ITU", "width": 8, "poly": 0x07, "init": 0x00, "xorout": 0x55, "refin": False, "refout": False},
            {"name": "CRC-8/ROHC", "width": 8, "poly": 0x07, "init": 0xFF, "xorout": 0x00, "refin": True, "refout": True},
            {"name": "CRC-8/MAXIM", "width": 8, "poly": 0x31, "init": 0x00, "xorout": 0x00, "refin": True, "refout": True},
            {"name": "CRC-16/IBM", "width": 16, "poly": 0x8005, "init": 0x0000, "xorout": 0x0000, "refin": True, "refout": True},
            {"name": "CRC-16/MAXIM", "width": 16, "poly": 0x8005, "init": 0x0000, "xorout": 0xFFFF, "refin": True, "refout": True},
            {"name": "CRC-16/USB", "width": 16, "poly": 0x8005, "init": 0xFFFF, "xorout": 0xFFFF, "refin": True, "refout": True},
            {"name": "CRC-16/MODBUS", "width": 16, "poly": 0x8005, "init": 0xFFFF, "xorout": 0x0000, "refin": True, "refout": True},
            {"name": "CRC-16/CCITT", "width": 16, "poly": 0x1021, "init": 0x0000, "xorout": 0x0000, "refin": True, "refout": True},
            {"name": "CRC-16/CCITT-FALSE", "width": 16, "poly": 0x1021, "init": 0xFFFF, "xorout": 0x0000, "refin": False, "refout": False},
            {"name": "CRC-16/X25", "width": 16, "poly": 0x1021, "init": 0xFFFF, "xorout": 0xFFFF, "refin": True, "refout": True},
            {"name": "CRC-16/XMODEM", "width": 16, "poly": 0x1021, "init": 0x0000, "xorout": 0x0000, "refin": False, "refout": False},
            {"name": "CRC-16/DNP", "width": 16, "poly": 0x3D65, "init": 0x0000, "xorout": 0xFFFF, "refin": True, "refout": True},
            {"name": "CRC-32", "width": 32, "poly": 0x04C11DB7, "init": 0xFFFFFFFF, "xorout": 0xFFFFFFFF, "refin": True, "refout": True},
            {"name": "CRC-32/MPEG-2", "width": 32, "poly": 0x04C11DB7, "init": 0xFFFFFFFF, "xorout": 0x00000000, "refin": False, "refout": False},
        ]

    def applyCrcModel(self, crcBox, widthInput, polyInput, initInput, xoroutInput, refinCheck, refoutCheck):
        model = self.crcModels()[crcBox.currentIndex()]
        hexWidth = max(1, (model["width"] + 3) // 4)
        widthInput.setText(str(model["width"]))
        polyInput.setText("{:0{}X}".format(model["poly"], hexWidth))
        initInput.setText("{:0{}X}".format(model["init"], hexWidth))
        xoroutInput.setText("{:0{}X}".format(model["xorout"], hexWidth))
        refinCheck.setChecked(model["refin"])
        refoutCheck.setChecked(model["refout"])

    def calcCrc(self, inp, resultFields, isHex, widthText, polyText, initText, xoroutText, refin, refout):
        try:
            data = self.parseBytes(inp.toPlainText(), isHex)
            width = int(widthText.strip())
            poly = int(polyText.strip(), 16)
            init = int(initText.strip(), 16)
            xorout = int(xoroutText.strip(), 16)
            value = self.crcGeneric(data, width, poly, init, xorout, refin, refout)
            self.fillCrcResult(resultFields, value, max(1, (width + 7) // 8), data if isHex else None, width)
        except Exception as e:
            self.fillErrorResult(resultFields, e)

    def fillCrcResult(self, resultFields, value, byteWidth, inputData=None, bitWidth=None):
        self.fillByteResult(resultFields, value, byteWidth, inputData, bitWidth)
        if byteWidth == 1:
            self.setOutput(resultFields["lowHigh"], "")
            self.setOutput(resultFields["highLow"], "")
            self.setOutput(resultFields["appendHexLow"], "")
            return
        highLowBytes = self.intToBytes(value, byteWidth)
        lowHighBytes = self.intToBytes(value, byteWidth, lowFirst=True)
        self.setOutput(resultFields["lowHigh"], self.formatBytes(lowHighBytes))
        self.setOutput(resultFields["highLow"], self.formatBytes(highLowBytes))
        self.setOutput(resultFields["appendHexLow"], self.formatBytes(inputData + lowHighBytes) if inputData is not None else "")

    def reflectBits(self, value, width):
        reflected = 0
        for _idx in range(width):
            reflected = (reflected << 1) | (value & 0x01)
            value >>= 1
        return reflected

    def crcGeneric(self, data, width, poly, init, xorout, refin, refout):
        if width < 1 or width > 32:
            raise ValueError(_("CRC width must be 1-32"))
        mask = (1 << width) - 1
        crc = init & mask
        if refin:
            reflectedPoly = self.reflectBits(poly, width)
            for byte in data:
                for bitIdx in range(8):
                    crc ^= (byte >> bitIdx) & 0x01
                    if crc & 0x01:
                        crc = (crc >> 1) ^ reflectedPoly
                    else:
                        crc >>= 1
                    crc &= mask
            if refout != refin:
                crc = self.reflectBits(crc, width)
            return (crc ^ xorout) & mask

        if width < 8:
            shift = 8 - width
            regMask = 0xFF
            regTopBit = 0x80
            regPoly = (poly << shift) & regMask
            crcReg = (init << shift) & regMask
            for byte in data:
                crcReg ^= byte
                for _idx in range(8):
                    if crcReg & regTopBit:
                        crcReg = ((crcReg << 1) ^ regPoly) & regMask
                    else:
                        crcReg = (crcReg << 1) & regMask
            crc = (crcReg >> shift) & mask
            if refout:
                crc = self.reflectBits(crc, width)
            return (crc ^ xorout) & mask

        topBit = 1 << (width - 1)
        for byte in data:
            crc ^= (byte << (width - 8)) & mask
            for _idx in range(8):
                if crc & topBit:
                    crc = ((crc << 1) ^ poly) & mask
                else:
                    crc = (crc << 1) & mask
        if refout:
            crc = self.reflectBits(crc, width)
        return (crc ^ xorout) & mask

    def createRgbTool(self):
        card = ToolCard(
            _("Color format convert"),
            _("Convert between RGB, HSV, and HTML HEX colors.")
        )
        titleLabel = card.findChild(QLabel, "ip33Title")
        if titleLabel is not None:
            titleLabel.setAlignment(Qt.AlignCenter)

        panel = QFrame()
        panel.setObjectName("colorConvertPanel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel.setStyleSheet("""
            QFrame#colorConvertPanel {
                border: 1px solid #858585;
                border-radius: 6px;
            }
            QSpinBox#colorSpinBox {
                min-height: 24px;
                padding: 1px 4px;
            }
            QLineEdit#colorHtmlInput {
                min-height: 28px;
                padding: 1px 8px;
            }
        """)
        panelLayout = QVBoxLayout()
        panelLayout.setContentsMargins(14, 14, 14, 14)
        panelLayout.setSpacing(14)
        panel.setLayout(panelLayout)

        pickerRow = QHBoxLayout()
        pickerRow.setSpacing(14)
        plane = HsvColorPlane()
        hueBar = HueBar()
        pickerRow.addWidget(plane, 1)
        pickerRow.addWidget(hueBar)
        panelLayout.addLayout(pickerRow, 1)

        controlRow = QHBoxLayout()
        controlRow.setSpacing(18)
        preview = QFrame()
        preview.setObjectName("colorPreview")
        preview.setFixedSize(76, 116)
        preview.setFrameShape(QFrame.StyledPanel)
        preview.setToolTip(_("Selected color preview"))
        controlRow.addWidget(preview)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        hueSpin = self.createColorSpinBox(0, 359, _("Hue value"))
        satSpin = self.createColorSpinBox(0, 255, _("Saturation value"))
        valSpin = self.createColorSpinBox(0, 255, _("Brightness value"))
        redSpin = self.createColorSpinBox(0, 255, _("Red value"))
        greenSpin = self.createColorSpinBox(0, 255, _("Green value"))
        blueSpin = self.createColorSpinBox(0, 255, _("Blue value"))
        htmlInput = QLineEdit()
        htmlInput.setObjectName("colorHtmlInput")
        htmlInput.setToolTip(_("HTML HEX color, for example #FFBB00"))
        htmlInput.setPlaceholderText("#FFBB00")

        form.addWidget(self.addCompactLabel(_("Hue") + ":"), 0, 0)
        form.addWidget(hueSpin, 0, 1)
        form.addWidget(self.addCompactLabel(_("Red") + ":"), 0, 2)
        form.addWidget(redSpin, 0, 3)
        form.addWidget(self.addCompactLabel(_("Sat") + ":"), 1, 0)
        form.addWidget(satSpin, 1, 1)
        form.addWidget(self.addCompactLabel(_("Green") + ":"), 1, 2)
        form.addWidget(greenSpin, 1, 3)
        form.addWidget(self.addCompactLabel(_("Val") + ":"), 2, 0)
        form.addWidget(valSpin, 2, 1)
        form.addWidget(self.addCompactLabel(_("Blue") + ":"), 2, 2)
        form.addWidget(blueSpin, 2, 3)
        form.addWidget(self.addCompactLabel("HTML:"), 3, 0)
        form.addWidget(htmlInput, 3, 1, 1, 3)
        controlRow.addLayout(form)
        controlRow.addStretch(1)
        panelLayout.addLayout(controlRow)

        card.layout.addWidget(panel, 1)

        state = {
            "updating": False,
            "plane": plane,
            "hueBar": hueBar,
            "preview": preview,
            "hue": hueSpin,
            "sat": satSpin,
            "val": valSpin,
            "red": redSpin,
            "green": greenSpin,
            "blue": blueSpin,
            "html": htmlInput,
        }
        plane.changedCallback = lambda hue, sat, val: self.updateColorControlsFromHsv(state, hue, sat, val)
        hueBar.changedCallback = lambda hue: self.updateColorControlsFromHsv(state, hue, satSpin.value(), valSpin.value())
        hueSpin.valueChanged.connect(lambda _value: self.updateColorControlsFromHsv(state, hueSpin.value(), satSpin.value(), valSpin.value()))
        satSpin.valueChanged.connect(lambda _value: self.updateColorControlsFromHsv(state, hueSpin.value(), satSpin.value(), valSpin.value()))
        valSpin.valueChanged.connect(lambda _value: self.updateColorControlsFromHsv(state, hueSpin.value(), satSpin.value(), valSpin.value()))
        redSpin.valueChanged.connect(lambda _value: self.updateColorControlsFromRgb(state))
        greenSpin.valueChanged.connect(lambda _value: self.updateColorControlsFromRgb(state))
        blueSpin.valueChanged.connect(lambda _value: self.updateColorControlsFromRgb(state))
        htmlInput.textEdited.connect(lambda text: self.updateColorControlsFromHtml(state, text, silent=True))
        htmlInput.editingFinished.connect(lambda: self.updateColorControlsFromHtml(state, htmlInput.text(), silent=False))
        self.updateColorControlsFromColor(state, QColor("#FFBB00"))
        return card

    def addCompactLabel(self, text):
        label = QLabel(text)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return label

    def createColorSpinBox(self, minimum, maximum, tooltip):
        spin = NoWheelSpinBox()
        spin.setObjectName("colorSpinBox")
        spin.setRange(minimum, maximum)
        spin.setFixedWidth(66)
        spin.setToolTip(tooltip)
        return spin

    def updateColorControlsFromHsv(self, state, hue, saturation, value):
        if state.get("updating"):
            return
        color = QColor.fromHsv(int(hue), int(saturation), int(value))
        self.updateColorControlsFromColor(state, color)

    def updateColorControlsFromRgb(self, state):
        if state.get("updating"):
            return
        color = QColor(state["red"].value(), state["green"].value(), state["blue"].value())
        self.updateColorControlsFromColor(state, color)

    def updateColorControlsFromHtml(self, state, text, silent=False):
        if state.get("updating"):
            return
        value = text.strip()
        if not value:
            if not silent:
                self.showWarning(_("Input is empty"))
            return
        try:
            r, g, b = self.parseRgb(value)
            self.updateColorControlsFromColor(state, QColor(r, g, b))
        except Exception as e:
            if not silent:
                self.showError(e)

    def updateColorControlsFromColor(self, state, color):
        if not color.isValid():
            self.showError(_("Format error"))
            return
        state["updating"] = True
        hue, saturation, value, _alpha = color.getHsv()
        if hue < 0:
            hue = 0
        state["plane"].setHsv(hue, saturation, value)
        state["hueBar"].setHue(hue)
        state["hue"].setValue(hue)
        state["sat"].setValue(saturation)
        state["val"].setValue(value)
        state["red"].setValue(color.red())
        state["green"].setValue(color.green())
        state["blue"].setValue(color.blue())
        state["html"].setText(color.name().upper())
        self.updateColorPreviewFrame(state["preview"], color)
        state["updating"] = False

    def updateColorPreviewFrame(self, preview, color):
        border = color.darker(150).name()
        preview.setStyleSheet(
            "QFrame#colorPreview { background-color: %s; border: 1px solid %s; }"
            % (color.name(), border)
        )

    def updateRgbPreview(self, previewButton, color):
        if previewButton is None:
            return
        qcolor = QColor(color)
        if not qcolor.isValid():
            previewButton.setStyleSheet("")
            return
        textColor = "black" if (0.299 * qcolor.red() + 0.587 * qcolor.green() + 0.114 * qcolor.blue()) > 160 else "white"
        hoverColor = qcolor.darker(110).name()
        pressedColor = qcolor.darker(135).name()
        previewButton.setStyleSheet(
            "QPushButton { background-color: %s; border-color: %s; color: %s; }"
            "QPushButton:hover { background-color: %s; border-color: %s; }"
            "QPushButton:pressed { background-color: %s; border-color: %s; }"
            % (color, color, textColor, hoverColor, hoverColor, pressedColor, pressedColor)
        )

    def convertRgb(self, inp, resultFields, previewButton=None):
        try:
            r, g, b = self.parseRgb(inp.text())
            decimal = (r << 16) + (g << 8) + b
            hexColor = "#{:02X}{:02X}{:02X}".format(r, g, b)
            self.setOutput(resultFields["hex"], hexColor)
            self.setOutput(resultFields["rgb"], "rgb({}, {}, {})".format(r, g, b))
            self.setOutput(resultFields["tuple"], "{}, {}, {}".format(r, g, b))
            self.setOutput(resultFields["dec"], str(decimal))
            self.setOutput(resultFields["bgr"], "#{:02X}{:02X}{:02X}".format(b, g, r))
            self.updateRgbPreview(previewButton, hexColor)
        except Exception as e:
            for field in resultFields.values():
                field.clear()
            self.showError(e)

    def parseRgb(self, text):
        value = text.strip()
        if not value:
            raise ValueError(_("Input is empty"))
        rgbMatch = re.search(r"rgba?\s*\(([^)]*)\)", value, re.IGNORECASE)
        if rgbMatch:
            parts = re.split(r"\s*,\s*", rgbMatch.group(1))
            return self.normalizeRgb(parts[:3])
        if value.startswith("#"):
            value = value[1:]
        if re.fullmatch(r"[0-9a-fA-F]{3}", value):
            return tuple(int(ch * 2, 16) for ch in value)
        if re.fullmatch(r"[0-9a-fA-F]{6}", value):
            return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
        if re.fullmatch(r"\d+", value):
            number = int(value)
            if 0 <= number <= 0xFFFFFF:
                return (number >> 16) & 0xFF, (number >> 8) & 0xFF, number & 0xFF
        parts = re.split(r"[\s,;]+", value)
        return self.normalizeRgb(parts)

    def normalizeRgb(self, parts):
        if len(parts) != 3:
            raise ValueError(_("Format error"))
        values = []
        for part in parts:
            number = int(str(part).strip())
            if number < 0 or number > 255:
                raise ValueError(_("RGB value must be 0-255"))
            values.append(number)
        return tuple(values)

    def createBitCalculatorTool(self):
        card = ToolCard(
            _("Bit calculator"),
            _("Programmer calculator for integer base conversion, bit toggling, bitwise operations, and shift operations.")
        )
        frame = QFrame()
        frame.setObjectName("bitCalculator")
        frame.setStyleSheet(self.bitCalculatorStyleSheet())
        self.bitCalculatorFrames.append(frame)
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        frame.setLayout(layout)

        exprLabel = QLabel("")
        exprLabel.setObjectName("bitCalcExpr")
        exprLabel.setAlignment(Qt.AlignRight)
        exprLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        display = QLabel("0")
        display.setObjectName("bitCalcDisplay")
        display.setAlignment(Qt.AlignRight)
        display.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(exprLabel)
        layout.addWidget(display)

        state = {
            "base": "DEC",
            "wordBits": 64,
            "entry": "0",
            "expr": "",
            "newEntry": False,
            "value": 0,
            "display": display,
            "exprLabel": exprLabel,
            "baseButtons": {},
            "baseValues": {},
            "digitButtons": {},
            "bitButtons": {},
        }

        baseGrid = QGridLayout()
        baseGrid.setHorizontalSpacing(8)
        baseGrid.setVerticalSpacing(3)
        baseGroup = QButtonGroup(frame)
        baseGroup.setExclusive(True)
        for row, baseName in enumerate(["HEX", "DEC", "OCT", "BIN"]):
            button = QPushButton(baseName)
            button.setObjectName("bitCalcBase")
            button.setFixedWidth(42)
            button.setCheckable(True)
            button.setToolTip(_("Switch input base") + ": " + baseName)
            button.clicked.connect(lambda _checked=False, base=baseName: self.bitCalcSetBase(state, base))
            baseGroup.addButton(button)
            valueLabel = QLabel("0")
            valueLabel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            valueLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
            valueLabel.setWordWrap(True)
            baseGrid.addWidget(button, row, 0)
            baseGrid.addWidget(valueLabel, row, 1)
            state["baseButtons"][baseName] = button
            state["baseValues"][baseName] = valueLabel
        baseGrid.setColumnStretch(0, 0)
        baseGrid.setColumnStretch(1, 1)
        layout.addLayout(baseGrid)

        toolbar = QHBoxLayout()
        keypadButton = QPushButton(_("Keypad"))
        bitsButton = QPushButton(_("Bit grid"))
        for button in (keypadButton, bitsButton):
            button.setCheckable(True)
            button.setObjectName("bitCalcToggle")
        viewGroup = QButtonGroup(frame)
        viewGroup.setExclusive(True)
        viewGroup.addButton(keypadButton)
        viewGroup.addButton(bitsButton)
        keypadButton.setChecked(True)
        wordBox = ComboBox()
        wordBox.addItems(["QWORD", "DWORD", "WORD", "BYTE"])
        wordBox.setToolTip(_("Word size"))
        toolbar.addWidget(keypadButton)
        toolbar.addWidget(bitsButton)
        toolbar.addStretch(1)
        toolbar.addWidget(wordBox)
        layout.addLayout(toolbar)

        opRow = QHBoxLayout()
        bitOpBox = ComboBox()
        bitOpBox.addItems(["AND", "OR", "XOR", "NOT"])
        shiftBox = ComboBox()
        shiftBox.addItems(["<<", ">>"])
        bitApply = QPushButton(_("Apply"))
        shiftApply = QPushButton(_("Apply"))
        for button in (bitApply, shiftApply):
            button.setObjectName("bitCalcAction")
        opRow.addWidget(QLabel(_("Bitwise") + ":"))
        opRow.addWidget(bitOpBox)
        opRow.addWidget(bitApply)
        opRow.addSpacing(12)
        opRow.addWidget(QLabel(_("Shift") + ":"))
        opRow.addWidget(shiftBox)
        opRow.addWidget(shiftApply)
        opRow.addStretch(1)
        layout.addLayout(opRow)

        viewStack = QStackedWidget()
        keypad = self.createBitCalculatorKeypad(state)
        bitGrid = self.createBitGrid(state)
        viewStack.addWidget(keypad)
        viewStack.addWidget(bitGrid)
        keypadButton.clicked.connect(lambda: viewStack.setCurrentIndex(0))
        bitsButton.clicked.connect(lambda: viewStack.setCurrentIndex(1))
        layout.addWidget(viewStack)

        wordBox.activated.connect(lambda _idx: self.bitCalcSetWordBits(state, wordBox.currentText()))
        bitApply.clicked.connect(lambda: self.bitCalcApplyNamedOp(state, bitOpBox.currentText()))
        shiftApply.clicked.connect(lambda: self.bitCalcPressOperator(state, shiftBox.currentText()))

        card.layout.addWidget(frame)
        self.bitCalcRefresh(state)
        return card

    def bitCalculatorStyleSheet(self, skin=None):
        if skin is None:
            skin = self.globalConfigValue("skin", "light")
        dark = skin == "dark"
        colors = {
            "frameBorder": "#565656" if dark else "#858585",
            "expr": "#a8a8a8" if dark else "#777777",
            "buttonBg": "#4a4a4a" if dark else "#ffffff",
            "buttonHover": "#565656" if dark else "#f2f2f2",
            "buttonDisabledBg": "#303030" if dark else "#f5f5f5",
            "buttonText": "#f2f2f2" if dark else "#202020",
            "buttonDisabledText": "#8c8c8c" if dark else "#9a9a9a",
            "buttonBorder": "#656565" if dark else "#c9c9c9",
        }
        return """
            QFrame#bitCalculator {
                border: 1px solid %(frameBorder)s;
                border-radius: 6px;
            }
            QLabel#bitCalcDisplay {
                font-size: 30px;
                font-weight: 600;
                padding: 4px 2px;
            }
            QLabel#bitCalcExpr {
                color: %(expr)s;
                min-height: 20px;
            }
            QPushButton#bitCalcKey {
                background: %(buttonBg)s;
                color: %(buttonText)s;
                border: 1px solid %(buttonBorder)s;
                border-radius: 4px;
                min-width: 58px;
                min-height: 34px;
                font-size: 16px;
            }
            QPushButton#bitCalcKey:hover {
                background: %(buttonHover)s;
            }
            QPushButton#bitCalcKey:pressed {
                background: #2f75c1;
                color: #ffffff;
            }
            QPushButton#bitCalcKey:disabled {
                color: %(buttonDisabledText)s;
                background: %(buttonDisabledBg)s;
            }
            QPushButton#bitCalcBase {
                background: %(buttonBg)s;
                color: %(buttonText)s;
                border: 1px solid %(buttonBorder)s;
                border-radius: 3px;
                min-width: 42px;
                max-width: 42px;
                min-height: 24px;
                padding: 1px 2px;
            }
            QPushButton#bitCalcBase:checked {
                background: #2f75c1;
                color: #ffffff;
                border-color: #2f75c1;
                font-weight: 600;
            }
            QPushButton#bitCalcToggle, QPushButton#bitCalcAction {
                background: %(buttonBg)s;
                color: %(buttonText)s;
                border: 1px solid %(buttonBorder)s;
                border-radius: 4px;
                min-height: 26px;
                padding: 2px 10px;
            }
            QPushButton#bitCalcToggle:hover, QPushButton#bitCalcAction:hover {
                background: %(buttonHover)s;
            }
            QPushButton#bitCalcToggle:checked {
                background: #2f75c1;
                color: #ffffff;
                border-color: #2f75c1;
            }
            QPushButton#bitCalcAction:pressed {
                background: #2f75c1;
                color: #ffffff;
                border-color: #2f75c1;
            }
            QPushButton#bitCell {
                background: %(buttonBg)s;
                color: %(buttonText)s;
                border: 1px solid %(buttonBorder)s;
                border-radius: 3px;
                min-width: 22px;
                max-width: 22px;
                min-height: 24px;
                max-height: 24px;
                font-weight: 600;
            }
            QPushButton#bitCell:checked {
                background: #2f75c1;
                color: white;
            }
        """ % colors

    def createBitCalculatorKeypad(self, state):
        widget = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        widget.setLayout(grid)
        rows = [
            ["A", "<<", ">>", "C", "Back"],
            ["B", "(", ")", "%", "/"],
            ["C", "7", "8", "9", "*"],
            ["D", "4", "5", "6", "-"],
            ["E", "1", "2", "3", "+"],
            ["F", "+/-", "0", ".", "="],
        ]
        for rowIdx, row in enumerate(rows):
            for colIdx, label in enumerate(row):
                button = QPushButton(label)
                button.setObjectName("bitCalcKey")
                digitButton = label in "0123456789ABCDEF" and not (rowIdx == 0 and colIdx == 3)
                if digitButton:
                    state["digitButtons"][label] = button
                    button.clicked.connect(lambda _checked=False, value=label: self.bitCalcAppendDigit(state, value))
                elif label in ["+", "-", "*", "/", "%", "<<", ">>"]:
                    button.clicked.connect(lambda _checked=False, op=label: self.bitCalcPressOperator(state, op))
                elif label in ["(", ")"]:
                    button.clicked.connect(lambda _checked=False, value=label: self.bitCalcPressParen(state, value))
                elif label == "C":
                    button.clicked.connect(lambda: self.bitCalcClear(state))
                elif label == "Back":
                    button.clicked.connect(lambda: self.bitCalcBackspace(state))
                elif label == "+/-":
                    button.clicked.connect(lambda: self.bitCalcToggleSign(state))
                elif label == "=":
                    button.clicked.connect(lambda: self.bitCalcEvaluate(state))
                else:
                    button.setEnabled(False)
                grid.addWidget(button, rowIdx, colIdx)
        return widget

    def createBitGrid(self, state):
        widget = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        widget.setLayout(grid)
        for groupIdx, groupStart in enumerate(range(60, -1, -4)):
            group = QWidget()
            groupLayout = QVBoxLayout()
            groupLayout.setContentsMargins(0, 0, 0, 0)
            groupLayout.setSpacing(2)
            bitsRow = QHBoxLayout()
            bitsRow.setSpacing(2)
            for bit in range(groupStart + 3, groupStart - 1, -1):
                button = QPushButton("0")
                button.setObjectName("bitCell")
                button.setCheckable(True)
                button.setToolTip(_("Toggle bit") + " {}".format(bit))
                button.clicked.connect(lambda _checked=False, index=bit: self.bitCalcToggleBit(state, index))
                bitsRow.addWidget(button)
                state["bitButtons"][bit] = button
            label = QLabel(str(groupStart))
            label.setAlignment(Qt.AlignCenter)
            groupLayout.addLayout(bitsRow)
            groupLayout.addWidget(label)
            group.setLayout(groupLayout)
            grid.addWidget(group, groupIdx // 4, groupIdx % 4)
        return widget

    def bitCalcWordMask(self, state):
        return (1 << state["wordBits"]) - 1

    def bitCalcCurrentValue(self, state):
        text = state["entry"].strip()
        if not text:
            return 0
        base = {"HEX": 16, "DEC": 10, "OCT": 8, "BIN": 2}[state["base"]]
        return int(text, base) & self.bitCalcWordMask(state)

    def bitCalcFormatValue(self, value, baseName, wordBits=None):
        if baseName == "HEX":
            width = max(1, ((wordBits or 4) + 3) // 4)
            return "{:0{}X}".format(value, width)
        if baseName == "OCT":
            return "{:o}".format(value)
        if baseName == "BIN":
            width = wordBits or max(1, value.bit_length())
            raw = "{:0{}b}".format(value, width)
            return " ".join(raw[i:i + 4] for i in range(0, len(raw), 4))
        return str(value)

    def bitCalcSetEntryValue(self, state, value, newEntry=False):
        value = int(value) & self.bitCalcWordMask(state)
        state["value"] = value
        state["entry"] = self.bitCalcFormatValue(value, state["base"]).replace(" ", "")
        state["newEntry"] = newEntry
        self.bitCalcRefresh(state)

    def bitCalcRefresh(self, state):
        try:
            value = self.bitCalcCurrentValue(state)
        except Exception:
            value = state.get("value", 0)
        state["value"] = value
        state["display"].setText(self.bitCalcFormatValue(value, state["base"]))
        state["exprLabel"].setText(state["expr"])
        for baseName, label in state["baseValues"].items():
            label.setText(self.bitCalcFormatValue(value, baseName, state["wordBits"]))
        for baseName, button in state["baseButtons"].items():
            button.setChecked(baseName == state["base"])
        allowed = self.bitCalcAllowedDigits(state["base"])
        for digit, button in state["digitButtons"].items():
            button.setEnabled(digit in allowed)
        for bit, button in state["bitButtons"].items():
            enabled = bit < state["wordBits"]
            button.setEnabled(enabled)
            button.setChecked(bool(value & (1 << bit)) if enabled else False)
            button.setText("1" if enabled and value & (1 << bit) else "0")

    def bitCalcAllowedDigits(self, baseName):
        if baseName == "HEX":
            return set("0123456789ABCDEF")
        if baseName == "DEC":
            return set("0123456789")
        if baseName == "OCT":
            return set("01234567")
        return set("01")

    def bitCalcSetBase(self, state, baseName):
        value = self.bitCalcCurrentValue(state)
        state["base"] = baseName
        self.bitCalcSetEntryValue(state, value)

    def bitCalcSetWordBits(self, state, wordName):
        state["wordBits"] = {"BYTE": 8, "WORD": 16, "DWORD": 32, "QWORD": 64}.get(wordName, 64)
        self.bitCalcSetEntryValue(state, self.bitCalcCurrentValue(state))

    def bitCalcAppendDigit(self, state, digit):
        if digit not in self.bitCalcAllowedDigits(state["base"]):
            return
        if state["newEntry"] or state["entry"] == "0":
            state["entry"] = digit
        else:
            state["entry"] += digit
        state["newEntry"] = False
        self.bitCalcSetEntryValue(state, self.bitCalcCurrentValue(state))
        state["newEntry"] = False

    def bitCalcClear(self, state):
        state["expr"] = ""
        self.bitCalcSetEntryValue(state, 0)

    def bitCalcBackspace(self, state):
        if state["newEntry"]:
            self.bitCalcSetEntryValue(state, 0)
            return
        state["entry"] = state["entry"][:-1] or "0"
        self.bitCalcSetEntryValue(state, self.bitCalcCurrentValue(state))

    def bitCalcToggleSign(self, state):
        self.bitCalcSetEntryValue(state, -self.bitCalcCurrentValue(state))

    def bitCalcToggleBit(self, state, bit):
        if bit >= state["wordBits"]:
            return
        value = self.bitCalcCurrentValue(state) ^ (1 << bit)
        self.bitCalcSetEntryValue(state, value)

    def bitCalcPressOperator(self, state, op):
        token = {"*": "*", "/": "//", "+": "+", "-": "-", "%": "%", "<<": "<<", ">>": ">>", "AND": "&", "OR": "|", "XOR": "^"}.get(op, op)
        expr = state["expr"].rstrip()
        if not expr or not state["newEntry"]:
            expr = (expr + " " + str(self.bitCalcCurrentValue(state))).strip()
        expr = re.sub(r"(<<|>>|//|[+\-*%&|^])$", "", expr).rstrip()
        state["expr"] = (expr + " " + token + " ").lstrip()
        state["newEntry"] = True
        self.bitCalcRefresh(state)

    def bitCalcApplyNamedOp(self, state, op):
        if op == "NOT":
            self.bitCalcSetEntryValue(state, ~self.bitCalcCurrentValue(state))
        else:
            self.bitCalcPressOperator(state, op)

    def bitCalcPressParen(self, state, paren):
        if paren == "(":
            state["expr"] += "("
            state["newEntry"] = True
        else:
            if not state["newEntry"]:
                state["expr"] += str(self.bitCalcCurrentValue(state))
            state["expr"] += ")"
            state["newEntry"] = True
        self.bitCalcRefresh(state)

    def bitCalcEvaluate(self, state):
        expr = state["expr"].strip()
        if not expr:
            self.bitCalcRefresh(state)
            return
        if not state["newEntry"] or re.search(r"(<<|>>|//|[+\-*%&|^(])\s*$", expr):
            expr += " " + str(self.bitCalcCurrentValue(state))
        try:
            value = self.bitCalcSafeEval(expr)
            state["expr"] = ""
            self.bitCalcSetEntryValue(state, value, newEntry=True)
        except Exception as e:
            self.showError(e)

    def bitCalcSafeEval(self, expression):
        node = ast.parse(expression, mode="eval")
        return self.bitCalcEvalNode(node.body)

    def bitCalcEvalNode(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Num):
            return node.n
        if isinstance(node, ast.UnaryOp):
            value = self.bitCalcEvalNode(node.operand)
            if isinstance(node.op, ast.Invert):
                return ~value
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.BinOp):
            left = self.bitCalcEvalNode(node.left)
            right = self.bitCalcEvalNode(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.FloorDiv):
                if right == 0:
                    raise ValueError(_("Divide by zero"))
                return left // right
            if isinstance(node.op, ast.Mod):
                if right == 0:
                    raise ValueError(_("Divide by zero"))
                return left % right
            if isinstance(node.op, ast.LShift):
                return left << right
            if isinstance(node.op, ast.RShift):
                return left >> right
            if isinstance(node.op, ast.BitAnd):
                return left & right
            if isinstance(node.op, ast.BitOr):
                return left | right
            if isinstance(node.op, ast.BitXor):
                return left ^ right
        raise ValueError(_("Format error"))

    def createBitwiseTool(self):
        card = ToolCard(
            _("Multi-bit operations"),
            _("Run byte-level AND, OR, XNOR, XOR, and NOT operations on two text or HEX inputs.")
        )
        hexRadio, _textRadio = self.addInputModeRadios(card)
        inputA = card.addTextArea(_("Input A") + ":", _("Input string or HEX"), False, 90)
        inputB = card.addTextArea(_("Input B") + ":", _("Input string or HEX"), False, 90)
        resultFields = {
            "and": card.addResultLine("AND:"),
            "or": card.addResultLine("OR:"),
            "xnor": card.addResultLine("XNOR:"),
            "xor": card.addResultLine("XOR:"),
            "notA": card.addResultLine("NOT A:"),
            "notB": card.addResultLine("NOT B:"),
        }
        card.addButton(_("Calculate"), lambda: self.calcBitwise(inputA, inputB, resultFields, hexRadio.isChecked()))
        card.addButton(_("Clear"), lambda: self.clearBitwise(inputA, inputB, resultFields), primary=False)
        card.finishButtons()
        return card

    def clearBitwise(self, inputA, inputB, resultFields):
        inputA.clear()
        inputB.clear()
        for field in resultFields.values():
            field.clear()

    def calcBitwise(self, inputA, inputB, resultFields, isHex):
        try:
            dataA = self.parseBytes(inputA.toPlainText(), isHex)
            dataB = self.parseBytes(inputB.toPlainText(), isHex)
            maxLen = max(len(dataA), len(dataB))
            a = dataA.ljust(maxLen, b"\x00")
            b = dataB.ljust(maxLen, b"\x00")
            if len(dataA) != len(dataB):
                self.showWarning(_("Inputs have different lengths; shorter input is padded with 00 for two-input operations."))
            self.setOutput(resultFields["and"], self.formatBytes(bytes(x & y for x, y in zip(a, b))))
            self.setOutput(resultFields["or"], self.formatBytes(bytes(x | y for x, y in zip(a, b))))
            self.setOutput(resultFields["xnor"], self.formatBytes(bytes((~(x ^ y)) & 0xFF for x, y in zip(a, b))))
            self.setOutput(resultFields["xor"], self.formatBytes(bytes(x ^ y for x, y in zip(a, b))))
            self.setOutput(resultFields["notA"], self.formatBytes(bytes((~x) & 0xFF for x in dataA)))
            self.setOutput(resultFields["notB"], self.formatBytes(bytes((~x) & 0xFF for x in dataB)))
        except Exception as e:
            self.fillErrorResult(resultFields, e)

    def createCaseConvertTool(self):
        card = ToolCard(
            _("English case convert"),
            _("Convert English text between uppercase, lowercase, title case, and swapped case.")
        )
        inp, out, _buttons = card.addInputOutput(_("Input English text"), _("Converted text"))
        card.addButton(_("Uppercase"), lambda: self.convertCaseText(inp, out, "upper"))
        card.addButton(_("Lowercase"), lambda: self.convertCaseText(inp, out, "lower"))
        card.addButton(_("Title case"), lambda: self.convertCaseText(inp, out, "title"))
        card.addButton(_("Swap case"), lambda: self.convertCaseText(inp, out, "swap"))
        card.addButton(_("Clear"), lambda: self.clearTextPair(inp, out), primary=False)
        card.finishButtons()
        return card

    def convertCaseText(self, inp, out, mode):
        text = inp.toPlainText()
        if mode == "upper":
            result = text.upper()
        elif mode == "lower":
            result = text.lower()
        elif mode == "title":
            result = text.title()
        else:
            result = text.swapcase()
        self.setOutput(out, result)
        self.showInfo(_("Conversion complete"))

    def createStringReverseTool(self):
        card = ToolCard(
            _("String reverse"),
            _("Reverse the input string by character order.")
        )
        inp, out, _buttons = card.addInputOutput(_("Input string"), _("Reversed string"))
        card.addButton(_("Reverse"), lambda: self.reverseString(inp, out))
        card.addButton(_("Clear"), lambda: self.clearTextPair(inp, out), primary=False)
        card.finishButtons()
        return card

    def reverseString(self, inp, out):
        self.setOutput(out, inp.toPlainText()[::-1])
        self.showInfo(_("Conversion complete"))

    def createCharCountTool(self):
        card = ToolCard(
            _("Character count"),
            _("Count characters, non-space characters, words, lines, and UTF-8 bytes in the input string.")
        )
        inp = card.addTextArea(_("Input string") + ":", _("Input string"), False, 140)
        resultFields = {
            "chars": card.addResultLine(_("Characters") + ":"),
            "noSpace": card.addResultLine(_("Characters without spaces") + ":"),
            "words": card.addResultLine(_("Words") + ":"),
            "lines": card.addResultLine(_("Lines") + ":"),
            "bytes": card.addResultLine(_("UTF-8 bytes") + ":"),
        }
        frequencyOutput = card.addTextArea(_("Character frequency") + ":", _("Character frequency"), True, 120)
        resultFields["frequency"] = frequencyOutput
        card.addButton(_("Count"), lambda: self.countString(inp, resultFields))
        card.addButton(_("Clear"), lambda: self.clearCharCount(inp, resultFields), primary=False)
        card.finishButtons()
        return card

    def countString(self, inp, resultFields):
        text = inp.toPlainText()
        self.setOutput(resultFields["chars"], str(len(text)))
        self.setOutput(resultFields["noSpace"], str(len(re.sub(r"\s+", "", text))))
        self.setOutput(resultFields["words"], str(len(re.findall(r"\S+", text))))
        self.setOutput(resultFields["lines"], str(0 if text == "" else text.count("\n") + 1))
        self.setOutput(resultFields["bytes"], str(len(text.encode("utf-8"))))
        counts = {}
        for char in text:
            counts[char] = counts.get(char, 0) + 1
        frequencyLines = [
            "{}：{}".format(self.formatCountChar(char), count)
            for char, count in counts.items()
        ]
        self.setOutput(resultFields["frequency"], "\n".join(frequencyLines))
        self.showInfo(_("Count complete"))

    def formatCountChar(self, char):
        if char == "\n":
            return "\\n"
        if char == "\t":
            return "\\t"
        if char == " ":
            return _("Space")
        return char

    def clearTextPair(self, inp, out):
        inp.clear()
        out.clear()

    def clearCharCount(self, inp, resultFields):
        inp.clear()
        for field in resultFields.values():
            field.clear()

    def createEccTool(self):
        card = ToolCard(
            _("ECC encrypt/decrypt"),
            _("Generate ECC key pairs and encrypt/decrypt text with ECIES style ECDH + AES-GCM.")
        )
        curveBox = ComboBox()
        curveBox.addItems(["SECP256R1", "SECP384R1", "SECP521R1", "SECP256K1"])
        card.addFormRow(_("Curve") + ":", curveBox)
        privateKeyInput = card.addTextArea(_("Private key") + ":", _("PEM private key"), False, 120)
        publicKeyInput = card.addTextArea(_("Public key") + ":", _("PEM public key"), False, 120)
        dataInput = card.addTextArea(_("Plain text or cipher JSON") + ":", _("Input text or ECC cipher JSON"), False, 120)
        output = card.addTextArea(_("Conversion result") + ":", _("Result"), True, 140)
        card.addButton(_("Generate key pair"), lambda: self.generateEccKeyPair(curveBox.currentText(), privateKeyInput, publicKeyInput))
        card.addButton(_("Encrypt"), lambda: self.eccEncrypt(publicKeyInput, dataInput, output))
        card.addButton(_("Decrypt"), lambda: self.eccDecrypt(privateKeyInput, dataInput, output))
        card.addButton(_("Clear"), lambda: self.clearEccTool(privateKeyInput, publicKeyInput, dataInput, output), primary=False)
        card.finishButtons()
        return card

    def eccReady(self):
        if AESGCM is None or ec is None or HKDF is None or hashes is None or serialization is None:
            self.showError(_("ECC backend not available"))
            return False
        return True

    def eccCurve(self, name):
        curves = {
            "SECP256R1": ec.SECP256R1,
            "SECP384R1": ec.SECP384R1,
            "SECP521R1": ec.SECP521R1,
            "SECP256K1": ec.SECP256K1,
        }
        return curves.get(name, ec.SECP256R1)()

    def generateEccKeyPair(self, curveName, privateKeyInput, publicKeyInput):
        if not self.eccReady():
            return
        try:
            privateKey = ec.generate_private_key(self.eccCurve(curveName), default_backend())
            publicKey = privateKey.public_key()
            privatePem = privateKey.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode("utf-8")
            publicPem = publicKey.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode("utf-8")
            self.setOutput(privateKeyInput, privatePem)
            self.setOutput(publicKeyInput, publicPem)
            self.showInfo(_("ECC key pair generated"))
        except Exception as e:
            self.showError(e)

    def clearEccTool(self, privateKeyInput, publicKeyInput, dataInput, output):
        privateKeyInput.clear()
        publicKeyInput.clear()
        dataInput.clear()
        output.clear()

    def eccDeriveKey(self, privateKey, publicKey):
        shared = privateKey.exchange(ec.ECDH(), publicKey)
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"COMTool ECC ECIES AES-GCM",
            backend=default_backend()
        ).derive(shared)

    def eccEncrypt(self, publicKeyInput, dataInput, output):
        if not self.eccReady():
            return
        try:
            publicKeyText = publicKeyInput.toPlainText().strip().encode("utf-8")
            if not publicKeyText:
                raise ValueError(_("Public key is empty"))
            publicKey = serialization.load_pem_public_key(publicKeyText, backend=default_backend())
            if not isinstance(publicKey, ec.EllipticCurvePublicKey):
                raise ValueError(_("Public key is not an ECC public key"))
            ephemeralPrivate = ec.generate_private_key(publicKey.curve, default_backend())
            aesKey = self.eccDeriveKey(ephemeralPrivate, publicKey)
            nonce = os.urandom(12)
            cipherText = AESGCM(aesKey).encrypt(nonce, dataInput.toPlainText().encode("utf-8"), None)
            ephemeralPublicPem = ephemeralPrivate.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            payload = {
                "version": 1,
                "algorithm": "ECIES-HKDF-SHA256-AESGCM",
                "curve": publicKey.curve.name,
                "ephemeralPublicKey": base64.b64encode(ephemeralPublicPem).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(cipherText).decode("ascii"),
            }
            self.setOutput(output, json.dumps(payload, indent=2))
            self.showInfo(_("ECC encrypt complete"))
        except Exception as e:
            self.showError(e)

    def eccDecrypt(self, privateKeyInput, dataInput, output):
        if not self.eccReady():
            return
        try:
            privateKeyText = privateKeyInput.toPlainText().strip().encode("utf-8")
            if not privateKeyText:
                raise ValueError(_("Private key is empty"))
            privateKey = serialization.load_pem_private_key(privateKeyText, password=None, backend=default_backend())
            if not isinstance(privateKey, ec.EllipticCurvePrivateKey):
                raise ValueError(_("Private key is not an ECC private key"))
            payload = json.loads(dataInput.toPlainText())
            ephemeralPublicPem = base64.b64decode(payload["ephemeralPublicKey"])
            ephemeralPublic = serialization.load_pem_public_key(ephemeralPublicPem, backend=default_backend())
            nonce = base64.b64decode(payload["nonce"])
            cipherText = base64.b64decode(payload["ciphertext"])
            aesKey = self.eccDeriveKey(privateKey, ephemeralPublic)
            plain = AESGCM(aesKey).decrypt(nonce, cipherText, None)
            self.setOutput(output, plain.decode("utf-8", errors="replace"))
            self.showInfo(_("ECC decrypt complete"))
        except Exception as e:
            self.showError(e)

    def createUnicodeTool(self):
        card = ToolCard(_("Unicode"), _("Convert text to Unicode escape sequences, or restore Unicode escapes to readable text."))
        inp, out, _buttons = card.addInputOutput()
        card.addButton(_("Encode"), lambda: self.setOutput(out, inp.toPlainText().encode("unicode_escape").decode("ascii")))
        card.addButton(_("Decode"), lambda: self.decodeUnicode(inp, out))
        card.finishButtons()
        return card

    def decodeUnicode(self, inp, out):
        try:
            self.setOutput(out, codecs.decode(inp.toPlainText(), "unicode_escape"))
        except Exception as e:
            self.fail(out, e)

    def createUrlTool(self):
        card = ToolCard(_("URLEncode"), _("Encode text for use in URLs, or decode percent-escaped URL text."))
        inp, out, _buttons = card.addInputOutput()
        card.addButton(_("Encode"), lambda: self.setOutput(out, quote(inp.toPlainText(), safe="")))
        card.addButton(_("Decode"), lambda: self.setOutput(out, unquote(inp.toPlainText())))
        card.finishButtons()
        return card

    def createBase64Tool(self):
        card = ToolCard(_("Base64"), _("Encode text as Base64, or decode Base64 back to text with the current UTF-8 text encoding."))
        inp, out, _buttons = card.addInputOutput()
        card.addButton(_("Encode"), lambda: self.setOutput(out, base64.b64encode(inp.toPlainText().encode("utf-8")).decode("ascii")))
        card.addButton(_("Decode"), lambda: self.decodeBase64(inp, out))
        card.finishButtons()
        return card

    def decodeBase64(self, inp, out):
        try:
            self.setOutput(out, base64.b64decode(inp.toPlainText()).decode("utf-8", errors="replace"))
        except Exception as e:
            self.fail(out, e)

    def createPunycodeTool(self):
        card = ToolCard(_("Punycode"), _("Convert internationalized domain names between Unicode text and ASCII Punycode form."))
        inp, out, _buttons = card.addInputOutput(_("Input domain or text"), _("Converted value"))
        card.addButton(_("Encode"), lambda: self.idnaEncode(inp, out))
        card.addButton(_("Decode"), lambda: self.idnaDecode(inp, out))
        card.finishButtons()
        return card

    def idnaEncode(self, inp, out):
        try:
            self.setOutput(out, inp.toPlainText().strip().encode("idna").decode("ascii"))
        except Exception as e:
            self.fail(out, e)

    def idnaDecode(self, inp, out):
        try:
            self.setOutput(out, inp.toPlainText().strip().encode("ascii").decode("idna"))
        except Exception as e:
            self.fail(out, e)

    def createTimestampTool(self):
        card = ToolCard(_("Unix timestamp"), _("Convert Unix timestamps and local date-time strings. Date input format: YYYY-MM-DD HH:MM:SS."))
        self.timestampInput = QLineEdit()
        self.timestampInput.setPlaceholderText(_("Timestamp or date-time"))
        self.timestampInput.setToolTip(_("Enter seconds, milliseconds, or YYYY-MM-DD HH:MM:SS"))
        self.timestampInput.setObjectName("ip33ResultLine")
        card.addFormRow(_("Timestamp or date-time") + ":", self.timestampInput)
        self.timestampOutput = card.addTextArea(_("Conversion result") + ":", _("Result"), True, 120)
        card.addButton(_("Now"), self.fillCurrentTimestamp)
        card.addButton(_("To date-time"), self.timestampToDate)
        card.addButton(_("To timestamp"), self.dateToTimestamp)
        card.finishButtons()
        return card

    def fillCurrentTimestamp(self):
        self.timestampInput.setText(str(int(time.time())))
        self.timestampToDate()

    def timestampToDate(self):
        try:
            value = self.timestampInput.text().strip()
            stamp = float(value)
            if stamp > 100000000000:
                stamp = stamp / 1000
            dt = datetime.fromtimestamp(stamp)
            self.setOutput(self.timestampOutput, dt.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception as e:
            self.fail(self.timestampOutput, e)

    def dateToTimestamp(self):
        try:
            dt = datetime.strptime(self.timestampInput.text().strip(), "%Y-%m-%d %H:%M:%S")
            self.setOutput(self.timestampOutput, "{}\n{} ms".format(int(dt.timestamp()), int(dt.timestamp() * 1000)))
        except Exception as e:
            self.fail(self.timestampOutput, e)

    def createImageBase64Tool(self):
        card = ToolCard(_("Image to Base64"), _("Choose an image file and convert it to Base64 text or a data URL for embedding."))
        self.imagePathInput = QLineEdit()
        self.imagePathInput.setPlaceholderText(_("Image file path"))
        self.imagePathInput.setObjectName("ip33ResultLine")
        chooseButton = QPushButton(_("Choose file"))
        chooseButton.setObjectName("ip33Secondary")
        encodeButton = QPushButton(_("Convert"))
        encodeButton.setObjectName("ip33Primary")
        dataUrlCheck = QCheckBox(_("Output data URL"))
        dataUrlCheck.setChecked(True)
        self.imageBase64Output = card.createTextEdit(_("Result"), True, 180)
        row = QHBoxLayout()
        row.addWidget(card.addLabel(_("Image file path") + ":"))
        row.addWidget(self.imagePathInput, 1)
        row.addWidget(chooseButton)
        row.addWidget(encodeButton)
        row.addWidget(dataUrlCheck)
        card.layout.addLayout(row)
        card.layout.addWidget(card.addLabel(_("Conversion result") + ":"))
        card.layout.addWidget(self.imageBase64Output, 1)
        chooseButton.clicked.connect(self.chooseImageFile)
        encodeButton.clicked.connect(lambda: self.imageToBase64(dataUrlCheck.isChecked()))
        return card

    def chooseImageFile(self):
        path, _kind = QFileDialog.getOpenFileName(None, _("Choose file"), os.getcwd(), _("Image files (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;All Files (*)"))
        if path:
            self.imagePathInput.setText(path)

    def imageToBase64(self, dataUrl):
        path = self.imagePathInput.text().strip()
        try:
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
            if dataUrl:
                ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
                if ext == "jpg":
                    ext = "jpeg"
                encoded = "data:image/{};base64,{}".format(ext, encoded)
            self.setOutput(self.imageBase64Output, encoded)
        except Exception as e:
            self.fail(self.imageBase64Output, e)

    def createDomainTool(self):
        card = ToolCard(_("Chinese domain encoding"), _("Encode Chinese or other internationalized domain names to IDNA, or decode xn-- domains back to readable text."))
        inp, out, _buttons = card.addInputOutput(_("Input domain"), _("Converted domain"))
        card.addButton(_("Encode"), lambda: self.idnaEncode(inp, out))
        card.addButton(_("Decode"), lambda: self.idnaDecode(inp, out))
        card.finishButtons()
        return card

    def createMd5Tool(self):
        card = ToolCard(_("MD5 encrypt/decrypt"), _("Generate MD5 digests. MD5 is one-way and cannot be truly decrypted; use the compare field to verify candidate text."))
        inp = card.addTextArea(_("Original text") + ":", _("Input text"), False, 120)
        compare = QLineEdit()
        compare.setPlaceholderText(_("Optional MD5 hash to compare"))
        compare.setObjectName("ip33ResultLine")
        card.addFormRow(_("Compare hash") + ":", compare)
        resultFields = {
            "lower32": card.addResultLine(_("Lowercase 32-bit") + ":"),
            "upper32": card.addResultLine(_("Uppercase 32-bit") + ":"),
            "lower16": card.addResultLine(_("Lowercase 16-bit") + ":"),
            "upper16": card.addResultLine(_("Uppercase 16-bit") + ":"),
            "compare": card.addResultLine(_("Compare") + ":"),
        }
        def run():
            digest = hashlib.md5(inp.toPlainText().encode("utf-8")).hexdigest()
            self.setOutput(resultFields["lower32"], digest)
            self.setOutput(resultFields["upper32"], digest.upper())
            self.setOutput(resultFields["lower16"], digest[8:24])
            self.setOutput(resultFields["upper16"], digest[8:24].upper())
            candidate = compare.text().strip().lower()
            self.setOutput(resultFields["compare"], "" if not candidate else ("OK" if candidate == digest else _("Not match")))
        card.addButton(_("Generate"), run)
        card.addButton(_("Clear"), lambda: self.clearMd5Tool(inp, compare, resultFields), primary=False)
        card.finishButtons()
        return card

    def clearMd5Tool(self, inp, compare, resultFields):
        inp.clear()
        compare.clear()
        for field in resultFields.values():
            field.clear()

    def createAesTool(self):
        card = ToolCard(_("AES encrypt/decrypt"), _("AES text encryption and decryption. Supports ECB and CBC with PKCS7 padding. Key lengths: 16, 24, or 32 bytes."))
        inp, out, _buttons = card.addInputOutput(_("Input text or Base64 cipher text"), _("AES result"))
        form = QGridLayout()
        keyInput = QLineEdit()
        keyInput.setPlaceholderText(_("AES key"))
        keyInput.setObjectName("ip33ResultLine")
        ivInput = QLineEdit()
        ivInput.setPlaceholderText(_("CBC IV, 16 bytes"))
        ivInput.setObjectName("ip33ResultLine")
        modeBox = ComboBox()
        modeBox.addItems(["CBC", "ECB"])
        form.addWidget(QLabel(_("Key")), 0, 0)
        form.addWidget(keyInput, 0, 1)
        form.addWidget(QLabel(_("Mode")), 0, 2)
        form.addWidget(modeBox, 0, 3)
        form.addWidget(QLabel(_("IV")), 1, 0)
        form.addWidget(ivInput, 1, 1, 1, 3)
        card.layout.insertLayout(3, form)
        card.addButton(_("Encrypt"), lambda: self.aesCrypt(inp, out, keyInput.text(), ivInput.text(), modeBox.currentText(), True))
        card.addButton(_("Decrypt"), lambda: self.aesCrypt(inp, out, keyInput.text(), ivInput.text(), modeBox.currentText(), False))
        card.finishButtons()
        return card

    def aesCrypt(self, inp, out, key, iv, modeName, encrypt):
        if Cipher is None:
            self.showError(_("AES backend not available"))
            return
        try:
            keyBytes = key.encode("utf-8")
            if len(keyBytes) not in (16, 24, 32):
                raise ValueError(_("AES key must be 16, 24, or 32 bytes"))
            mode = modes.ECB() if modeName == "ECB" else modes.CBC(iv.encode("utf-8"))
            cipher = Cipher(algorithms.AES(keyBytes), mode, backend=default_backend())
            if encrypt:
                padder = padding.PKCS7(128).padder()
                data = padder.update(inp.toPlainText().encode("utf-8")) + padder.finalize()
                cryptor = cipher.encryptor()
                self.setOutput(out, base64.b64encode(cryptor.update(data) + cryptor.finalize()).decode("ascii"))
            else:
                cryptor = cipher.decryptor()
                data = cryptor.update(base64.b64decode(inp.toPlainText())) + cryptor.finalize()
                unpadder = padding.PKCS7(128).unpadder()
                plain = unpadder.update(data) + unpadder.finalize()
                self.setOutput(out, plain.decode("utf-8", errors="replace"))
        except Exception as e:
            self.fail(out, e)

    def createCodecTool(self):
        card = ToolCard(_("Encode/decode collection"), _("Common reversible text transforms for quick programming work."))
        method = ComboBox()
        method.addItems(["Hex", "ROT13", "HTML"])
        card.addFormRow(_("Algorithm") + ":", method)
        inp, out, _buttons = card.addInputOutput()
        card.addButton(_("Encode"), lambda: self.codecTransform(inp, out, method.currentText(), True))
        card.addButton(_("Decode"), lambda: self.codecTransform(inp, out, method.currentText(), False))
        card.finishButtons()
        return card

    def codecTransform(self, inp, out, method, encode):
        try:
            text = inp.toPlainText()
            if method == "Hex":
                value = text.encode("utf-8").hex(" ") if encode else bytes.fromhex(text).decode("utf-8", errors="replace")
            elif method == "ROT13":
                value = codecs.encode(text, "rot_13")
            else:
                value = html.escape(text) if encode else html.unescape(text)
            self.setOutput(out, value)
        except Exception as e:
            self.fail(out, e)

    def createHashTool(self):
        card = ToolCard(_("Hash collection"), _("Generate common hashes for the input text."))
        inp, out, _buttons = card.addInputOutput()
        card.addButton(_("Generate"), lambda: self.hashAll(inp, out))
        card.finishButtons()
        return card

    def hashAll(self, inp, out):
        data = inp.toPlainText().encode("utf-8")
        names = ["md5", "sha1", "sha224", "sha256", "sha384", "sha512"]
        lines = []
        for name in names:
            digest = hashlib.new(name, data).hexdigest()
            lines.append("{}: {}".format(name.upper(), digest))
        self.setOutput(out, "\n".join(lines))
