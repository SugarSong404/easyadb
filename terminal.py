import os
import subprocess
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextCursor, QKeySequence, QIcon
from PyQt5.QtWidgets import QPlainTextEdit, QWidget, QVBoxLayout, QShortcut
from PyQt5.QtCore import QProcess


def open_adb_shell_terminal(serial: str):
    try:
        if os.name == "nt":
            cmd = 'start "" cmd'
            subprocess.Popen(cmd, shell=True)
        else:
            subprocess.Popen(["xterm"])
    except Exception as e:
        print("无法打开外部终端:", e)


class TerminalEdit(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Consolas", 10))
        self.input_start = 0
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def show_prompt(self, prompt):
        self.moveCursor(QTextCursor.End)
        self.insertPlainText(prompt)
        self.input_start = self.textCursor().position()
        self.ensureCursorVisible()

    def keyPressEvent(self, e):
        kc = e.key()
        mod = e.modifiers()
        if (mod & Qt.ControlModifier) and kc in (Qt.Key_C, Qt.Key_Pause):
            if hasattr(self.parent(), "send_interrupt"):
                self.parent().send_interrupt()
            return
        if kc == Qt.Key_Up:
            try:
                if hasattr(self.parent(), "history_prev_text"):
                    cur = self._current_input_text()
                    text = self.parent().history_prev_text(cur)
                    if text is not None:
                        self._replace_current_input(text)
                        return
                # 无历史或未返回文本时，保持在当前行尾
                self.moveCursor(QTextCursor.End)
                return
            except Exception:
                self.moveCursor(QTextCursor.End)
                return
        if kc == Qt.Key_Down:
            try:
                if hasattr(self.parent(), "history_next_text"):
                    cur = self._current_input_text()
                    text = self.parent().history_next_text(cur)
                    if text is not None:
                        self._replace_current_input(text)
                        return
                # 无历史或未返回文本时，清空为当前空输入并保持在行尾
                self.moveCursor(QTextCursor.End)
                return
            except Exception:
                self.moveCursor(QTextCursor.End)
                return
        if kc in (Qt.Key_Backspace,):
            if self.textCursor().position() <= self.input_start:
                return
        if kc in (Qt.Key_Left,):
            if self.textCursor().position() <= self.input_start:
                return
        if kc in (Qt.Key_Home,):
            c = self.textCursor()
            c.setPosition(self.input_start)
            self.setTextCursor(c)
            return
        if kc in (Qt.Key_Return, Qt.Key_Enter):
            c = self.textCursor()
            c.setPosition(self.input_start, QTextCursor.MoveAnchor)
            c.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            line = c.selectedText()
            self.moveCursor(QTextCursor.End)
            self.insertPlainText("\n")
            self.input_start = self.textCursor().position()
            if hasattr(self.parent(), "send_command"):
                self.parent().send_command(line)
            return
        if self.textCursor().position() < self.input_start:
            self.moveCursor(QTextCursor.End)
        super().keyPressEvent(e)

    def append_output(self, text):
        self.moveCursor(QTextCursor.End)
        self.insertPlainText(text)
        self.input_start = self.textCursor().position()
        self.ensureCursorVisible()

    def _current_input_text(self):
        try:
            c = self.textCursor()
            c.setPosition(self.input_start, QTextCursor.MoveAnchor)
            c.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            return c.selectedText()
        except Exception:
            return ""

    def _replace_current_input(self, text):
        try:
            start = self.input_start
            c = self.textCursor()
            c.setPosition(start, QTextCursor.MoveAnchor)
            c.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            c.removeSelectedText()
            self.setTextCursor(c)
            self.insertPlainText(text)
            self.input_start = start
            self.moveCursor(QTextCursor.End)
            self.ensureCursorVisible()
        except Exception:
            pass


class ShellTab(QWidget):
    def __init__(self, serial, parent=None, mode="android"):
        super().__init__(parent)
        self.serial = serial
        self.mode = mode
        self.proc = QProcess(self)
        self._local_proc = None
        self._local_cwd = None
        self.view = TerminalEdit(self)
        self.last_command = ""
        self._prompt_timer = QTimer(self)
        self._prompt_timer.setSingleShot(True)
        self._prompt_timer.timeout.connect(self._append_android_prompt)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.view, 1)
        self._history = []
        self._hist_idx = None
        self.proc.readyReadStandardOutput.connect(self.on_stdout)
        self.proc.readyReadStandardError.connect(self.on_stderr)
        self.proc.finished.connect(self.on_finished)
        self.sc_int = QShortcut(QKeySequence("Ctrl+C"), self.view)
        self.sc_int.activated.connect(self.send_interrupt)
        try:
            self.sc_int2 = QShortcut(QKeySequence("Ctrl+Pause"), self.view)
            self.sc_int2.activated.connect(self.send_interrupt)
        except Exception:
            pass

    def start(self):
        if self.proc.state() != QProcess.NotRunning:
            return
        if not self.serial:
            return
        if self.mode == "android":
            self.proc.start("adb", ["-s", self.serial, "shell", "-t", "-t"])
        else:
            try:
                home = os.path.expanduser("~")
                desktop = os.path.join(home, "Desktop")
                if os.name == "nt" and os.path.isdir(desktop):
                    self._local_cwd = desktop
                elif os.path.isdir(home):
                    self._local_cwd = home
                else:
                    self._local_cwd = os.getcwd()
            except Exception:
                self._local_cwd = os.getcwd()
            self.view.show_prompt(self._build_local_prompt())
    def stop(self):
        try:
            if self.proc.state() != QProcess.NotRunning:
                self.proc.terminate()
                try:
                    QTimer.singleShot(500, lambda: self.proc.kill() if self.proc.state() != QProcess.NotRunning else None)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if self._local_proc and self._local_proc.state() != QProcess.NotRunning:
                self._local_proc.kill()
        except Exception:
            pass

    def on_stdout(self):
        try:
            data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "ignore")
            if data:
                if self.mode == "local" and self.last_command:
                    for eol in ("\r\n", "\n"):
                        prefix = self.last_command + eol
                        if data.startswith(prefix):
                            data = data[len(prefix):]
                            break
                    self.last_command = ""
                self.view.append_output(data)
                if self.mode == "android":
                    self._arm_prompt_timer()
        except Exception:
            pass

    def on_stderr(self):
        try:
            data = bytes(self.proc.readAllStandardError()).decode("utf-8", "ignore")
            if data:
                self.view.append_output(data)
                if self.mode == "android":
                    self._arm_prompt_timer()
        except Exception:
            pass

    def on_finished(self):
        self.view.append_output("\n[terminated]\n")

    def send_command(self, line):
        if self.mode == "android":
            try:
                self.proc.write((line + "\n").encode("utf-8"))
            except Exception:
                pass
            self.last_command = line
            try:
                s2 = (line or "").strip()
                if s2:
                    self._push_history(s2)
            except Exception:
                pass
            self.view.moveCursor(self.view.textCursor().End)
            self._arm_prompt_timer()
            return
        s = line.strip()
        if not s:
            self.view.show_prompt(self._build_local_prompt())
            return
        try:
            self._push_history(s)
        except Exception:
            pass
        if s.lower().startswith("cd "):
            target = s[3:].strip().strip('"').strip("'")
            try:
                newp = target
                if not os.path.isabs(newp):
                    newp = os.path.abspath(os.path.join(self._local_cwd, newp))
                if os.path.isdir(newp):
                    self._local_cwd = newp
            except Exception:
                pass
            self.view.append_output("\n")
            self.view.show_prompt(self._build_local_prompt())
            return
        if s.lower() in ("cls", "clear"):
            self.view.setPlainText("")
            self.view.show_prompt(self._build_local_prompt())
            return
        if self._local_proc and self._local_proc.state() != QProcess.NotRunning:
            return
        self._local_proc = QProcess(self)
        try:
            self._local_proc.setWorkingDirectory(self._local_cwd or os.getcwd())
        except Exception:
            pass
        if os.name == "nt":
            program = "powershell"
            args = ["-NoLogo", "-NoProfile", "-Command", line]
        else:
            program = "/bin/bash"
            args = ["-lc", line]
        self._local_proc.readyReadStandardOutput.connect(self._on_local_stdout)
        self._local_proc.readyReadStandardError.connect(self._on_local_stderr)
        self._local_proc.finished.connect(self._on_local_finished)
        self._local_proc.start(program, args)

    def send_interrupt(self):
        try:
            if self.mode == "android":
                try:
                    self.proc.write(b"\x03")
                except Exception:
                    pass
                return
            if self.mode == "local":
                if self._local_proc and self._local_proc.state() != QProcess.NotRunning:
                    try:
                        self._local_proc.terminate()
                        QTimer.singleShot(300, lambda: self._local_proc.kill() if self._local_proc and self._local_proc.state() != QProcess.NotRunning else None)
                    except Exception:
                        try:
                            self._local_proc.kill()
                        except Exception:
                            pass
                else:
                    self.view.append_output("\n")
                    self.view.show_prompt(self._build_local_prompt())
                return
        except Exception:
            pass

    def _arm_prompt_timer(self):
        try:
            self._prompt_timer.start(180)
        except Exception:
            pass

    def _append_android_prompt(self):
        try:
            txt = self.view.toPlainText()
            tail = txt[-120:] if len(txt) > 120 else txt
            tail_stripped = tail.rstrip("\r\n")
            if tail_stripped.endswith(("$ ", "# ", "> ")):
                return
            if not txt.endswith(("\n", "\r", "\r\n")):
                self.view.append_output("\n")
            self.view.show_prompt(f"(adb:{self.serial})> ")
        except Exception:
            pass

    def _build_local_prompt(self):
        try:
            base = self._local_cwd if self._local_cwd else os.getcwd()
            if os.name == "nt":
                return f"({base})> "
            return f"({base})$ "
        except Exception:
            return "> "

    def _push_history(self, cmd: str):
        try:
            if not cmd:
                return
            if not self._history or self._history[-1] != cmd:
                self._history.append(cmd)
            self._hist_idx = None
        except Exception:
            pass

    def history_prev_text(self, current: str):
        try:
            if not self._history:
                return None
            if self._hist_idx is None:
                self._hist_idx = len(self._history) - 1
            elif self._hist_idx > 0:
                self._hist_idx -= 1
            return self._history[self._hist_idx]
        except Exception:
            return None

    def history_next_text(self, current: str):
        try:
            if not self._history:
                return None
            if self._hist_idx is None:
                return ""
            if self._hist_idx < len(self._history) - 1:
                self._hist_idx += 1
                return self._history[self._hist_idx]
            else:
                self._hist_idx = None
                return ""
        except Exception:
            return None


    def _on_local_stdout(self):
        try:
            data = bytes(self._local_proc.readAllStandardOutput()).decode("utf-8", "ignore")
            if data:
                self.view.append_output(data)
        except Exception:
            pass

    def _on_local_stderr(self):
        try:
            data = bytes(self._local_proc.readAllStandardError()).decode("utf-8", "ignore")
            if data:
                self.view.append_output(data)
        except Exception:
            pass

    def _on_local_finished(self):
        try:
            self._local_proc = None
            self.view.append_output("\n")
            self.view.show_prompt(self._build_local_prompt())
        except Exception:
            pass
