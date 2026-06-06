from PyQt5.QtWidgets import QComboBox,QListView,QApplication
from PyQt5.QtCore import pyqtSignal, QModelIndex, QEvent


class ComboBox(QComboBox):
    clicked = pyqtSignal()
    # popupAboutToBeShown = pyqtSignal()

    def __init__(self):
        QComboBox.__init__(self)
        listView = QListView()
        listView.setMouseTracking(True)
        listView.executeDelayedItemsLayout()
        self.setView(listView)
        listView.viewport().installEventFilter(self)

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
        self.clearPopupHover()
    
    def showItems(self):
        self._showPopup()

    def mousePressEvent(self, QMouseEvent):
        self.clicked.emit()

    def wheelEvent(self, event):
        event.ignore()

    def clearPopupHover(self):
        view = self.view()
        view.setCurrentIndex(QModelIndex())
        if view.selectionModel() is not None:
            view.selectionModel().clearSelection()

    def eventFilter(self, obj, event):
        if obj is self.view().viewport() and event.type() in (QEvent.Leave, QEvent.Hide):
            self.clearPopupHover()
        return super().eventFilter(obj, event)

