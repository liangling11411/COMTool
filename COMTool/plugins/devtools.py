import base64
import codecs
from datetime import datetime
import hashlib
import html
import json
import os
import re
import time
from urllib.parse import quote, unquote

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTextEdit, QLabel, QLineEdit, QFileDialog, QStackedWidget, QScrollArea,
    QCheckBox, QRadioButton, QButtonGroup, QColorDialog
)
from PyQt5.QtGui import QColor, QCursor

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



class Plugin(Plugin_Base):
    id = "devtools"
    name = _("Programming Tools")

    def onInit(self, config):
        super().onInit(config)

    def onIsAddConnWidget(self):
        return False

    def onWidgetStatusBar(self, parent):
        self.statusBar = statusBar(rxTxCount=False)
        return self.statusBar

    def onSettingsWidgetScrollTogether(self):
        return True

    def onWidgetSettings(self, parent):
        self.toolButtons = []
        panel = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(6)
        panel.setLayout(layout)
        for idx, (key, title) in enumerate(self.toolDefinitions()):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setToolTip(_("Open tool") + ": " + title)
            button.clicked.connect(lambda _checked=False, index=idx: self.setTool(index))
            layout.addWidget(button)
            self.toolButtons.append(button)
        layout.addStretch(1)
        return panel

    def onWidgetMain(self, parent):
        self.stack = QStackedWidget()
        for key, _title in self.toolDefinitions():
            self.stack.addWidget(self.wrapTool(self.createTool(key)))
        self.setTool(0)
        return self.stack

    def toolDefinitions(self):
        return [
            ("lrc", _("LRC check")),
            ("bcc", _("BCC check")),
            ("crc", _("CRC check")),
            ("rgb", _("Color format convert")),
            ("bitwise", _("Bitwise operations")),
            ("ecc", _("ECC encrypt/decrypt")),
            ("unicode", _("Unicode")),
            ("url", _("URLEncode")),
            ("base64", _("Base64")),
            ("punycode", _("Punycode")),
            ("timestamp", _("Unix timestamp")),
            ("image_base64", _("Image to Base64")),
            ("domain", _("Chinese domain encoding")),
            ("md5", _("MD5 encrypt/decrypt")),
            ("aes", _("AES encrypt/decrypt")),
            ("codec", _("Encode/decode collection")),
            ("hash", _("Hash collection")),
        ]

    def wrapTool(self, widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(widget)
        return scroll

    def setTool(self, index):
        if hasattr(self, "stack"):
            self.stack.setCurrentIndex(index)
        for idx, button in enumerate(getattr(self, "toolButtons", [])):
            button.setChecked(idx == index)

    def createTool(self, key):
        creators = {
            "lrc": self.createLrcTool,
            "bcc": self.createBccTool,
            "crc": self.createCrcTool,
            "rgb": self.createRgbTool,
            "bitwise": self.createBitwiseTool,
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
            _("Convert common RGB color formats. Supports #RRGGBB, short #RGB, rgb(r,g,b), comma separated RGB, and decimal color values.")
        )
        inp = QLineEdit()
        inp.setPlaceholderText("#336699 / rgb(51,102,153) / 51,102,153")
        inp.setObjectName("ip33ResultLine")
        screenPickButton = QPushButton(_("Screen pick"))
        screenPickButton.setObjectName("ip33Secondary")
        previewButton = QPushButton("")
        previewButton.setObjectName("ip33Secondary")
        previewButton.setFixedWidth(54)
        card.addFormRow(_("Color") + ":", [inp, screenPickButton, previewButton])
        colorDialog = QColorDialog(QColor("#336699"), card)
        colorDialog.setOption(QColorDialog.NoButtons, True)
        colorDialog.setOption(QColorDialog.DontUseNativeDialog, True)
        colorDialog.setToolTip(_("Palette"))
        card.layout.addWidget(colorDialog)
        resultFields = {
            "hex": card.addResultLine("HEX:"),
            "rgb": card.addResultLine("RGB:"),
            "tuple": card.addResultLine(_("RGB tuple") + ":"),
            "dec": card.addResultLine(_("Decimal") + ":"),
            "bgr": card.addResultLine("BGR HEX:"),
        }
        colorDialog.currentColorChanged.connect(lambda color: self.setColorFromDialog(color, inp, previewButton, resultFields))
        screenPickButton.clicked.connect(lambda: self.pickScreenRgbColorDelayed(inp, previewButton, resultFields, screenPickButton))
        card.addButton(_("Convert"), lambda: self.convertRgb(inp, resultFields, previewButton))
        card.addButton(_("Clear"), lambda: self.clearRgbTool(inp, resultFields, previewButton, colorDialog), primary=False)
        card.finishButtons()
        self.setColorFromDialog(QColor("#336699"), inp, previewButton, resultFields)
        return card

    def clearRgbTool(self, inp, resultFields, previewButton=None, colorDialog=None):
        inp.clear()
        for field in resultFields.values():
            field.clear()
        if previewButton is not None:
            previewButton.setStyleSheet("")
        if colorDialog is not None:
            colorDialog.blockSignals(True)
            colorDialog.setCurrentColor(QColor("#336699"))
            colorDialog.blockSignals(False)

    def setColorFromDialog(self, color, inp, previewButton, resultFields):
        if color.isValid():
            inp.setText(color.name().upper())
            self.convertRgb(inp, resultFields, previewButton)

    def pickScreenRgbColorDelayed(self, inp, previewButton, resultFields, button):
        oldText = button.text()
        button.setText(_("Move cursor to color"))
        button.setEnabled(False)
        QTimer.singleShot(1000, lambda: self.pickScreenRgbColor(inp, previewButton, resultFields, button, oldText))

    def pickScreenRgbColor(self, inp, previewButton, resultFields, button, oldText):
        try:
            pos = QCursor.pos()
            screen = QApplication.screenAt(pos) if hasattr(QApplication, "screenAt") else QApplication.primaryScreen()
            if screen is None:
                screen = QApplication.primaryScreen()
            pixmap = screen.grabWindow(0, pos.x(), pos.y(), 1, 1)
            color = pixmap.toImage().pixelColor(0, 0)
            if color.isValid():
                inp.setText(color.name().upper())
                self.convertRgb(inp, resultFields, previewButton)
        finally:
            button.setText(oldText)
            button.setEnabled(True)

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

    def createBitwiseTool(self):
        card = ToolCard(
            _("Bitwise operations"),
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
