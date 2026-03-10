import os
import posixpath
import shlex
import shutil
import traceback
import tempfile
from PyQt5.QtCore import Qt, QThread, QTimer, QFileSystemWatcher, QUrl
from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QDockWidget, QTabWidget, QPushButton, QMessageBox, QInputDialog, QAction, QComboBox, QListWidget, QLineEdit, QDialog, QMenu, QListWidgetItem
from PyQt5.QtGui import QIcon, QDesktopServices, QGuiApplication, QFont
from filepane import FilePane
from transfers import TransferItem
from workers import RemoteListWorker, DeviceListWorker, DeviceConnectWorker
from terminal import ShellTab, open_adb_shell_terminal, GLOBAL_HISTORY, bus
from utils import run_cmd


class MainWindow(QMainWindow):
    def __init__(self, serial):
        super().__init__()
        self.setWindowTitle("easyadb")
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            w = min(int(geo.width() * 0.55), 1200)
            h = min(int(geo.height() * 0.65), 820)
            self.resize(max(800, w), max(560, h))
        else:
            self.resize(1000, 700)
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        menubar = self.menuBar()
        menu_device = menubar.addMenu(serial or "设备")
        act_switch = QAction("切换设备", self)
        act_switch.setShortcut("Ctrl+D")
        menu_device.addAction(act_switch)
        menu_tools = menubar.addMenu("视图")
        act_shell_ext = QAction("打开外部终端", self)
        act_shell_ext.setShortcut("Ctrl+O")
        menu_tools.addAction(act_shell_ext)
        self.act_shell_toggle = QAction("显示内嵌终端", self, checkable=True)
        self.act_shell_toggle.setShortcut("Ctrl+E")
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_shell_toggle)
        self.act_commands_toggle = QAction("显示常用指令", self, checkable=True)
        self.act_commands_toggle.setShortcut("Ctrl+L")
        menu_tools.addAction(self.act_commands_toggle)
        device_corner = QWidget(menubar)
        device_corner_lay = QHBoxLayout(device_corner)
        device_corner_lay.setContentsMargins(8, 0, 8, 0)
        device_corner_lay.setSpacing(6)
        self.btnSyncTemp = QPushButton("同步修改", device_corner)
        self.btnSyncTemp.setFont(QFont("", 10))
        self.btnSyncTemp.setVisible(True)
        self.btnSyncTemp.setEnabled(False)
        self.btnSyncTemp.clicked.connect(self.sync_temp_changes)
        self._sync_btn_default_style = self.btnSyncTemp.styleSheet()
        device_corner_lay.addWidget(self.btnSyncTemp, 0)
        try:
            menubar.setCornerWidget(device_corner, Qt.TopRightCorner)
        except Exception:
            pass
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
        self.btnNewLocalShell.setFont(QFont("", 10))
        self.btnNewAndroidShell.setFont(QFont("", 10))
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
        self.left.newFolderRequested.connect(self.on_left_new_folder)
        self.left.newFileRequested.connect(self.on_left_new_file)
        self.right.newFolderRequested.connect(self.on_right_new_folder)
        self.right.newFileRequested.connect(self.on_right_new_file)
        self.left.refreshRequested.connect(self.refresh_local)
        self.right.refreshRequested.connect(self.refresh_remote)
        act_switch.triggered.connect(self.switch_device)
        act_shell_ext.triggered.connect(self.open_external_shell)
        self.act_shell_toggle.toggled.connect(self.on_toggle_shell)
        self.btnNewLocalShell.clicked.connect(self.on_new_local_shell)
        self.btnNewAndroidShell.clicked.connect(self.on_new_android_shell)
        self.commandsDock = QDockWidget("常用指令", self)
        self.commandsDock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.commandsWidget = CommonCommandsWidget(self, self.commandsDock)
        self.commandsDock.setWidget(self.commandsWidget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.commandsDock)
        self.commandsDock.show()
        self.init_paths()
        self.refresh_remote()
        self.act_shell_toggle.setChecked(True)
        if self.shellTabs.count() == 0:
            self.on_new_android_shell()
        try:
            QTimer.singleShot(0, lambda: self.resizeDocks([self.shellDock], [int(self.height() * 0.35)], Qt.Vertical))
        except Exception:
            pass
        self.act_commands_toggle.toggled.connect(self.on_toggle_commands)
        try:
            self.act_commands_toggle.setChecked(True)
        except Exception:
            pass
        try:
            self.shellDock.visibilityChanged.connect(lambda v: self.act_shell_toggle.setChecked(v))
            self.commandsDock.visibilityChanged.connect(lambda v: self.act_commands_toggle.setChecked(v))
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
    def on_toggle_commands(self, checked):
        if checked:
            self.commandsDock.show()
        else:
            self.commandsDock.hide()

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
            ".txt", ".log",
            ".json", ".xml", ".yaml", ".yml", ".toml",
            ".csv", ".ini", ".conf", ".cfg", ".config", ".env",
            ".prop", ".properties",
            ".md", ".markdown",
            ".html", ".htm", ".css",
            ".py", ".pyw",
            ".js", ".ts", ".jsx", ".tsx",
            ".java", ".gradle", ".groovy",
            ".rb", ".php", ".pl", ".pm", ".lua",
            ".c", ".h", ".hpp", ".hh", ".hxx",
            ".cc", ".cpp", ".cxx",
            ".m", ".mm", ".swift",
            ".go", ".rs", ".kt", ".kts", ".scala",
            ".sql",
            ".sh", ".bash", ".zsh",
            ".ps1", ".psm1", ".bat", ".cmd",
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
            self.btnSyncTemp.setVisible(True)
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

    def on_left_new_folder(self, name: str):
        if not name or any(c in name for c in ("/", "\\")):
            QMessageBox.warning(self, "提示", "名称不合法")
            return
        base = self.left.current_path
        p = os.path.join(base, name)
        if os.path.exists(p):
            QMessageBox.warning(self, "提示", "已存在同名文件或文件夹")
            return
        try:
            os.makedirs(p, exist_ok=False)
        except Exception as e:
            QMessageBox.warning(self, "创建失败", str(e))
            return
        self.refresh_local()

    def on_left_new_file(self, name: str):
        if not name or any(c in name for c in ("/", "\\")):
            QMessageBox.warning(self, "提示", "名称不合法")
            return
        base = self.left.current_path
        p = os.path.join(base, name)
        if os.path.exists(p):
            QMessageBox.warning(self, "提示", "已存在同名文件或文件夹")
            return
        try:
            with open(p, "a", encoding="utf-8"):
                pass
        except Exception as e:
            QMessageBox.warning(self, "创建失败", str(e))
            return
        self.refresh_local()

    def on_right_new_folder(self, name: str):
        if not self.current_device:
            QMessageBox.information(self, "提示", "当前未连接设备")
            return
        if not name or "/" in name or "\\" in name:
            QMessageBox.warning(self, "提示", "名称不合法")
            return
        base = self.right.current_path if self.right.current_path else "/"
        p = posixpath.join(base, name)
        cmd = f"mkdir -p {shlex.quote(p)}"
        code, out, err = run_cmd(["adb", "-s", self.current_device, "shell", cmd], timeout=30)
        if code != 0:
            QMessageBox.warning(self, "创建失败", err or out or "未知错误")
            return
        self.refresh_remote()

    def on_right_new_file(self, name: str):
        if not self.current_device:
            QMessageBox.information(self, "提示", "当前未连接设备")
            return
        if not name or "/" in name or "\\" in name:
            QMessageBox.warning(self, "提示", "名称不合法")
            return
        base = self.right.current_path if self.right.current_path else "/"
        p = posixpath.join(base, name)
        cmd = f"touch {shlex.quote(p)}"
        code, out, err = run_cmd(["adb", "-s", self.current_device, "shell", cmd], timeout=30)
        if code != 0:
            QMessageBox.warning(self, "创建失败", err or out or "未知错误")
            return
        self.refresh_remote()


