from PyQt5.QtWidgets import QComboBox,QListView,QApplication
from PyQt5.QtCore import pyqtSignal


class ComboBox(QComboBox):
    clicked = pyqtSignal()
    # popupAboutToBeShown = pyqtSignal()

    def __init__(self):
        QComboBox.__init__(self)
        listView = QListView()
        listView.executeDelayedItemsLayout()
        self.setView(listView)

    def mouseReleaseEvent(self, QMouseEvent):
        self.showItems()

    def showPopup(self):
        # self.popupAboutToBeShown.emit()
        # prevent show popup, manually call it in mouse release event
        pass

    def _showPopup(self):
        max_w = 0
        for i in range(self.count()):
            w = self.view().sizeHintForColumn(i)
            if w > max_w:
                max_w = w

        screen_width = QApplication.desktop().availableGeometry().width()
        self.view().setMinimumWidth(min(max_w + 50, screen_width))
        super(ComboBox, self).showPopup()
    
    def showItems(self):
        self._showPopup()

    def mousePressEvent(self, QMouseEvent):
        self.clicked.emit()

    def wheelEvent(self, event):
        event.ignore()

