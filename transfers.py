import os
import shutil
import subprocess
import traceback
import posixpath
import shlex
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QLabel, QProgressBar, QPushButton, QHBoxLayout, QFrame
from utils import ensure_remote_dir, remote_find_files, run_cmd


class CopyWorkerSignals(QWidget):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    canceled = pyqtSignal()


class CopyWorker(QFrame):
    def __init__(self, direction, items, src_base, dst_base, serial, parent=None):
        super().__init__(parent)
        self.direction = direction
        self.items = items
        self.src_base = src_base
        self.dst_base = dst_base
        self.serial = serial
        self.signals = CopyWorkerSignals()
        self._stop = False
        self._current_proc = None

    def stop(self):
        self._stop = True
        if self._current_proc:
            try:
                self._current_proc.terminate()
            except Exception:
                pass

    def run(self):
        try:
            if self.direction == "local_to_remote":
                tasks = []
                for it in self.items:
                    name = it["name"]
                    src_path = os.path.join(self.src_base, name)
                    if it.get("is_dir"):
                        for root, _, files in os.walk(src_path):
                            rel = os.path.relpath(root, src_path)
                            remote_dir = posixpath.join(self.dst_base, name) if rel == "." else posixpath.join(self.dst_base, name, rel.replace("\\", "/"))
                            ensure_remote_dir(self.serial, remote_dir)
                            for f in files:
                                local_file = os.path.join(root, f)
                                remote_file = posixpath.join(remote_dir, f)
                                tasks.append(("push", local_file, remote_file))
                    else:
                        remote_file = posixpath.join(self.dst_base, name)
                        ensure_remote_dir(self.serial, posixpath.dirname(remote_file))
                        tasks.append(("push", src_path, remote_file))
                total = max(len(tasks), 1)
                done = 0
                for typ, src, dst in tasks:
                    if self._stop:
                        self.signals.canceled.emit()
                        return
                    self.signals.progress.emit(done, total, f"上传 {os.path.basename(src)}")
                    self._current_proc = subprocess.Popen(["adb", "-s", self.serial, "push", src, dst], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    out, err = self._current_proc.communicate()
                    rc = self._current_proc.returncode
                    self._current_proc = None
                    if rc != 0:
                        self.signals.error.emit(f"push 失败: {src} -> {dst} :: {(err or out).decode('utf-8','ignore') if isinstance(err, (bytes, bytearray)) else (err or out)}")
                        return
                    done += 1
                    self.signals.progress.emit(done, total, f"上传完成 {os.path.basename(src)}")
            elif self.direction == "remote_to_local":
                tasks = []
                for it in self.items:
                    name = it["name"]
                    remote_path = posixpath.join(self.src_base if self.src_base else "/", name) if self.src_base else name
                    if it.get("is_dir"):
                        files = remote_find_files(self.serial, remote_path)
                        for f in files:
                            remote_file = posixpath.join(remote_path, f)
                            local_file = os.path.join(self.dst_base, name, f.replace("/", os.sep))
                            tasks.append(("pull", remote_file, local_file))
                    else:
                        local_file = os.path.join(self.dst_base, name)
                        tasks.append(("pull", remote_path, local_file))
                total = max(len(tasks), 1)
                done = 0
                for typ, src, dst in tasks:
                    if self._stop:
                        self.signals.canceled.emit()
                        return
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    self.signals.progress.emit(done, total, f"下载 {os.path.basename(dst)}")
                    self._current_proc = subprocess.Popen(["adb", "-s", self.serial, "pull", src, dst], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    out, err = self._current_proc.communicate()
                    rc = self._current_proc.returncode
                    self._current_proc = None
                    if rc != 0:
                        self.signals.error.emit(f"pull 失败: {src} -> {dst} :: {(err or out).decode('utf-8','ignore') if isinstance(err, (bytes, bytearray)) else (err or out)}")
                        return
                    done += 1
                    self.signals.progress.emit(done, total, f"下载完成 {os.path.basename(dst)}")
            elif self.direction == "local_to_local":
                tasks = []
                for it in self.items:
                    name = it["name"]
                    src_path = os.path.join(self.src_base, name)
                    dst_path = os.path.join(self.dst_base, name)
                    if it.get("is_dir"):
                        try:
                            src_real = os.path.realpath(src_path)
                            dst_real = os.path.realpath(dst_path)
                            if os.path.commonpath([dst_real, src_real]) == src_real:
                                self.signals.error.emit(f"不能将目录移动到其子目录: {src_path} -> {dst_path}")
                                return
                        except Exception:
                            pass
                    tasks.append(("move_local", src_path, dst_path))
                total = max(len(tasks), 1)
                done = 0
                for _, src, dst in tasks:
                    if self._stop:
                        self.signals.canceled.emit()
                        return
                    self.signals.progress.emit(done, total, f"移动 {os.path.basename(src)}")
                    try:
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        if os.path.exists(dst):
                            if os.path.isdir(dst) and os.path.isdir(src):
                                for root, dirs, files in os.walk(src):
                                    rel = os.path.relpath(root, src)
                                    target_dir = dst if rel == "." else os.path.join(dst, rel)
                                    os.makedirs(target_dir, exist_ok=True)
                                    for f in files:
                                        shutil.move(os.path.join(root, f), os.path.join(target_dir, f))
                                shutil.rmtree(src, ignore_errors=True)
                            else:
                                if os.path.isdir(dst):
                                    dst = os.path.join(dst, os.path.basename(src))
                                if os.path.isfile(dst):
                                    try:
                                        os.remove(dst)
                                    except Exception:
                                        pass
                                shutil.move(src, dst)
                        else:
                            shutil.move(src, dst)
                    except Exception as e:
                        self.signals.error.emit(f"本地移动失败: {src} -> {dst}: {e}")
                        return
                    done += 1
                    self.signals.progress.emit(done, total, f"移动完成 {os.path.basename(src)}")
            elif self.direction == "remote_to_remote":
                tasks = []
                for it in self.items:
                    name = it["name"]
                    src_path = posixpath.join(self.src_base if self.src_base else "/", name) if self.src_base else name
                    dst_dir = posixpath.join(self.dst_base)
                    if it.get("is_dir"):
                        try:
                            src_norm = posixpath.normpath(src_path)
                            dst_norm = posixpath.normpath(posixpath.join(dst_dir, name))
                            if dst_norm.startswith(src_norm + "/") or dst_norm == src_norm:
                                self.signals.error.emit(f"不能将远端目录移动到其子目录: {src_path} -> {dst_norm}")
                                return
                        except Exception:
                            pass
                    tasks.append(("mv_remote", src_path, dst_dir))
                total = max(len(tasks), 1)
                done = 0
                for _, src, dst_dir in tasks:
                    if self._stop:
                        self.signals.canceled.emit()
                        return
                    self.signals.progress.emit(done, total, f"远端移动 {posixpath.basename(src)}")
                    cmd_mkdir = f"mkdir -p {shlex.quote(dst_dir)}"
                    rc_mk, out_mk, err_mk = run_cmd(["adb", "-s", self.serial, "shell", cmd_mkdir], timeout=30)
                    if rc_mk != 0:
                        self.signals.error.emit(f"远端创建目录失败: {dst_dir} :: {err_mk or out_mk}")
                        return
                    cmd_mv = f"mv {shlex.quote(src)} {shlex.quote(dst_dir)}/"
                    rc_mv, out_mv, err_mv = run_cmd(["adb", "-s", self.serial, "shell", cmd_mv], timeout=60)
                    if rc_mv != 0:
                        self.signals.error.emit(f"远端移动失败: {src} -> {dst_dir} :: {err_mv or out_mv}")
                        return
                    done += 1
                    self.signals.progress.emit(done, total, f"远端移动完成 {posixpath.basename(src)}")
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit(f"异常: {e}\n{traceback.format_exc()}")


class TransferItem(QWidget):
    finishedSignal = pyqtSignal()
    def __init__(self, direction, items, src_base, dst_base, serial, parent=None):
        super().__init__(parent)
        self.worker = CopyWorker(direction, items, src_base, dst_base, serial, parent=self)
        self.label = QLabel(self)
        self.progress = QProgressBar(self)
        self.cancel = QPushButton("取消", self)
        lay = QHBoxLayout(self)
        lay.addWidget(self.label, 3)
        lay.addWidget(self.progress, 5)
        lay.addWidget(self.cancel, 0)
        self.progress.setRange(0, 100)
        self.cancel.clicked.connect(self.on_cancel)
        names = [it["name"] for it in items]
        if direction == "local_to_remote":
            prefix = "上传"
        elif direction == "remote_to_local":
            prefix = "下载"
        elif direction in ("local_to_local", "remote_to_remote"):
            prefix = "移动"
        else:
            prefix = "传输"
        self.label.setText(prefix + " " + ", ".join(names))
        self.worker.signals.progress.connect(self.on_progress)
        self.worker.signals.finished.connect(self.on_finished)
        self.worker.signals.canceled.connect(self.on_canceled)
        self.worker.signals.error.connect(self.on_error)

    def start(self):
        from threading import Thread
        self._thread = Thread(target=self.worker.run, daemon=True)
        self._thread.start()

    def on_progress(self, done, total, text):
        pct = int(done * 100 / total) if total > 0 else 0
        self.progress.setValue(pct)
        self.label.setText(text)

    def on_finished(self):
        self.progress.setValue(100)
        self.finishedSignal.emit()

    def on_canceled(self):
        self.label.setText("已取消")
        self.finishedSignal.emit()

    def on_error(self, msg):
        self.label.setText("错误: " + msg)
        try:
            print("传输错误:", msg)
        except Exception:
            pass
        self.finishedSignal.emit()

    def on_cancel(self):
        self.worker.stop()