class CommonCommandsWidget(QWidget):
    def __init__(self, main, parent=None):
        super().__init__(parent)
        self.main = main
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.tabs.setTabPosition(QTabWidget.North)
        layout.addWidget(self.tabs, 1)
        saved_container = QWidget(self)
        saved_lay = QVBoxLayout(saved_container)
        saved_top = QHBoxLayout()
        self.btnAddSmall = QPushButton("添加", saved_container)
        self.btnAddSmall.setFont(QFont("", 10))
        saved_top.addWidget(self.btnAddSmall, 0)
        saved_top.addStretch(1)
        saved_lay.addLayout(saved_top)
        self.savedList = QListWidget(saved_container)
        self.savedList.setFont(QFont("", 10))
        self.savedList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.savedList.customContextMenuRequested.connect(self.on_saved_context_menu)
        saved_lay.addWidget(self.savedList, 1)
        self.tabs.addTab(saved_container, "自定义")
        history_container = QWidget(self)
        history_lay = QVBoxLayout(history_container)
        self.historyList = QListWidget(history_container)
        self.historyList.setFont(QFont("", 10))
        self.historyList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.historyList.customContextMenuRequested.connect(self.on_history_context_menu)
        history_lay.addWidget(self.historyList, 1)
        self.tabs.addTab(history_container, "历史")
        self.savedList.itemDoubleClicked.connect(lambda _: self.on_run_from_list(self.savedList))
        self.historyList.itemDoubleClicked.connect(lambda _: self.on_run_from_list(self.historyList))
        self.btnAddSmall.clicked.connect(self.on_add)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self._saved_items = []
        self._refresh_saved_list()
        self._refresh_history_list()
        self._last_shell = None
        try:
            self.main.shellTabs.currentChanged.connect(self._on_shell_tab_changed)
        except Exception:
            pass
        self._connect_shell_history()
        try:
            bus.historyChanged.connect(self._refresh_history_if_active)
        except Exception:
            pass
    def on_add(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("添加常用指令")
        v = QVBoxLayout(dlg)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("标题"))
        title_edit = QLineEdit(dlg)
        title_edit.setFont(QFont("", 10))
        row1.addWidget(title_edit, 1)
        v.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("指令"))
        cmd_edit = QLineEdit(dlg)
        cmd_edit.setFont(QFont("", 10))
        row2.addWidget(cmd_edit, 1)
        v.addLayout(row2)
        row3 = QHBoxLayout()
        btn_ok = QPushButton("确定", dlg)
        btn_ok.setFont(QFont("", 10))
        btn_cancel = QPushButton("取消", dlg)
        btn_cancel.setFont(QFont("", 10))
        row3.addStretch(1)
        row3.addWidget(btn_ok)
        row3.addWidget(btn_cancel)
        v.addLayout(row3)
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        try:
            cmd_edit.setFocus()
        except Exception:
            pass
        if dlg.exec() == QDialog.Accepted:
            title = title_edit.text().strip()
            cmd = cmd_edit.text().strip()
            if not cmd:
                return
            if not title:
                title = cmd
            self._saved_items.append((title, cmd))
            self._refresh_saved_list()
    def on_run_from_list(self, which):
        it = which.currentItem()
        if not it:
            return
        cmd = (it.data(Qt.UserRole) or "").strip()
        if not cmd:
            return
        tab = None
        try:
            cw = self.main.shellTabs.currentWidget()
            if isinstance(cw, ShellTab):
                tab = cw
        except Exception:
            tab = None
        if tab is None:
            try:
                self.main.on_new_android_shell()
                cw = self.main.shellTabs.currentWidget()
                if isinstance(cw, ShellTab):
                    tab = cw
            except Exception:
                tab = None
        if tab is None:
            QMessageBox.information(self, "提示", "未找到可用终端")
            return
        try:
            tab.send_command(cmd)
            try:
                if not self.main.shellDock.isVisible():
                    self.main.shellDock.show()
                    self.main.act_shell_toggle.setChecked(True)
            except Exception:
                pass
            try:
                self.main.shellTabs.setCurrentWidget(tab)
            except Exception:
                pass
            try:
                QTimer.singleShot(100, lambda: (tab.view.setFocus(), tab.view.moveCursor(tab.view.textCursor().End), tab.view.ensureCursorVisible()))
            except Exception:
                pass
        except Exception:
            QMessageBox.warning(self, "执行失败", "指令发送失败")
    def on_saved_context_menu(self, pos):
        idx = self.savedList.indexAt(pos)
        item = self.savedList.item(idx.row()) if idx.isValid() else None
        if not item:
            return
        m = QMenu(self)
        act_edit = QAction("编辑", self)
        act_del = QAction("删除", self)
        m.addAction(act_edit)
        m.addSeparator()
        m.addAction(act_del)
        a = m.exec(self.savedList.viewport().mapToGlobal(pos))
        if a and a.text() == "删除":
            self.savedList.takeItem(self.savedList.row(item))
            try:
                txt = item.text()
                self._saved_items = [(t, c) for (t, c) in self._saved_items if t != txt]
            except Exception:
                pass
            return
        if a and a.text() == "编辑":
            self._edit_item(item)
    def _edit_item(self, item: QListWidgetItem):
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑常用指令")
        v = QVBoxLayout(dlg)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("标题"))
        title_edit = QLineEdit(dlg)
        title_edit.setFont(QFont("", 10))
        title_edit.setText(item.text())
        row1.addWidget(title_edit, 1)
        v.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("指令"))
        cmd_edit = QLineEdit(dlg)
        cmd_edit.setFont(QFont("", 10))
        cmd_edit.setText(item.data(Qt.UserRole) or "")
        row2.addWidget(cmd_edit, 1)
        v.addLayout(row2)
        row3 = QHBoxLayout()
        btn_ok = QPushButton("确定", dlg)
        btn_ok.setFont(QFont("", 10))
        btn_cancel = QPushButton("取消", dlg)
        btn_cancel.setFont(QFont("", 10))
        row3.addStretch(1)
        row3.addWidget(btn_ok)
        row3.addWidget(btn_cancel)
        v.addLayout(row3)
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        try:
            cmd_edit.setFocus()
        except Exception:
            pass
        if dlg.exec() == QDialog.Accepted:
            title = title_edit.text().strip()
            cmd = cmd_edit.text().strip()
            if not cmd:
                return
            if not title:
                title = cmd
            item.setText(title)
            item.setData(Qt.UserRole, cmd)
            # 更新保存集合
            try:
                found = False
                for i, (t, c) in enumerate(self._saved_items):
                    if t == title or t == item.text():
                        self._saved_items[i] = (title, cmd)
                        found = True
                        break
                if not found:
                    self._saved_items.append((title, cmd))
            except Exception:
                pass
    def _refresh_saved_list(self):
        try:
            self.savedList.clear()
            for title, cmd in self._saved_items:
                it = QListWidgetItem(title)
                it.setData(Qt.UserRole, cmd)
                self.savedList.addItem(it)
        except Exception:
            pass
    def _refresh_history_list(self):
        try:
            self.historyList.clear()
            hist = list(GLOBAL_HISTORY)
            hist = hist[-30:]
            for cmd in reversed(hist):
                it = QListWidgetItem(cmd)
                it.setData(Qt.UserRole, cmd)
                self.historyList.addItem(it)
        except Exception:
            pass
    def _on_shell_tab_changed(self, idx):
        self._connect_shell_history()
        if self.tabs.currentIndex() == 1:
            self._refresh_history_list()
    def _connect_shell_history(self):
        try:
            cw = self.main.shellTabs.currentWidget()
            if self._last_shell is cw:
                return
            self._last_shell = cw
            if isinstance(cw, ShellTab):
                cw.historyChanged.connect(self._refresh_history_if_active)
        except Exception:
            pass
    def _refresh_history_if_active(self):
        try:
            if self.tabs.currentIndex() == 1:
                self._refresh_history_list()
        except Exception:
            pass
    def on_history_context_menu(self, pos):
        idx = self.historyList.indexAt(pos)
        item = self.historyList.item(idx.row()) if idx.isValid() else None
        if not item:
            return
        m = QMenu(self)
        act_bind = QAction("绑定为新指令", self)
        m.addAction(act_bind)
        a = m.exec(self.historyList.viewport().mapToGlobal(pos))
        if a and a.text() == "绑定为新指令":
            self._bind_history_item(item)
    def _bind_history_item(self, item: QListWidgetItem):
        cmd_prefill = (item.data(Qt.UserRole) or "").strip()
        if not cmd_prefill:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("添加常用指令")
        v = QVBoxLayout(dlg)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("标题"))
        title_edit = QLineEdit(dlg)
        title_edit.setFont(QFont("", 10))
        row1.addWidget(title_edit, 1)
        v.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("指令"))
        cmd_edit = QLineEdit(dlg)
        cmd_edit.setFont(QFont("", 10))
        cmd_edit.setText(cmd_prefill)
        row2.addWidget(cmd_edit, 1)
        v.addLayout(row2)
        row3 = QHBoxLayout()
        btn_ok = QPushButton("确定", dlg)
        btn_ok.setFont(QFont("", 10))
        btn_cancel = QPushButton("取消", dlg)
        btn_cancel.setFont(QFont("", 10))
        row3.addStretch(1)
        row3.addWidget(btn_ok)
        row3.addWidget(btn_cancel)
        v.addLayout(row3)
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        try:
            cmd_edit.setFocus()
        except Exception:
            pass
        if dlg.exec() == QDialog.Accepted:
            title = title_edit.text().strip()
            cmd = cmd_edit.text().strip()
            if not cmd:
                return
            if not title:
                title = cmd
            self._saved_items.append((title, cmd))
            try:
                self.tabs.setCurrentIndex(0)
            except Exception:
                pass
            self._refresh_saved_list()
    def on_tab_changed(self, idx):
        if idx == 0:
            self._refresh_saved_list()
        else:
            self._refresh_history_list()


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
        label.setFont(QFont("", 10))
        self.combo = QComboBox(self)
        self.combo.setFont(QFont("", 10))
        self.refresh_btn = QPushButton("刷新", self)
        self.refresh_btn.setFont(QFont("", 10))
        self.connect_btn = QPushButton("连接", self)
        self.connect_btn.setFont(QFont("", 10))
        row.addWidget(label)
        row.addWidget(self.combo, 1)
        row.addWidget(self.refresh_btn, 0)
        layout.addLayout(row)
        layout.addStretch(1)
        self.status_label = QLabel("", self)
        self.status_label.setFont(QFont("", 10))
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
