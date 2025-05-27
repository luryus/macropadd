from typing import List, Optional, Tuple
import time
import logging
from sys import platform
from threading import Thread, Event
from queue import Empty, Queue, Full
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

def get_hal():
    if platform == 'win32':
        return WindowsHal()
    else:
        return NoopHal()

class HalBase(ABC):
    def __init__(self):
        self.key_event_handler = None
        self.encoder_button_handler = None
        self.encoder_handler = None

        self.msg_queue = Queue(maxsize=6)

    @abstractmethod
    def close(self):
        pass

class NoopHal(HalBase):
    def close(self):
        pass


class WindowsHal(HalBase):
    def __init__(self):
        self.__hid_thread_stop_event = Event()
        self.__hid_thread = None
        self.__global_hotkey_thread = None

        super().__init__()
        self.__start_hotkey_handler_thread()
        self.__start_hid_thread()

    def close(self):
        self.__hid_thread_stop_event.set()

    def send_profile_name(self, name: str):
        data = bytes([3]) + name[:18].encode('ascii', errors='ignore')
        if len(data) < 19:
            data += b'\0' * (19 - len(data))
        assert len(data) == 19
        try:
            self.msg_queue.put(data, timeout=0.1)
        except Full:
            pass

    def send_key_names(self, key_names: List[str]):
        data = b'\04'

        # Reorder lines from top to bottom
        key_names = key_names[8:] + key_names[4:8] + key_names[:4]
        assert len(key_names) == 12

        for n in key_names:
            if n is not None:
                # Truncate / pad to exactly 4
                name = f'{n:4.4}'
            else:
                name = '    '
            data += name.encode('ascii', errors='ignore')

        assert len(data) == (1 + 4*12)
        try:
            self.msg_queue.put(data, timeout=0.1)
        except Full:
            pass

    def __shortcut_handler(self, key: str):
        if self.key_event_handler is not None:
            logger.debug("Sending keypress %s to handler", key)
            self.key_event_handler(key)

    def __start_hotkey_handler_thread(self):
        self.__global_hotkey_thread = Thread(None, self.__global_hotkey_thread_loop, name="hotkey_thread", daemon=True)
        self.__global_hotkey_thread.start()

    def __start_hid_thread(self):
        self.__hid_thread = Thread(None, self.__hid_thread_loop, name="hid_thread", daemon=True)
        self.__hid_thread.start()

    @classmethod
    def __parse_encoder_hid_data(cls, data: List[int]) -> Tuple[Optional[int], Optional[bool]]:
        # A valid encoder message is [2, <rotation>, <button state>]
        if len(data) == 3 and data[0] == 2:
            return data[1], bool(data[2])
        return None, None

    def __hid_thread_loop(self):
        import hid
        logger = logging.getLogger('HID thread')
        while not self.__hid_thread_stop_event.is_set():
            try:
                # Usage page 0x14 & Usage 2 == Auxiliary display (write)
                # Usage page 1 & Usage 8 == Multi-axis controller (read)
                devs = [d for d in hid.enumerate(vendor_id=0x2e8a, product_id=0xffee)
                        if (d['usage_page'], d['usage']) in [(0x14, 0x02), (1, 8)]]
                if not devs:
                    logger.debug("Macropad devices not found")
                    time.sleep(1)
                    continue

                # Only support one device connected at a time, so get the first one for both read and write
                read_path = next((d['path'] for d in devs if (d['usage_page'], d['usage']) == (1, 8)), None)
                write_path = next((d['path'] for d in devs if (d['usage_page'], d['usage']) == (0x14, 0x02)), None)

                if read_path is None or write_path is None:
                    logger.debug("Macropad devices not found (read_path: %s, write_path: %s)", read_path, write_path)
                    time.sleep(1)
                    continue

                read_dev = hid.device()
                read_dev.open_path(read_path)
                read_dev.set_nonblocking(True)

                write_dev = hid.device()
                write_dev.open_path(write_path)
                write_dev.set_nonblocking(True)

                try:
                    logger.info("Connected to %s (read) and %s (write)",
                                read_dev.get_product_string(), write_dev.get_product_string())
                    while not self.__hid_thread_stop_event.is_set():
                        # Handle outgoing messages
                        try:
                            msg = self.msg_queue.get(block=False)
                            if not isinstance(msg, (list, bytes)):
                                logger.warning("Invalid message %s", msg)
                                continue
                            assert msg[0] in [0x03, 0x04]
                            logger.debug("Sending %d byte message %s", len(msg), msg)
                            res = write_dev.write(msg)
                            if res == -1:
                                logger.warning("HID write errored (%s). Device probably disconnected. Reconnecting...", write_dev.error())
                                break
                        except Empty:
                            pass

                        # Handle incoming data
                        data = read_dev.read(64, timeout_ms=50)
                        if data:
                            logger.debug("Received data: %s", data)
                            parsed_rot, parsed_btn = WindowsHal.__parse_encoder_hid_data(data)
                            if parsed_rot is not None and self.encoder_handler:
                                self.encoder_handler(parsed_rot)
                            if parsed_btn is not None and self.encoder_button_handler:
                                self.encoder_button_handler(parsed_btn)
                        else:
                            time.sleep(0.001)
                finally:
                    write_dev.close()
                    read_dev.close()
            except IOError as e:
                logger.error("HID thread loop failed", exc_info=e)

    def __global_hotkey_thread_loop(self):
        import win32utils
        def reg_hotkeys():
            MOD_NOREPEAT = 0x4000
            for n in range(13, 24+1):
                # https://docs.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey
                # https://docs.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
                if not win32utils.register_hotkey(n, 0x7c - 13 + n, MOD_NOREPEAT):
                    raise win32utils.get_last_error()
        def unreg_hotkeys():
            for n in range(13, 24+1):
                if not win32utils.unregister_hotkey(n):
                    raise win32utils.get_last_error()

        # Register F13 - F24 as global hotkeys
        reg_hotkeys()

        # The WM_HOTKEY messages are delivered to this thread. Listen to them in a loop.
        WM_HOTKEY = 0x0312
        while msg := win32utils.get_message():
            # This seems to work on 64-bit windows, don't care about 32-bit
            key = msg.lParam >> 16
            mod = msg.lParam & 0xffff
            if 0x7c <= key <= 0x7c+11:
                # Key is F<n>
                n = key - 0x7c + 13
                logger.debug("Received hotkey msg for F%s", n)

                # Disable global hotkeys while handling the message.
                # This way we will not get into a loop if an action simulates Fxx keypress
                unreg_hotkeys()
                self.__shortcut_handler(f'F{n}')
                reg_hotkeys()

