import sys
import time
import ctypes
import ctypes.wintypes
import threading
import logging

logger = logging.getLogger(__name__)

WINEVENT_OUTOFCONTEXT = 0x0000
EVENT_SYSTEM_FOREGROUND = 0x0003

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
THREAD_QUERY_LIMITED_INFORMATION = 0x0800

user32 = ctypes.windll.user32
ole32 = ctypes.windll.ole32
kernel32 = ctypes.windll.kernel32


def getProcessID(dwEventThread, hwnd):
    hThread = kernel32.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, 0, dwEventThread)

    if hThread:
        try:
            processID = kernel32.GetProcessIdOfThread(hThread)
            if not processID:
                logger.warn("Couldn't get process for thread %s: %s" % (hThread, ctypes.WinError()))
                return None
        finally:
            kernel32.CloseHandle(hThread)
    else:
        logger.warn("Could not open thread")

    return processID


def getProcessFilename(processID):
    hProcess = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, processID)
    if not hProcess:
        logger.error("OpenProcess(%s) failed: %s" % (processID, ctypes.WinError()))
        return None

    try:
        filenameBufferSize = ctypes.wintypes.DWORD(4096)
        filename = ctypes.create_unicode_buffer(filenameBufferSize.value)
        kernel32.QueryFullProcessImageNameW(hProcess, 0, ctypes.byref(filename),
                                            ctypes.byref(filenameBufferSize))

        return filename.value
    finally:
        kernel32.CloseHandle(hProcess)


class ActiveWindowListener:
    def __init__(self, callback):
        self.process_change_callback = callback

    def _run(self):
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
        length = user32.GetWindowTextLengthA(hwnd)
        buff = ctypes.create_string_buffer(length + 1)
        user32.GetWindowTextA(hwnd, buff, length + 1)
        logger.debug('Active window %s', buff.value)

        pid = getProcessID(dwEventThread, hwnd)
        logger.debug('Active window PID %d', pid)
        if pid is not None:
            path = getProcessFilename(pid)
            logger.debug('Active window path %s', path)
            self.process_change_callback(path)
        

    def listen_forever(self):
        t = threading.Thread(target=self._run, daemon=True, name="active_window_listener")
        t.start()