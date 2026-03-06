import os
import sys
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette, QIcon
from PyQt5.QtWidgets import QApplication
from windows import DeviceSelectionWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        icon_path = os.path.join(os.path.dirname(__file__), "ad.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception:
        pass
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(palette)
    selector = DeviceSelectionWindow()
    selector.resize(600, 240)
    selector.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
