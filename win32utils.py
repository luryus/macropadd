import ctypes
from logging import getLogger
from typing import Optional

WINEVENT_OUTOFCONTEXT = 0x0000
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MINIMIZEEND = 0x0017

logger = getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.wintypes.LPARAM]

def ole32_coinitialize():
    ole32 = ctypes.windll.ole32
    if ole32.CoInitialize(0) != 0:
        raise Exception("Ole32.CoInitialize failed")

def set_win_event_hook(callback):
    WinEventProcType = ctypes.WINFUNCTYPE(
        None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
        ctypes.wintypes.HWND, ctypes.wintypes.LONG, ctypes.wintypes.LONG,
        ctypes.wintypes.DWORD, ctypes.wintypes.DWORD
    )
    WinEventProc = WinEventProcType(callback)
    user32.SetWinEventHook.restype = ctypes.wintypes.HANDLE
    hook = user32.SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND,
        EVENT_SYSTEM_MINIMIZEEND,
        0,
        WinEventProc,
        0,
        0,
        WINEVENT_OUTOFCONTEXT
    )
    if hook == 0:
        raise Exception("Setting windows hook failed")
    return WinEventProc

def handle_messages_forever():
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
        user32.TranslateMessageW(msg)
        user32.DispatchMessageW(msg)

def get_window_text(hwnd):
    length = user32.GetWindowTextLengthA(hwnd)
    buff = ctypes.create_string_buffer(length + 1)
    user32.GetWindowTextA(hwnd, buff, length + 1)
    return buff.value

def get_thread_process_id(dwEventThread):
    THREAD_QUERY_LIMITED_INFORMATION = 0x0800
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

def get_process_filename(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
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

def get_window_process_id(hwnd):
    pid = ctypes.wintypes.DWORD(0)
    thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid

def set_foreground_window(hwnd):
    user32.SetForegroundWindow(hwnd)

def get_foreground_window():
    return user32.GetForegroundWindow()

def enum_windows(callback):
    cb = WNDENUMPROC(callback)
    user32.EnumWindows(cb, 0)

def is_minimized(hwnd):
    return user32.IsIconic(hwnd)

def restore_minimized_window(hwnd):
    SW_RESTORE = 9
    return user32.ShowWindow(hwnd, SW_RESTORE)

def is_window_visible(hwnd) -> bool:
    return user32.IsWindowVisible(hwnd)

def register_hotkey(id, key, modifiers) -> bool:
    return user32.RegisterHotKey(None, id, modifiers, key)

def unregister_hotkey(id) -> bool:
    return user32.UnregisterHotKey(None, id)

def get_message() -> ctypes.wintypes.MSG:
    msg = ctypes.wintypes.MSG()
    if user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
        return msg
    return None

def get_last_error() -> Optional[ctypes.WinError]:
    return ctypes.WinError(ctypes.get_last_error())