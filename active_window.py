import ctypes
import ctypes.wintypes
import threading
import logging
from sys import platform
from abc import ABC, abstractmethod
from typing import Callable

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
        WINEVENT_OUTOFCONTEXT = 0x0000
        EVENT_SYSTEM_FOREGROUND = 0x0003


        user32 = ctypes.windll.user32
        ole32 = ctypes.windll.ole32

        ole32.CoInitialize(0)
        WinEventProcType = ctypes.WINFUNCTYPE(
            None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
            ctypes.wintypes.HWND, ctypes.wintypes.LONG, ctypes.wintypes.LONG,
            ctypes.wintypes.DWORD, ctypes.wintypes.DWORD
        )
        WinEventProc = WinEventProcType(self._callback)

        user32.SetWinEventHook.restype = ctypes.wintypes.HANDLE
        hook = user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            0,
            WinEventProc,
            0,
            0,
            WINEVENT_OUTOFCONTEXT
        )
        if hook == 0:
            raise Exception("Setting windows hook failed")
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessageW(msg)
            user32.DispatchMessageW(msg)

    def _callback(self, hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthA(hwnd)
        buff = ctypes.create_string_buffer(length + 1)
        user32.GetWindowTextA(hwnd, buff, length + 1)
        logger.debug('Active window %s', buff.value)

        pid = WindowsActiveWindowListener._get_process_id(dwEventThread, hwnd)
        logger.debug('Active window PID %d', pid)
        if pid is not None:
            path = WindowsActiveWindowListener._get_process_filename(pid)
            logger.debug('Active window path %s', path)
            self.process_change_callback(path)
        
    @staticmethod
    def _get_process_id(dwEventThread, hwnd):
        THREAD_QUERY_LIMITED_INFORMATION = 0x0800
        kernel32 = ctypes.windll.kernel32
        hThread = kernel32.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, 0, dwEventThread)

        if hThread:
            try:
                processID = kernel32.GetProcessIdOfThread(hThread)
                if not processID:
                    logger.warning("Could not get process for thread %s: %s" % (hThread, ctypes.WinError()))
                    return None
                else:
                    return processID
            finally:
                kernel32.CloseHandle(hThread)
        else:
            logger.warning("Could not open thread")
            return None

    @staticmethod
    def _get_process_filename(pid):
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        hProcess = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not hProcess:
            logger.error("OpenProcess(%s) failed: %s" % (pid, ctypes.WinError()))
            return None

        try:
            filenameBufferSize = ctypes.wintypes.DWORD(4096)
            filename = ctypes.create_unicode_buffer(filenameBufferSize.value)
            kernel32.QueryFullProcessImageNameW(hProcess, 0, ctypes.byref(filename),
                                                ctypes.byref(filenameBufferSize))

            return filename.value
        finally:
            kernel32.CloseHandle(hProcess)

    def listen_forever(self):
        t = threading.Thread(target=self._run, daemon=True, name="active_window_listener")
        t.start()