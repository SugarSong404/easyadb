import os
import posixpath
import pathlib
import json
from PyQt5.QtCore import Qt, pyqtSignal, QMimeData, QPoint, QEvent, QTimer
from PyQt5.QtGui import QColor, QDrag, QFont
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QLineEdit, QLabel, QHeaderView, QMenu, QAction, QInputDialog


class DnDTable(QTableWidget):
    def __init__(self, pane, source_type, parent=None):
        super().__init__(parent)
        self.pane = pane
        self.source_type = source_type
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDragDropMode(QTableWidget.DragDrop)
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)
        self._hover_row = -1
        self._folder_hover_timer = QTimer(self)
        self._folder_hover_timer.setSingleShot(True)
        self._folder_hover_timer.setInterval(1000)
        self._folder_hover_timer.timeout.connect(self._on_folder_hover_timeout)
        self._pending_enter_name = None

    def startDrag(self, supportedActions):
        rows = set([i.row() for i in self.selectedIndexes()])
        items = []
        for r in rows:
            name = self.item(r, 0).text()
            is_dir = self.item(r, 1).text() == "目录"
            items.append({"name": name, "is_dir": is_dir})
        payload = {
            "source": self.source_type,
            "base": self.pane.current_path,
            "items": items,
        }
        md = QMimeData()
        md.setData("application/x-easyadb", json.dumps(payload).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(md)
        try:
            self.pane.set_up_btn_drag_active(True)
        except Exception:
            pass
        drag.exec(Qt.MoveAction | Qt.CopyAction, Qt.MoveAction)
        try:
            self.pane.set_up_btn_drag_active(False)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if obj is self.viewport():
            if event.type() in (QEvent.DragEnter, QEvent.DragMove):
                md = event.mimeData()
                if md and md.hasFormat("application/x-easyadb"):
                    try:
                        data = json.loads(bytes(md.data("application/x-easyadb")).decode("utf-8"))
                        try:
                            self.pane.set_up_btn_drag_active(True)
                        except Exception:
                            pass
                        same_side = data.get("source") == self.source_type
                        if same_side:
                            event.setDropAction(Qt.MoveAction)
                        else:
                            event.setDropAction(Qt.CopyAction)
                        if same_side:
                            idx = self.indexAt(event.pos())
                            new_row = idx.row() if idx.isValid() else -1
                            new_is_dir = False
                            new_name = None
                            if idx.isValid():
                                try:
                                    new_is_dir = self.item(new_row, 1).text() == "目录"
                                    new_name = self.item(new_row, 0).text()
                                except Exception:
                                    new_is_dir = False
                            if new_row != self._hover_row:
                                self._clear_hover_row()
                                self._folder_hover_timer.stop()
                                if new_row >= 0 and new_is_dir:
                                    self._set_hover_row(new_row, True)
                                    self._pending_enter_name = new_name
                                    self._folder_hover_timer.start()
                            else:
                                if new_row >= 0 and new_is_dir and not self._folder_hover_timer.isActive():
                                    self._pending_enter_name = new_name
                                    self._folder_hover_timer.start()
                        else:
                            self._clear_hover_row()
                            self._folder_hover_timer.stop()
                        event.accept()
                        return True
                    except Exception:
                        pass
                event.ignore()
                return True
            if event.type() == QEvent.DragLeave:
                self._clear_hover_row()
                self._folder_hover_timer.stop()
                try:
                    self.pane.set_up_btn_drag_active(False)
                except Exception:
                    pass
                event.accept()
                return True
            if event.type() == QEvent.Drop:
                try:
                    data = json.loads(bytes(event.mimeData().data("application/x-easyadb")).decode("utf-8"))
                except Exception:
                    event.ignore()
                    return True
                self._clear_hover_row()
                self._folder_hover_timer.stop()
                try:
                    self.pane.set_up_btn_drag_active(False)
                except Exception:
                    pass
                idx = self.indexAt(event.pos())
                target_dir_name = None
                if idx.isValid():
                    row = idx.row()
                    is_dir = self.item(row, 1).text() == "目录"
                    if is_dir:
                        target_dir_name = self.item(row, 0).text()
                data["target_base"] = self.pane.current_path
                if target_dir_name:
                    data["target_dir"] = target_dir_name
                if data.get("source") == self.source_type:
                    event.setDropAction(Qt.MoveAction)
                    self.pane.internalDropReceived.emit(data)
                else:
                    event.setDropAction(Qt.CopyAction)
                    self.pane.dropReceived.emit(data)
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def _set_hover_row(self, row, on: bool):
        if row < 0 or row >= self.rowCount():
            return
        color = QColor(70, 90, 120) if on else self.palette().base().color()
        for c in range(self.columnCount()):
            it = self.item(row, c)
            if it:
                it.setBackground(color)
        self._hover_row = row if on else -1

    def _clear_hover_row(self):
        if self._hover_row >= 0:
            self._set_hover_row(self._hover_row, False)
        self._hover_row = -1
        self._pending_enter_name = None

    def _on_folder_hover_timeout(self):
        if self._hover_row >= 0 and self._pending_enter_name:
            name = self._pending_enter_name
            try:
                if self.pane.is_posix:
                    new_path = posixpath.join(self.pane.current_path if self.pane.current_path else "/", name)
                else:
                    new_path = os.path.join(self.pane.current_path, name)
                self.pane.navigate_to(new_path)
            except Exception:
                pass
        self._clear_hover_row()


class Breadcrumb(QWidget):
    pathChanged = pyqtSignal(str)

    def __init__(self, is_posix=False, parent=None):
        super().__init__(parent)
        self.is_posix = is_posix
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(4)
        self.current_path = ""

    def setPath(self, path):
        self.current_path = path
        while self.layout.count():
            w = self.layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        parts = []
        if self.is_posix:
            p = path if path else "/"
            if p.startswith("/"):
                parts.append(("/", "/"))
                rest = p[1:]
            else:
                rest = p
            for seg in [s for s in rest.split("/") if s]:
                prev = parts[-1][1] if parts else ""
                full = posixpath.join(prev if prev else "/", seg) if prev else "/" + seg
                parts.append((seg, full))
        else:
            p = pathlib.Path(path)
            try:
                drive = p.anchor if p.anchor else str(pathlib.Path.cwd().anchor)
            except Exception:
                drive = p.anchor
            if drive:
                parts.append((drive.rstrip("\\/"), drive))
            rest_parts = [s for s in p.parts if s not in [drive, "\\", "/"]]
            cur = drive
            for seg in rest_parts:
                cur = os.path.join(cur, seg) if cur else seg
                parts.append((seg, cur))
        for i, (label, full) in enumerate(parts):
            b = QPushButton(label)
            b.setFont(QFont("", 9))
            b.setCursor(Qt.PointingHandCursor)
            b.setFlat(False)
            b.setStyleSheet(
                "QPushButton {"
                " background-color: #3f3f3f;"
                " color: #ffffff;"
                " border: 1px solid #5a5a5a;"
                " border-radius: 6px;"
                " padding: 2px 6px;"
                "}"
                "QPushButton:hover {"
                " background-color: #505050;"
                "}"
                "QPushButton:pressed {"
                " background-color: #606060;"
                "}"
            )
            b.clicked.connect(lambda _, f=full: self.pathChanged.emit(f))
            self.layout.addWidget(b)
            if i < len(parts) - 1:
                sep = QLabel("/" if self.is_posix else "\\")
                sep.setFont(QFont("", 9))
                sep.setStyleSheet("color: gray;")
                self.layout.addWidget(sep)
        self.layout.addStretch(1)


class FilePane(QWidget):
    pathChanged = pyqtSignal(str)
    dropReceived = pyqtSignal(dict)
    internalDropReceived = pyqtSignal(dict)
    deleteRequested = pyqtSignal(list)
    renameRequested = pyqtSignal(dict)
    fileOpenRequested = pyqtSignal(dict)
    newFolderRequested = pyqtSignal(str)
    newFileRequested = pyqtSignal(str)
    refreshRequested = pyqtSignal()

    def __init__(self, title, is_posix=False, pane_type="local", parent=None):
        super().__init__(parent)
        self.is_posix = is_posix
        self.pane_type = pane_type
        self.current_path = ""
        self.title = title
        self.breadcrumb = Breadcrumb(is_posix=is_posix, parent=self)
        self.path_edit = QLineEdit(self)
        self.up_btn = QPushButton("上一级", self)
        self.table = DnDTable(self, pane_type, self)
        self.setAcceptDrops(True)
        self.up_btn.setAcceptDrops(True)
        self.up_btn.installEventFilter(self)
        self._drag_hovering_up = False
        self._up_btn_default_style = self.up_btn.styleSheet()
        self._up_hover_timer = QTimer(self)
        self._up_hover_timer.setSingleShot(True)
        self._up_hover_timer.setInterval(1000)
        self._up_hover_timer.timeout.connect(self._on_up_hover_timeout)
        self.header = QLabel(title, self)
        self.header.setFont(QFont("", 11))
        self.path_edit.setFont(QFont("", 10))
        self.up_btn.setFont(QFont("", 10))
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self.header)
        top.addStretch(1)
        crumb_row = QHBoxLayout()
        crumb_row.addWidget(self.breadcrumb, 1)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.up_btn, 0)
        layout.addLayout(top)
        layout.addLayout(crumb_row)
        layout.addLayout(path_row)
        layout.addWidget(self.table, 1)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["名称", "类型"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_context_menu)
        self.breadcrumb.pathChanged.connect(self.navigate_to)
        self.table.setFont(QFont("", 10))
        self.table.horizontalHeader().setFont(QFont("", 10))
        self.table.verticalHeader().setDefaultSectionSize(26)
        if isinstance(self.path_edit, QLineEdit):
            self.path_edit.returnPressed.connect(self.return_pressed)
        self.up_btn.clicked.connect(self.navigate_up)
        self.table.cellDoubleClicked.connect(self.on_double_click)

    def eventFilter(self, obj, event):
        if obj is self.up_btn:
            if event.type() in (QEvent.DragEnter, QEvent.DragMove):
                md = event.mimeData()
                if md and md.hasFormat("application/x-easyadb"):
                    try:
                        data = json.loads(bytes(md.data("application/x-easyadb")).decode("utf-8"))
                        if data.get("source") == self.pane_type:
                            event.setDropAction(Qt.MoveAction)
                        else:
                            event.setDropAction(Qt.CopyAction)
                        self._set_up_btn_highlight(True)
                        self._drag_hovering_up = True
                        if not self._up_hover_timer.isActive():
                            self._up_hover_timer.start()
                        event.accept()
                        return True
                    except Exception:
                        pass
                self._set_up_btn_highlight(False)
                self._drag_hovering_up = False
                self._up_hover_timer.stop()
                event.ignore()
                return True
            if event.type() == QEvent.DragLeave:
                self._set_up_btn_highlight(False)
                self._drag_hovering_up = False
                self._up_hover_timer.stop()
                event.accept()
                return True
            if event.type() == QEvent.Drop:
                self._set_up_btn_highlight(False)
                self._drag_hovering_up = False
                self._up_hover_timer.stop()
                event.ignore()
                return True
        return super().eventFilter(obj, event)

    def _set_up_btn_highlight(self, on: bool):
        if on:
            self.up_btn.setStyleSheet(
                "QPushButton {"
                " background-color: #2f6fa5;"
                " color: white;"
                " border: 1px solid #6fa2d0;"
                " border-radius: 6px;"
                "}"
            )
        else:
            if getattr(self, "_drag_active_faint", False):
                self._apply_up_btn_faint()
            else:
                self.up_btn.setStyleSheet(self._up_btn_default_style)

    def _apply_up_btn_faint(self):
        self.up_btn.setStyleSheet(
            "QPushButton {"
            " background-color: #3a3f48;"
            " color: white;"
            " border: 1px solid #5a6675;"
            " border-radius: 6px;"
            "}"
        )

    def set_up_btn_drag_active(self, active: bool):
        self._drag_active_faint = active
        if active:
            if not self._drag_hovering_up:
                self._apply_up_btn_faint()
        else:
            if not self._drag_hovering_up:
                self.up_btn.setStyleSheet(self._up_btn_default_style)

    def _on_up_hover_timeout(self):
        if self._drag_hovering_up:
            self.navigate_up()
            self._up_hover_timer.start()

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat("application/x-easyadb"):
            try:
                data = json.loads(bytes(e.mimeData().data("application/x-easyadb")).decode("utf-8"))
                if data.get("source") != self.pane_type:
                    e.acceptProposedAction()
                    return
            except Exception:
                pass
        e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        try:
            data = json.loads(bytes(e.mimeData().data("application/x-easyadb")).decode("utf-8"))
            if data.get("source") != self.pane_type:
                data["target_base"] = self.current_path
                self.dropReceived.emit(data)
                e.acceptProposedAction()
                return
        except Exception:
            pass
        e.ignore()

    def set_items(self, items):
        self.table.setRowCount(len(items))
        for row, it in enumerate(items):
            name_item = QTableWidgetItem(it["name"])
            type_item = QTableWidgetItem("目录" if it.get("is_dir") else "文件")
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, type_item)

    def set_path(self, path):
        self.current_path = path
        if isinstance(self.path_edit, QLineEdit):
            self.path_edit.setText(path)
        self.breadcrumb.setPath(path)

    def navigate_to(self, path):
        self.pathChanged.emit(path)

    def navigate_up(self):
        if self.is_posix:
            p = self.current_path if self.current_path else "/"
            parent = posixpath.dirname(p.rstrip("/")) if p != "/" else "/"
            if not parent:
                parent = "/"
            self.navigate_to(parent)
        else:
            p = pathlib.Path(self.current_path)
            parent = str(p.parent) if p.parent != p else self.current_path
            self.navigate_to(parent)

    def return_pressed(self):
        if isinstance(self.path_edit, QLineEdit):
            self.navigate_to(self.path_edit.text().strip())

    def on_double_click(self, row, col):
        name = self.table.item(row, 0).text()
        is_dir = self.table.item(row, 1).text() == "目录"
        if is_dir:
            if self.is_posix:
                new_path = posixpath.join(self.current_path if self.current_path else "/", name)
            else:
                new_path = os.path.join(self.current_path, name)
            self.navigate_to(new_path)
            return
        # file open requested
        if self.pane_type == "local":
            full = os.path.join(self.current_path, name)
            self.fileOpenRequested.emit({"side": "local", "path": full})
        else:
            full = posixpath.join(self.current_path if self.current_path else "/", name)
            self.fileOpenRequested.emit({"side": "remote", "path": full, "name": name})

    def selected_items(self):
        rows = set([i.row() for i in self.table.selectedIndexes()])
        items = []
        for r in rows:
            name = self.table.item(r, 0).text()
            is_dir = self.table.item(r, 1).text() == "目录"
            items.append({"name": name, "is_dir": is_dir})
        return items

    def on_context_menu(self, pos: QPoint):
        row = self.table.rowAt(pos.y())
        menu = QMenu(self)
        # Common actions always available
        act_refresh = QAction("刷新", self)
        act_new_folder = QAction("新建文件夹", self)
        act_new_file = QAction("新建文件", self)
        menu.addAction(act_refresh)
        menu.addAction(act_new_folder)
        menu.addAction(act_new_file)
        # Item-specific actions
        items = []
        if row >= 0:
            if not self.table.selectedIndexes():
                try:
                    self.table.setCurrentCell(row, 0)
                    self.table.selectRow(row)
                except Exception:
                    pass
            items = self.selected_items()
        if items:
            menu.addSeparator()
            act_rename = QAction("重命名", self)
            act_delete = QAction("删除", self)
            if len(items) != 1:
                act_rename.setEnabled(False)
            menu.addAction(act_rename)
            menu.addSeparator()
            menu.addAction(act_delete)
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action is act_refresh:
            self.refreshRequested.emit()
            return
        if action is act_new_folder:
            name, ok = QInputDialog.getText(self, "新建文件夹", "文件夹名称：")
            name = (name or "").strip()
            if ok and name:
                self.newFolderRequested.emit(name)
            return
        if action is act_new_file:
            name, ok = QInputDialog.getText(self, "新建文件", "文件名：")
            name = (name or "").strip()
            if ok and name:
                self.newFileRequested.emit(name)
            return
        if items:
            if action is act_rename and len(items) == 1:
                self.renameRequested.emit(items[0])
            elif action is act_delete:
                self.deleteRequested.emit(items)
