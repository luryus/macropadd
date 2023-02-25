import ctypes
import ctypes.wintypes
import threading
import logging
from sys import platform
from abc import ABC, abstractmethod
from typing import Callable

if platform == 'win32':
    import win32utils

logger = logging.getLogger(__name__)

_CallbackFunctionType = Callable[[str], None]


def get_active_window_listener(callback: _CallbackFunctionType):
    if platform == 'win32':
        return WindowsActiveWindowListener(callback)
    else:
        return NoopActiveWindowListener(callback)


class BaseActiveWindowListener(ABC):
    def __init__(self, callback: _CallbackFunctionType):
        self.process_change_callback: _CallbackFunctionType = callback
    
    @abstractmethod
    def listen_forever(self):
        pass

class NoopActiveWindowListener(BaseActiveWindowListener):
    def listen_forever(self):
        pass


class WindowsActiveWindowListener(BaseActiveWindowListener):
    def __init__(self, callback: _CallbackFunctionType):
        super().__init__(callback)

    def _run(self):
        win32utils.ole32_coinitialize()
        # Keep proc in a variable so that it's not gc'd
        proc = win32utils.set_win_event_hook(self._callback)
        win32utils.handle_messages_forever()

    def _callback(self, hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        if event != win32utils.EVENT_SYSTEM_FOREGROUND and event != win32utils.EVENT_SYSTEM_MINIMIZEEND:
            return

        logger.debug('Active window %s', win32utils.get_window_text(hwnd))

        pid = win32utils.get_thread_process_id(dwEventThread)
        logger.debug('Active window PID %d', pid)
        if pid is not None:
            path = win32utils.get_process_filename(pid)
            logger.debug('Active window path %s', path)
            self.process_change_callback(path)

    def listen_forever(self):
        t = threading.Thread(target=self._run, daemon=True, name="active_window_listener")
        t.start()