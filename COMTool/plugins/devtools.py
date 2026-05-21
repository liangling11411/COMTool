import binascii
import base64
import codecs
from datetime import datetime
import hashlib
import html
import os
import re
import time
from urllib.parse import quote, unquote

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout, QTextEdit,
    QLabel, QLineEdit, QFileDialog, QStackedWidget, QScrollArea,
    QGroupBox, QCheckBox
)

try:
    from Combobox import ComboBox
    from plugins.base import Plugin_Base
    from i18n import _
except ImportError:
    from COMTool.Combobox import ComboBox
    from COMTool.plugins.base import Plugin_Base
    from COMTool.i18n import _

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend
except Exception:
    Cipher = None


class ToolCard(QWidget):
    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(8)
        self.setLayout(self.layout)

        titleLabel = QLabel(title)
        titleLabel.setProperty("class", "title")
        titleLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        descLabel = QLabel(description)
        descLabel.setWordWrap(True)
        descLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.layout.addWidget(titleLabel)
        self.layout.addWidget(descLabel)

    def addInputOutput(self, inputPlaceholder=None, outputPlaceholder=None):
        self.input = QTextEdit()
        self.input.setAcceptRichText(False)
        self.input.setPlaceholderText(inputPlaceholder or _("Input text"))
        self.output = QTextEdit()
        self.output.setAcceptRichText(False)
        self.output.setPlaceholderText(outputPlaceholder or _("Result"))
        self.layout.addWidget(self.input, 2)
        self.buttonLayout = QHBoxLayout()
        self.layout.addLayout(self.buttonLayout)
        self.layout.addWidget(self.output, 2)
        return self.input, self.output, self.buttonLayout

    def addButton(self, text, callback):
        button = QPushButton(text)
        button.setToolTip(text)
        button.clicked.connect(callback)
        self.buttonLayout.addWidget(button)
        return button

    def finishButtons(self):
        self.buttonLayout.addStretch(1)


