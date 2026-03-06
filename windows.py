import os
import posixpath
import shlex
import shutil
import traceback
import tempfile
from PyQt5.QtCore import Qt, QThread, QTimer, QFileSystemWatcher, QUrl
from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QDockWidget, QTabWidget, QPushButton, QMessageBox, QInputDialog, QAction, QComboBox
from PyQt5.QtGui import QIcon, QDesktopServices
from filepane import FilePane
from transfers import TransferItem
from workers import RemoteListWorker, DeviceListWorker, DeviceConnectWorker
from terminal import ShellTab, open_adb_shell_terminal
from utils import run_cmd


class MainWindow(QMainWindow):
    def __init__(self, serial):
        super().__init__()
        self.setWindowTitle("easyadb")
        self.resize(1920, 1500)
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        menubar = self.menuBar()
        menu_device = menubar.addMenu("设备")
        act_switch = QAction("切换设备", self)
        act_switch.setShortcut("Ctrl+D")
        menu_device.addAction(act_switch)
        menu_tools = menubar.addMenu("工具")
        act_shell_ext = QAction("打开外部终端", self)
        act_shell_ext.setShortcut("Ctrl+O")
        menu_tools.addAction(act_shell_ext)
        self.act_shell_toggle = QAction("显示内嵌终端", self, checkable=True)
        self.act_shell_toggle.setShortcut("Ctrl+E")
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_shell_toggle)
        topbar = QHBoxLayout()
        self.serialLabel = QLabel(f"设备: {serial}", self)
        topbar.addWidget(self.serialLabel)
        self.btnSyncTemp = QPushButton("同步修改", self)
        self.btnSyncTemp.setVisible(False)
        self.btnSyncTemp.setEnabled(False)
        self.btnSyncTemp.clicked.connect(self.sync_temp_changes)
        self._sync_btn_default_style = self.btnSyncTemp.styleSheet()
        topbar.addWidget(self.btnSyncTemp)
        topbar.addStretch(1)
        layout.addLayout(topbar)
        splitter = QSplitter(self)
        self.left = FilePane("本地", is_posix=False, pane_type="local", parent=splitter)
        self.right = FilePane("安卓设备", is_posix=True, pane_type="remote", parent=splitter)
        splitter.addWidget(self.left)
        splitter.addWidget(self.right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self.left.fileOpenRequested.connect(self.on_open_local_file)
        self.right.fileOpenRequested.connect(self.on_open_remote_file)
        self._temp_root = os.path.join(tempfile.gettempdir(), "easyadb_temp", serial or "")
        self._temp_files = set()
        self._temp_watcher = QFileSystemWatcher(self)
        try:
            self._temp_watcher.fileChanged.connect(self._on_temp_file_changed)
        except Exception:
            pass
        transfers_bar = QVBoxLayout()
        self.transfers_container = QWidget(self)
        self.transfers_layout = QVBoxLayout(self.transfers_container)
        self.transfers_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.transfers_container, 0)
        self.current_device = serial or ""
        self.shellDock = QDockWidget("", self)
        self.shellDock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.shellTabs = QTabWidget(self.shellDock)
        self.shellTabs.setTabsClosable(True)
        self.shellTabs.tabCloseRequested.connect(self.on_close_shell_tab)
        corner = QWidget(self.shellTabs)
        corner_lay = QHBoxLayout(corner)
        corner_lay.setContentsMargins(8, 4, 8, 4)
        self.btnNewLocalShell = QPushButton("新建本机终端", corner)
        self.btnNewAndroidShell = QPushButton("新建安卓终端", corner)
        self.btnNewLocalShell.setMinimumHeight(28)
        self.btnNewAndroidShell.setMinimumHeight(28)
        self.btnNewLocalShell.setMinimumWidth(100)
        self.btnNewAndroidShell.setMinimumWidth(100)
        self.btnNewLocalShell.setStyleSheet("QPushButton { padding: 4px 10px; }")
        self.btnNewAndroidShell.setStyleSheet("QPushButton { padding: 4px 10px; }")
        corner_lay.addWidget(self.btnNewLocalShell, 0)
        corner_lay.addWidget(self.btnNewAndroidShell, 0)
        self.shellTabs.setCornerWidget(corner, Qt.TopRightCorner)
        self.shellDock.setWidget(self.shellTabs)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.shellDock)
        self.shellDock.show()
        self.left.pathChanged.connect(self.on_local_path_change)
        self.right.pathChanged.connect(self.on_remote_path_change)
        self.left.dropReceived.connect(self.on_drop_to_local)
        self.right.dropReceived.connect(self.on_drop_to_remote)
        self.left.internalDropReceived.connect(self.on_left_internal_copy)
        self.right.internalDropReceived.connect(self.on_right_internal_copy)
        self.left.deleteRequested.connect(self.on_left_delete)
        self.right.deleteRequested.connect(self.on_right_delete)
        self.left.renameRequested.connect(self.on_left_rename)
        self.right.renameRequested.connect(self.on_right_rename)
        act_switch.triggered.connect(self.switch_device)
        act_shell_ext.triggered.connect(self.open_external_shell)
        self.act_shell_toggle.toggled.connect(self.on_toggle_shell)
        self.btnNewLocalShell.clicked.connect(self.on_new_local_shell)
        self.btnNewAndroidShell.clicked.connect(self.on_new_android_shell)
        self.init_paths()
        self.refresh_remote()
        self.act_shell_toggle.setChecked(True)
        if self.shellTabs.count() == 0:
            self.on_new_android_shell()
        try:
            QTimer.singleShot(0, lambda: self.resizeDocks([self.shellDock], [int(self.height() * 0.35)], Qt.Vertical))
        except Exception:
            pass

    def switch_device(self):
        try:
            if hasattr(self, "_selector") and self._selector is not None:
                try:
                    self._selector.close()
                except Exception:
                    pass
        except Exception:
            pass
        self._selector = DeviceSelectionWindow()
        self._selector.show()
        self.close()

    def open_external_shell(self):
        if self.current_device:
            open_adb_shell_terminal(self.current_device)

    def on_toggle_shell(self, checked):
        if checked:
            self.shellDock.show()
            if self.shellTabs.count() == 0:
                self.on_new_android_shell()
        else:
            self.shellDock.hide()

    def on_new_local_shell(self):
        tab = ShellTab(self.current_device, self.shellTabs, mode="local")
        idx = self.shellTabs.addTab(tab, f"local-{self.shellTabs.count()+1}")
        self.shellTabs.setCurrentIndex(idx)
        tab.start()
        if not self.shellDock.isVisible():
            self.shellDock.show()
            self.act_shell_toggle.setChecked(True)

    def on_new_android_shell(self):
        if not self.current_device:
            return
        tab = ShellTab(self.current_device, self.shellTabs, mode="android")
        idx = self.shellTabs.addTab(tab, f"android-{self.shellTabs.count()+1}")
        self.shellTabs.setCurrentIndex(idx)
        tab.start()
        if not self.shellDock.isVisible():
            self.shellDock.show()
            self.act_shell_toggle.setChecked(True)

    def on_close_shell_tab(self, idx):
        w = self.shellTabs.widget(idx)
        try:
            if isinstance(w, ShellTab):
                w.stop()
        except Exception:
            pass
        self.shellTabs.removeTab(idx)
        if self.shellTabs.count() == 0:
            self.shellDock.hide()
            self.act_shell_toggle.setChecked(False)
            try:
                QTimer.singleShot(300, self.refresh_remote)
            except Exception:
                try:
                    self.refresh_remote()
                except Exception:
                    pass

    def closeEvent(self, e):
        try:
            for i in range(self.shellTabs.count()):
                w = self.shellTabs.widget(i)
                try:
                    w.stop()
                except Exception:
                    pass
        except Exception:
            pass
        super().closeEvent(e)

    def init_paths(self):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.left.set_path(desktop)
        self.refresh_local()
        self.right.set_path("/")
        self.refresh_remote()

    def on_local_path_change(self, path):
        p = os.path.abspath(path)
        if os.path.isdir(p):
            self.left.set_path(p)
            self.refresh_local()

    def on_remote_path_change(self, path):
        p = path if path else "/"
        self.right.set_path(p)
        self.refresh_remote()

    def refresh_local(self):
        path = self.left.current_path
        items = []
        try:
            for name in os.listdir(path):
                full = os.path.join(path, name)
                items.append({"name": name, "is_dir": os.path.isdir(full)})
        except Exception:
            items = []
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        self.left.set_items(items)

    def refresh_remote(self):
        if not self.current_device:
            try:
                self.right.header.setText("安卓设备 (未连接)")
            except Exception:
                pass
            self.right.set_items([])
            return
        try:
            self.right.header.setText("安卓设备 (加载中…)")
            self.right.set_items([{"name": "加载中…", "is_dir": False}])
        except Exception:
            pass
        path = self.right.current_path if self.right.current_path else "/"
        self._remote_list_thread = QThread(self)
        self._remote_list_worker = RemoteListWorker(self.current_device, path)
        self._remote_list_worker.moveToThread(self._remote_list_thread)
        self._remote_list_thread.started.connect(self._remote_list_worker.run)
        self._remote_list_worker.finished.connect(self._on_remote_list_ready)
        self._remote_list_worker.finished.connect(self._remote_list_thread.quit)
        self._remote_list_worker.finished.connect(self._remote_list_worker.deleteLater)
        self._remote_list_thread.finished.connect(self._remote_list_thread.deleteLater)
        self._remote_list_thread.start()

    def _on_remote_list_ready(self, serial, path, items):
        try:
            if serial != self.current_device:
                return
            current = self.right.current_path if self.right.current_path else "/"
            if path != current:
                return
            self.right.set_items(items)
            try:
                self.right.header.setText("安卓设备")
            except Exception:
                pass
        except Exception:
            pass

    def on_drop_to_local(self, data):
        if not self.current_device:
            return
        items = data.get("items", [])
        src_base = data.get("base", "/")
        dst_base = self.left.current_path
        self.start_transfer("remote_to_local", items, src_base, dst_base)

    def on_drop_to_remote(self, data):
        if not self.current_device:
            return
        items = data.get("items", [])
        src_base = data.get("base", "")
        dst_base = self.right.current_path if self.right.current_path else "/"
        self.start_transfer("local_to_remote", items, src_base, dst_base)

    def on_left_internal_copy(self, data):
        items = data.get("items", [])
        src_base = data.get("base", self.left.current_path)
        target_base = data.get("target_base", self.left.current_path)
        target_dir = data.get("target_dir")
        dst_base = os.path.join(target_base, target_dir) if target_dir else target_base
        if os.path.abspath(src_base) == os.path.abspath(dst_base):
            return
        self.start_transfer("local_to_local", items, src_base, dst_base)

    def on_right_internal_copy(self, data):
        if not self.current_device:
            return
        items = data.get("items", [])
        src_base = data.get("base", self.right.current_path if self.right.current_path else "/")
        target_base = data.get("target_base", self.right.current_path if self.right.current_path else "/")
        target_dir = data.get("target_dir")
        dst_base = posixpath.join(target_base, target_dir) if target_dir else target_base
        if src_base == dst_base:
            return
        self.start_transfer("remote_to_remote", items, src_base, dst_base)

    def start_transfer(self, direction, items, src_base, dst_base):
        t = TransferItem(direction, items, src_base, dst_base, self.current_device, parent=self)
        self.transfers_layout.addWidget(t)
        t.start()
        t.finishedSignal.connect(lambda d=direction, w=t: self._cleanup_transfer(w, d))

    def _cleanup_transfer(self, widget, direction):
        try:
            self.transfers_layout.removeWidget(widget)
        except Exception:
            pass
        try:
            widget.deleteLater()
        except Exception:
            pass
        if direction in ("local_to_remote", "remote_to_remote"):
            self.refresh_remote()
        else:
            self.refresh_local()
        if direction == "local_to_remote" and getattr(self, "_syncing_temp", False):
            try:
                self._temp_watcher.removePaths(self._temp_watcher.files())
            except Exception:
                pass
            self._temp_files.clear()
            try:
                shutil.rmtree(self._temp_root, ignore_errors=True)
            except Exception:
                pass
            self.btnSyncTemp.setEnabled(False)
            self.btnSyncTemp.setVisible(False)
            self.btnSyncTemp.setStyleSheet(self._sync_btn_default_style)
            self._syncing_temp = False
        if direction in ("local_to_remote", "remote_to_remote"):
            try:
                self.right.table.setFocus(Qt.OtherFocusReason)
            except Exception:
                pass
        else:
            try:
                self.left.table.setFocus(Qt.OtherFocusReason)
            except Exception:
                pass

    def _is_text_name(self, name: str) -> bool:
        ext = os.path.splitext(name.lower())[1]
        text_exts = {
            ".txt", ".log", ".json", ".xml", ".yaml", ".yml", ".csv", ".ini", ".conf",
            ".cfg", ".prop", ".properties", ".sh", ".bash", ".zsh", ".py", ".js",
            ".ts", ".java", ".gradle", ".md", ".html", ".htm", ".css", ".rb", ".php"
        }
        return ext in text_exts or ext == ""

    def _ensure_temp_dir_for(self, remote_path: str) -> str:
        rel = remote_path.lstrip("/").replace("/", os.sep)
        local_path = os.path.join(self._temp_root, rel)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        return local_path

    def _watch_temp_file(self, path: str):
        if not os.path.isfile(path):
            return
        if path not in self._temp_files:
            self._temp_files.add(path)
            try:
                self._temp_watcher.addPath(path)
            except Exception:
                pass

    def _on_temp_file_changed(self, path: str):
        try:
            self.btnSyncTemp.setVisible(True)
            self.btnSyncTemp.setEnabled(True)
            self.btnSyncTemp.setStyleSheet(
                "QPushButton {"
                " background-color: #2f6fa5;"
                " color: white;"
                " border: 1px solid #6fa2d0;"
                " border-radius: 6px;"
                "}"
            )
        except Exception:
            pass

    def on_open_local_file(self, info: dict):
        p = info.get("path")
        if not p or not os.path.exists(p):
            return
        try:
            if os.name == "nt":
                os.startfile(p)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
        except Exception:
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            except Exception:
                pass

    def on_open_remote_file(self, info: dict):
        if not self.current_device:
            return
        remote_path = info.get("path")
        name = info.get("name") or (posixpath.basename(remote_path) if remote_path else "")
        if not remote_path or not name:
            return
        if not self._is_text_name(name):
            QMessageBox.information(self, "无法打开", "该文件不是文本类型，无法用文本编辑方式打开。")
            return
        local_path = self._ensure_temp_dir_for(remote_path)
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
        except Exception:
            pass
        rc, out, err = run_cmd(["adb", "-s", self.current_device, "pull", remote_path, local_path], timeout=60)
        if rc != 0:
            QMessageBox.warning(self, "拉取失败", err or out or "未知错误")
            return
        self._watch_temp_file(local_path)
        try:
            if os.name == "nt":
                os.startfile(local_path)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(local_path))
        except Exception:
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(local_path))
            except Exception:
                pass

    def sync_temp_changes(self):
        if not self.current_device:
            return
        root = self._temp_root
        if not os.path.isdir(root):
            self.btnSyncTemp.setEnabled(False)
            self.btnSyncTemp.setVisible(False)
            try:
                self.btnSyncTemp.setStyleSheet(self._sync_btn_default_style)
            except Exception:
                pass
            try:
                self.right.table.setFocus(Qt.OtherFocusReason)
            except Exception:
                pass
            return
        try:
            names = os.listdir(root)
        except Exception:
            names = []
        items = []
        for n in names:
            full = os.path.join(root, n)
            items.append({"name": n, "is_dir": os.path.isdir(full)})
        if not items:
            self.btnSyncTemp.setEnabled(False)
            self.btnSyncTemp.setVisible(False)
            try:
                self.btnSyncTemp.setStyleSheet(self._sync_btn_default_style)
            except Exception:
                pass
            try:
                self.right.table.setFocus(Qt.OtherFocusReason)
            except Exception:
                pass
            return
        self._syncing_temp = True
        self.start_transfer("local_to_remote", items, root, "/")

    def on_left_delete(self, items):
        if not items:
            return
        names = ", ".join([i["name"] for i in items])
        ret = QMessageBox.question(self, "确认删除", f"确定删除所选项：{names}？该操作不可恢复。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        base = self.left.current_path
        for it in items:
            p = os.path.join(base, it["name"])
            try:
                if it.get("is_dir"):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    if os.path.exists(p):
                        os.remove(p)
            except Exception as e:
                print("本地删除失败:", p, e)
                traceback.print_exc()
        self.refresh_local()

    def on_right_delete(self, items):
        if not self.current_device or not items:
            return
        names = ", ".join([i["name"] for i in items])
        ret = QMessageBox.question(self, "确认删除", f"确定删除所选项：{names}？该操作不可恢复。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        base = self.right.current_path if self.right.current_path else "/"
        for it in items:
            p = posixpath.join(base, it["name"])
            cmd = f"rm -rf {shlex.quote(p)}"
            code, out, err = run_cmd(["adb", "-s", self.current_device, "shell", cmd], timeout=60)
            if code != 0:
                print("远端删除失败:", p, err or out)
        self.refresh_remote()

    def on_left_rename(self, item):
        base = self.left.current_path
        old_name = item["name"]
        new_name, ok = QInputDialog.getText(self, "重命名", f"将 {old_name} 重命名为：", text=old_name)
        if not ok or not new_name or new_name == old_name:
            return
        old_path = os.path.join(base, old_name)
        new_path = os.path.join(base, new_name)
        try:
            os.rename(old_path, new_path)
        except Exception as e:
            print("本地重命名失败:", old_path, "->", new_path, e)
            traceback.print_exc()
        self.refresh_local()

    def on_right_rename(self, item):
        if not self.current_device:
            return
        base = self.right.current_path if self.right.current_path else "/"
        old_name = item["name"]
        new_name, ok = QInputDialog.getText(self, "重命名", f"将 {old_name} 重命名为：", text=old_name)
        if not ok or not new_name or new_name == old_name:
            return
        old_path = posixpath.join(base, old_name)
        new_path = posixpath.join(base, new_name)
        cmd = f"mv {shlex.quote(old_path)} {shlex.quote(new_path)}"
        code, out, err = run_cmd(["adb", "-s", self.current_device, "shell", cmd], timeout=30)
        if code != 0:
            print("远端重命名失败:", old_path, "->", new_path, err or out)
        self.refresh_remote()


class DeviceSelectionWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("选择设备")
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "ad.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        row = QHBoxLayout()
        label = QLabel("设备")
        self.combo = QComboBox(self)
        self.refresh_btn = QPushButton("刷新", self)
        self.connect_btn = QPushButton("连接", self)
        row.addWidget(label)
        row.addWidget(self.combo, 1)
        row.addWidget(self.refresh_btn, 0)
        layout.addLayout(row)
        layout.addStretch(1)
        self.status_label = QLabel("", self)
        layout.addWidget(self.status_label, 0, Qt.AlignLeft)
        layout.addWidget(self.connect_btn, 0, Qt.AlignRight)
        self.refresh_btn.clicked.connect(self.populate)
        self.connect_btn.clicked.connect(self.on_connect)
        self._list_thread = None
        self._list_worker = None
        self._connect_thread = None
        self._connect_worker = None
        self.populate()

    def populate(self):
        try:
            self.refresh_btn.setEnabled(False)
        except Exception:
            pass
        self.combo.clear()
        try:
            self.combo.addItem("扫描中…")
        except Exception:
            pass
        try:
            if self._list_thread and self._list_thread.isRunning():
                return
        except Exception:
            pass
        self._list_thread = QThread(self)
        self._list_worker = DeviceListWorker()
        self._list_worker.moveToThread(self._list_thread)
        self._list_thread.started.connect(self._list_worker.run)
        self._list_worker.finished.connect(self._on_devices_ready)
        self._list_worker.finished.connect(self._list_thread.quit)
        self._list_worker.finished.connect(self._list_worker.deleteLater)
        self._list_thread.finished.connect(self._list_thread.deleteLater)
        self._list_thread.start()

    def on_connect(self):
        serial = self.combo.currentText().strip()
        if not serial:
            QMessageBox.warning(self, "提示", "请先选择一个设备")
            return
        try:
            if self._connect_thread and self._connect_thread.isRunning():
                return
        except Exception:
            pass
        try:
            self.connect_btn.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self.status_label.setText("连接中…")
        except Exception:
            pass
        self._connect_thread = QThread(self)
        self._connect_worker = DeviceConnectWorker(serial)
        self._connect_worker.moveToThread(self._connect_thread)
        self._connect_thread.started.connect(self._connect_worker.run)
        self._connect_worker.finished.connect(self._on_connect_finished)
        self._connect_worker.finished.connect(self._connect_thread.quit)
        self._connect_worker.finished.connect(self._connect_worker.deleteLater)
        self._connect_thread.finished.connect(self._connect_thread.deleteLater)
        self._connect_thread.start()
    def _on_devices_ready(self, devs):
        try:
            self.combo.clear()
            for d in devs:
                self.combo.addItem(d)
        except Exception:
            pass
        try:
            self.refresh_btn.setEnabled(True)
        except Exception:
            pass
    def _on_connect_finished(self, ok, serial, msg, items):
        try:
            self.status_label.setText("" if ok else (msg or "连接失败"))
            self.connect_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
        except Exception:
            pass
        if ok:
            w = MainWindow(serial)
            w.show()
            try:
                w.right.set_path("/")
                w.right.set_items(items or [])
                w.right.header.setText("安卓设备")
            except Exception:
                pass
            self._child = w
            self.close()
