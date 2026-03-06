from PyQt5.QtCore import QObject, pyqtSignal
import time
from utils import list_adb_devices, adb_list_dir, run_cmd


class DeviceListWorker(QObject):
    finished = pyqtSignal(list)

    def run(self):
        try:
            devs = list_adb_devices()
        except Exception:
            devs = []
        self.finished.emit(devs)


class RemoteListWorker(QObject):
    finished = pyqtSignal(str, str, list)

    def __init__(self, serial, path):
        super().__init__()
        self.serial = serial
        self.path = path

    def run(self):
        try:
            items = adb_list_dir(self.serial, self.path)
            if not items:
                try:
                    time.sleep(0.25)
                except Exception:
                    pass
                items = adb_list_dir(self.serial, self.path)
        except Exception:
            items = []
        self.finished.emit(self.serial, self.path, items)


class DeviceConnectWorker(QObject):
    finished = pyqtSignal(bool, str, str, list)

    def __init__(self, serial):
        super().__init__()
        self.serial = serial

    def run(self):
        try:
            rc, out, err = run_cmd(["adb", "-s", self.serial, "get-state"], timeout=5)
            ok = (rc == 0 and (out.strip() or "device" in (out + err)))
            if not ok:
                self.finished.emit(False, self.serial, err or out or "", [])
                return
            items = adb_list_dir(self.serial, "/")
            self.finished.emit(True, self.serial, "", items)
        except Exception as e:
            self.finished.emit(False, self.serial, str(e), [])
