import os
import subprocess
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextCursor, QKeySequence, QIcon, QGuiApplication
from PyQt5.QtWidgets import QPlainTextEdit, QWidget, QVBoxLayout, QShortcut
from PyQt5.QtCore import QProcess, pyqtSignal, QObject

class HistoryBus(QObject):
    historyChanged = pyqtSignal()

bus = HistoryBus()
GLOBAL_HISTORY = []

def push_global_history(cmd: str):
    try:
        if not cmd:
            return
        if not GLOBAL_HISTORY or GLOBAL_HISTORY[-1] != cmd:
            GLOBAL_HISTORY.append(cmd)
        if len(GLOBAL_HISTORY) > 30:
            del GLOBAL_HISTORY[: len(GLOBAL_HISTORY) - 30]
        try:
            bus.historyChanged.emit()
        except Exception:
            pass
    except Exception:
        pass


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
        if kc in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
            return
        if (mod & Qt.ControlModifier) and (mod & Qt.ShiftModifier) and kc == Qt.Key_C:
            self.copy()
            return
        if (mod & Qt.ControlModifier) and (mod & Qt.ShiftModifier) and kc == Qt.Key_V:
            try:
                clip = QGuiApplication.clipboard()
                text = clip.text() if clip else ""
            except Exception:
                text = ""
            if not text:
                return
            try:
                c = self.textCursor()
                if c.hasSelection():
                    sel_start = min(c.selectionStart(), c.selectionEnd())
                    if sel_start < self.input_start:
                        self.moveCursor(QTextCursor.End)
                        c = self.textCursor()
                if c.position() < self.input_start:
                    self.moveCursor(QTextCursor.End)
                    c = self.textCursor()
                self.setTextCursor(c)
                self.insertPlainText(text)
                self.ensureCursorVisible()
            except Exception:
                pass
            return
        if (mod & Qt.ControlModifier) and kc in (Qt.Key_C, Qt.Key_Pause):
            if hasattr(self.parent(), "send_interrupt"):
                self.parent().send_interrupt()
            return
        try:
            c0 = self.textCursor()
            has_sel = c0.hasSelection()
            if has_sel:
                sel_start = min(c0.selectionStart(), c0.selectionEnd())
            else:
                sel_start = c0.position()
            is_text_input = bool(getattr(e, "text", lambda: "")()) and not (mod & Qt.ControlModifier) and not (mod & Qt.AltModifier)
            is_edit_key = kc in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab)
            should_redirect = is_text_input or is_edit_key
            if should_redirect and sel_start < self.input_start:
                self.moveCursor(QTextCursor.End)
        except Exception:
            pass
        if kc == Qt.Key_Tab:
            try:
                if hasattr(self.parent(), "handle_tab"):
                    cur = self._current_input_text()
                    rel = self.textCursor().position() - self.input_start
                    new_text = self.parent().handle_tab(cur, rel)
                    if isinstance(new_text, str):
                        self._replace_current_input(new_text)
                    return
            except Exception:
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
            is_text_input = bool(getattr(e, "text", lambda: "")()) and not (mod & Qt.ControlModifier) and not (mod & Qt.AltModifier)
            if is_text_input or kc in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
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
    historyChanged = pyqtSignal()
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
        self._last_was_tab = False
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
                if self.mode == "android" and getattr(self, "_last_was_tab", False):
                    try:
                        while data.startswith("\t") or data.startswith("^I"):
                            if data.startswith("^I"):
                                data = data[2:]
                            elif data.startswith("\t"):
                                data = data[1:]
                            else:
                                break
                    except Exception:
                        pass
                    self._last_was_tab = False
                self.view.append_output(data)
        except Exception:
            pass

    def on_stderr(self):
        try:
            data = bytes(self.proc.readAllStandardError()).decode("utf-8", "ignore")
            if data:
                if self.mode == "android" and getattr(self, "_last_was_tab", False):
                    try:
                        while data.startswith("\t") or data.startswith("^I"):
                            if data.startswith("^I"):
                                data = data[2:]
                            elif data.startswith("\t"):
                                data = data[1:]
                            else:
                                break
                    except Exception:
                        pass
                    self._last_was_tab = False
                self.view.append_output(data)
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

    def handle_tab(self, current_text: str, cursor_offset: int):
        if self.mode == "android":
            try:
                return self._android_tab_complete(current_text, cursor_offset)
            except Exception:
                return None
        try:
            return self._local_tab_complete(current_text, cursor_offset)
        except Exception:
            return None

    def _local_tab_complete(self, current_text: str, cursor_offset: int):
        prefix = current_text[: max(0, cursor_offset)]
        if not prefix or prefix.endswith((" ", "\t")):
            return None
        token_start = max(prefix.rfind(" "), prefix.rfind("\t")) + 1
        token = prefix[token_start:]
        quoted = False
        quote_char = ""
        if token and token[0] in ('"', "'"):
            quoted = True
            quote_char = token[0]
            token = token[1:]
        token = token.replace("/", os.sep)
        if os.altsep:
            token = token.replace(os.altsep, os.sep)
        base_dir = token
        part = ""
        if token.endswith(os.sep):
            base_dir = token
            part = ""
        else:
            base_dir = os.path.dirname(token)
            part = os.path.basename(token)
        search_dir = base_dir
        if not os.path.isabs(search_dir):
            search_dir = os.path.abspath(os.path.join(self._local_cwd or os.getcwd(), search_dir))
        if not os.path.isdir(search_dir):
            return None
        try:
            entries = os.listdir(search_dir)
        except Exception:
            return None
        matches = [n for n in entries if n.lower().startswith(part.lower())]
        if not matches:
            return None
        matches.sort(key=lambda s: s.lower())
        common = matches[0]
        for m in matches[1:]:
            i = 0
            limit = min(len(common), len(m))
            while i < limit and common[i].lower() == m[i].lower():
                i += 1
            common = common[:i]
            if not common:
                break
        if len(matches) == 1:
            common = matches[0]
        if not common or common.lower() == part.lower():
            return None
        completed = os.path.join(base_dir, common) if base_dir else common
        if quoted:
            completed = quote_char + completed
        return current_text[:token_start] + completed + current_text[token_start + (len(prefix) - token_start):]

    def _android_tab_complete(self, current_text: str, cursor_offset: int):
        prefix = current_text[: max(0, cursor_offset)]
        if not prefix or prefix.endswith((" ", "\t")):
            return None
        token_start = max(prefix.rfind(" "), prefix.rfind("\t")) + 1
        token = prefix[token_start:]
        quoted = False
        quote_char = ""
        if token and token[0] in ('"', "'"):
            quoted = True
            quote_char = token[0]
            token = token[1:]
        # 路径补全（含 /）
        if "/" in token or token.startswith("/"):
            base_dir = token
            part = ""
            if token.endswith("/"):
                base_dir = token
                part = ""
            else:
                base_dir = os.path.dirname(token)
                part = os.path.basename(token)
            dir_arg = base_dir if base_dir else "/"
            try:
                result = subprocess.run(["adb", "-s", self.serial, "shell", "ls", "-1", dir_arg], capture_output=True, text=True, timeout=1.5)
                if result.returncode != 0:
                    return None
                entries = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            except Exception:
                return None
            matches = [n for n in entries if n.lower().startswith(part.lower())]
            if not matches:
                return None
            matches.sort(key=lambda s: s.lower())
            common = matches[0]
            for m in matches[1:]:
                i = 0
                limit = min(len(common), len(m))
                while i < limit and common[i].lower() == m[i].lower():
                    i += 1
                common = common[:i]
                if not common:
                    break
            if len(matches) == 1:
                common = matches[0]
            if not common or common.lower() == part.lower():
                return None
            completed = (base_dir + common) if base_dir.endswith("/") else (base_dir + "/" + common)
            if quoted:
                completed = quote_char + completed
            return current_text[:token_start] + completed + current_text[token_start + (len(prefix) - token_start):]
        # 命令补全（从 PATH 搜索）
        try:
            r = subprocess.run(["adb", "-s", self.serial, "shell", "sh", "-lc", "echo \"$PATH\""], capture_output=True, text=True, timeout=1.5)
            if r.returncode != 0:
                return None
            paths = [p for p in (r.stdout.strip().split(":")) if p]
        except Exception:
            return None
        entries = set()
        for p in paths[:10]:
            try:
                lr = subprocess.run(["adb", "-s", self.serial, "shell", "ls", "-1", p], capture_output=True, text=True, timeout=1.0)
                if lr.returncode == 0:
                    for line in lr.stdout.splitlines():
                        s = line.strip()
                        if s:
                            entries.add(s)
            except Exception:
                continue
        part = token
        matches = [n for n in entries if n.lower().startswith(part.lower())]
        if not matches:
            return None
        matches.sort(key=lambda s: s.lower())
        common = matches[0]
        for m in matches[1:]:
            i = 0
            limit = min(len(common), len(m))
            while i < limit and common[i].lower() == m[i].lower():
                i += 1
            common = common[:i]
            if not common:
                break
        if len(matches) == 1:
            common = matches[0]
        if not common or common.lower() == part.lower():
            return None
        completed = common
        if quoted:
            completed = quote_char + completed
        return current_text[:token_start] + completed + current_text[token_start + (len(prefix) - token_start):]

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
            try:
                push_global_history(cmd)
            except Exception:
                pass
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