class Plugin(Plugin_Base):
    id = "devtools"
    name = _("Programming Tools")

    def onInit(self, config):
        super().onInit(config)

    def onIsAddConnWidget(self):
        return False

    def onWidgetStatusBar(self, parent):
        return None

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
            ("rgb", _("RGB color format convert")),
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
        output.setPlainText("" if value is None else str(value))

    def fail(self, output, err):
        self.setOutput(output, _("Error") + ": " + str(err))

    def createByteTool(self, title, description, actionText, handler):
        card = ToolCard(title, description)
        inp, out, _buttons = card.addInputOutput(_("Input hex bytes or text"), _("Check result"))
        modeBox = ComboBox()
        modeBox.addItems([_("Hex bytes"), _("UTF-8 text")])
        modeBox.setToolTip(_("Choose whether the input is hex bytes like 01 02 AF or plain text"))
        card.layout.insertWidget(2, modeBox)
        card.addButton(actionText, lambda: handler(inp, out, modeBox.currentIndex() == 0))
        card.finishButtons()
        return card

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

    def createLrcTool(self):
        return self.createByteTool(
            _("LRC check"),
            _("Calculate the longitudinal redundancy check byte. The result is the two's complement of the byte sum, often used by serial text protocols."),
            _("Calculate LRC"),
            self.calcLrc
        )

    def calcLrc(self, inp, out, isHex):
        try:
            data = self.parseBytes(inp.toPlainText(), isHex)
            value = (-sum(data)) & 0xFF
            lines = [self.bytesInfo(data), "LRC: 0x{:02X}".format(value), _("Append byte") + ": {:02X}".format(value)]
            self.setOutput(out, "\n".join(lines))
        except Exception as e:
            self.fail(out, e)

    def createBccTool(self):
        return self.createByteTool(
            _("BCC check"),
            _("Calculate the block check character by XORing every input byte. It is useful for simple serial protocol frame checks."),
            _("Calculate BCC"),
            self.calcBcc
        )

    def calcBcc(self, inp, out, isHex):
        try:
            data = self.parseBytes(inp.toPlainText(), isHex)
            value = 0
            for byte in data:
                value ^= byte
            lines = [self.bytesInfo(data), "BCC: 0x{:02X}".format(value), _("Append byte") + ": {:02X}".format(value)]
            self.setOutput(out, "\n".join(lines))
        except Exception as e:
            self.fail(out, e)

    def createCrcTool(self):
        card = ToolCard(
            _("CRC check"),
            _("Calculate common cyclic redundancy checks for byte data. Hex input accepts spaces, commas, 0x prefixes, and line breaks.")
        )
        inp, out, _buttons = card.addInputOutput(_("Input hex bytes or text"), _("CRC result"))
        form = QGridLayout()
        modeBox = ComboBox()
        modeBox.addItems([_("Hex bytes"), _("UTF-8 text")])
        modeBox.setToolTip(_("Choose whether the input is hex bytes like 01 02 AF or plain text"))
        crcBox = ComboBox()
        crcBox.addItems(["CRC-16/MODBUS", "CRC-16/IBM", "CRC-8", "CRC-32"])
        crcBox.setToolTip(_("Choose CRC algorithm"))
        form.addWidget(QLabel(_("Input mode")), 0, 0)
        form.addWidget(modeBox, 0, 1)
        form.addWidget(QLabel(_("Algorithm")), 0, 2)
        form.addWidget(crcBox, 0, 3)
        card.layout.insertLayout(2, form)
        card.addButton(_("Calculate CRC"), lambda: self.calcCrc(inp, out, modeBox.currentIndex() == 0, crcBox.currentText()))
        card.finishButtons()
        return card

    def calcCrc(self, inp, out, isHex, algorithm):
        try:
            data = self.parseBytes(inp.toPlainText(), isHex)
            if algorithm == "CRC-16/MODBUS":
                value = self.crc16(data, 0xFFFF)
                lines = self.crc16Output(data, algorithm, value)
            elif algorithm == "CRC-16/IBM":
                value = self.crc16(data, 0x0000)
                lines = self.crc16Output(data, algorithm, value)
            elif algorithm == "CRC-8":
                value = self.crc8(data)
                lines = [self.bytesInfo(data), "{}: 0x{:02X}".format(algorithm, value), _("Append byte") + ": {:02X}".format(value)]
            else:
                value = binascii.crc32(data) & 0xFFFFFFFF
                lines = [self.bytesInfo(data), "{}: 0x{:08X}".format(algorithm, value), _("Append bytes") + ": {:08X}".format(value)]
            self.setOutput(out, "\n".join(lines))
        except Exception as e:
            self.fail(out, e)

    def crc16(self, data, initValue):
        crc = initValue
        for byte in data:
            crc ^= byte
            for _idx in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc & 0xFFFF

    def crc8(self, data):
        crc = 0
        for byte in data:
            crc ^= byte
            for _idx in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
        return crc

    def crc16Output(self, data, algorithm, value):
        lowHigh = "{:02X} {:02X}".format(value & 0xFF, value >> 8)
        highLow = "{:02X} {:02X}".format(value >> 8, value & 0xFF)
        return [
            self.bytesInfo(data),
            "{}: 0x{:04X}".format(algorithm, value),
            _("Low byte first") + ": " + lowHigh,
            _("High byte first") + ": " + highLow,
        ]

    def createRgbTool(self):
        card = ToolCard(
            _("RGB color format convert"),
            _("Convert common RGB color formats. Supports #RRGGBB, short #RGB, rgb(r,g,b), comma separated RGB, and decimal color values.")
        )
        inp, out, _buttons = card.addInputOutput(_("Input RGB color"), _("Converted color values"))
        card.addButton(_("Convert"), lambda: self.convertRgb(inp, out))
        card.finishButtons()
        return card

    def convertRgb(self, inp, out):
        try:
            r, g, b = self.parseRgb(inp.toPlainText())
            decimal = (r << 16) + (g << 8) + b
            lines = [
                "HEX: #{:02X}{:02X}{:02X}".format(r, g, b),
                "RGB: rgb({}, {}, {})".format(r, g, b),
                "RGB tuple: {}, {}, {}".format(r, g, b),
                "Decimal: {}".format(decimal),
                "BGR hex: #{:02X}{:02X}{:02X}".format(b, g, r),
            ]
            self.setOutput(out, "\n".join(lines))
        except Exception as e:
            self.fail(out, e)

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
        layout = QGridLayout()
        card.layout.addLayout(layout)
        self.timestampInput = QLineEdit()
        self.timestampInput.setPlaceholderText(_("Timestamp or date-time"))
        self.timestampInput.setToolTip(_("Enter seconds, milliseconds, or YYYY-MM-DD HH:MM:SS"))
        nowButton = QPushButton(_("Now"))
        toDateButton = QPushButton(_("To date-time"))
        toStampButton = QPushButton(_("To timestamp"))
        self.timestampOutput = QTextEdit()
        self.timestampOutput.setAcceptRichText(False)
        layout.addWidget(QLabel(_("Input")), 0, 0)
        layout.addWidget(self.timestampInput, 0, 1, 1, 3)
        layout.addWidget(nowButton, 1, 0)
        layout.addWidget(toDateButton, 1, 1)
        layout.addWidget(toStampButton, 1, 2)
        card.layout.addWidget(self.timestampOutput, 1)
        nowButton.clicked.connect(self.fillCurrentTimestamp)
        toDateButton.clicked.connect(self.timestampToDate)
        toStampButton.clicked.connect(self.dateToTimestamp)
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
        chooseButton = QPushButton(_("Choose file"))
        encodeButton = QPushButton(_("Convert"))
        dataUrlCheck = QCheckBox(_("Output data URL"))
        dataUrlCheck.setChecked(True)
        self.imageBase64Output = QTextEdit()
        self.imageBase64Output.setAcceptRichText(False)
        row = QHBoxLayout()
        row.addWidget(self.imagePathInput, 1)
        row.addWidget(chooseButton)
        row.addWidget(encodeButton)
        row.addWidget(dataUrlCheck)
        card.layout.addLayout(row)
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
        inp, out, _buttons = card.addInputOutput(_("Input text"), _("MD5 result"))
        compare = QLineEdit()
        compare.setPlaceholderText(_("Optional MD5 hash to compare"))
        card.layout.insertWidget(2, compare)
        def run():
            digest = hashlib.md5(inp.toPlainText().encode("utf-8")).hexdigest()
            result = [
                "32 lower: " + digest,
                "32 upper: " + digest.upper(),
                "16 lower: " + digest[8:24],
                "16 upper: " + digest[8:24].upper(),
            ]
            candidate = compare.text().strip().lower()
            if candidate:
                result.append(_("Compare") + ": " + ("OK" if candidate == digest else _("Not match")))
            self.setOutput(out, "\n".join(result))
        card.addButton(_("Generate"), run)
        card.finishButtons()
        return card

    def createAesTool(self):
        card = ToolCard(_("AES encrypt/decrypt"), _("AES text encryption and decryption. Supports ECB and CBC with PKCS7 padding. Key lengths: 16, 24, or 32 bytes."))
        inp, out, _buttons = card.addInputOutput(_("Input text or Base64 cipher text"), _("AES result"))
        form = QGridLayout()
        keyInput = QLineEdit()
        keyInput.setPlaceholderText(_("AES key"))
        ivInput = QLineEdit()
        ivInput.setPlaceholderText(_("CBC IV, 16 bytes"))
        modeBox = ComboBox()
        modeBox.addItems(["CBC", "ECB"])
        form.addWidget(QLabel(_("Key")), 0, 0)
        form.addWidget(keyInput, 0, 1)
        form.addWidget(QLabel(_("Mode")), 0, 2)
        form.addWidget(modeBox, 0, 3)
        form.addWidget(QLabel(_("IV")), 1, 0)
        form.addWidget(ivInput, 1, 1, 1, 3)
        card.layout.insertLayout(2, form)
        card.addButton(_("Encrypt"), lambda: self.aesCrypt(inp, out, keyInput.text(), ivInput.text(), modeBox.currentText(), True))
        card.addButton(_("Decrypt"), lambda: self.aesCrypt(inp, out, keyInput.text(), ivInput.text(), modeBox.currentText(), False))
        card.finishButtons()
        return card

    def aesCrypt(self, inp, out, key, iv, modeName, encrypt):
        if Cipher is None:
            self.setOutput(out, _("AES backend not available"))
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
        inp, out, _buttons = card.addInputOutput()
        method = ComboBox()
        method.addItems(["Hex", "ROT13", "HTML"])
        card.layout.insertWidget(2, method)
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
