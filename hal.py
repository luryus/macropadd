from typing import List, Optional, Tuple
import time
import logging
from sys import platform
from threading import Thread, Event
from queue import Empty, Queue
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

        self.msg_queue = Queue()
    
    @abstractmethod
    def close(self):
        pass

class NoopHal(HalBase):
    def close(self):
        pass


class WindowsHal(HalBase):
    def __init__(self):
        self.__hid_read_thread = None
        self.__hid_thread_stop_event = Event()
        self.__hid_send_thread = None
        self.__global_hotkey_thread = None

        super().__init__()
        self.__start_hotkey_handler_thread()
        self.__start_hid_read_thread()
        self.__start_hid_sender_thread()

    def close(self):
        self.__hid_thread_stop_event.set()

    def send_profile_name(self, name: str):
        data = bytes([3]) + name[:18].encode('ascii', errors='ignore')
        if len(data) < 19:
            data += b'\0' * (19 - len(data)) 
        assert len(data) == 19
        self.msg_queue.put(data)

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
        self.msg_queue.put(data)

    def __shortcut_handler(self, key: str):
        if self.key_event_handler is not None:
            logger.debug("Sending keypress %s to handler", key)
            self.key_event_handler(key)

    def __start_hotkey_handler_thread(self):
        self.__global_hotkey_thread = Thread(None, self.__global_hotkey_thread_loop, name="hotkey_thread", daemon=True)
        self.__global_hotkey_thread.start()

    def __start_hid_read_thread(self):
        self.__hid_read_thread = Thread(None, self.__hid_read_thread_loop, name="hid_thread", daemon=True)
        self.__hid_read_thread.start()

    def __start_hid_sender_thread(self):
        self.__hid_send_thread = Thread(None, self.__hid_send_thread_loop, name="hid_sender", daemon=True)
        self.__hid_send_thread.start()

    @classmethod
    def __parse_encoder_hid_data(cls, data: List[int]) -> Tuple[Optional[int], Optional[bool]]:
        # A valid encoder message is [2, <rotation>, <button state>]
        if len(data) == 3 and data[0] == 2:
            return data[1], bool(data[2])
        return None, None

    def __hid_send_thread_loop(self):
        import hid
        logger = logging.getLogger('HID sender')
        # Main loop
        while not self.__hid_thread_stop_event.is_set():
            try:
                # Usage page 0x14 & Usage 2 == Auxiliary display
                devs = [d for d in hid.enumerate(vendor_id=0x2e8a, product_id=0xffee)
                        if d['usage_page'] == 0x14 and d['usage'] == 0x02]
                if not devs:
                    logger.debug("Macropad devices not found")
                    time.sleep(1)
                    continue

                # Only support one device connected at a time, so get the first one
                dev = hid.device()
                # hid.enumerate returns a list of dicts. Each dict represents a device.
                # The path is available under the 'path' key
                dev.open_path(devs[0]['path'])
                dev.set_nonblocking(True)

                try:
                    logger.info("Connected to %s", dev.get_product_string())
                    while not self.__hid_thread_stop_event.is_set():
                        try:
                            msg = self.msg_queue.get(block=True, timeout=1)
                        except Empty:
                            continue
                    
                        if not isinstance(msg, list) and not isinstance(msg, bytes):
                            logger.warning("Invalid message %s", msg)
                            continue

                        assert msg[0] in [0x03, 0x04]

                        logger.debug("Sending %d byte message %s", len(msg), msg)

                        res = dev.write(msg)
                        logger.debug("Send result %d", res)
                finally:
                    dev.close()
            except IOError as e:
                logger.error("HID send thread loop failed", exc_info=e)

    def __hid_read_thread_loop(self):
        import hid
        # Main loop
        while not self.__hid_thread_stop_event.is_set():
            try:
                # Usage page 1 & Usage 8 == Multi-axis controller
                devs = [d for d in hid.enumerate(vendor_id=0x2e8a, product_id=0xffee)
                        if d['usage_page'] == 1 and d['usage'] == 8]
                if not devs:
                    logger.debug("Macropad devices not found")
                    time.sleep(1)
                    continue
                
                # Only support one device connected at a time, so get the first one
                dev = hid.device()
                # hid.enumerate returns a list of dicts. Each dict represents a device.
                # The path is available under the 'path' key
                dev.open_path(devs[0]['path'])
                dev.set_nonblocking(True)

                try:
                    logger.debug("Connected to %s", dev.get_product_string())
                    
                    # Read loop
                    while not self.__hid_thread_stop_event.is_set():
                        data = dev.read(64)
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
                    dev.close()

            except IOError as e:
                print(e)

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
            
