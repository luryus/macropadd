from typing import List, Optional, Tuple
import keyboard
import time
import hid
import logging
from threading import Thread, Event
from queue import Empty, Queue

logger = logging.getLogger(__name__)

class HalBase:
    def __init__(self):
        self.key_event_handler = None
        self.encoder_button_handler = None
        self.encoder_handler = None

        self.msg_queue = Queue()


class Hal(HalBase):

    def __init__(self):
        self.__hid_read_thread = None
        self.__hid_thread_stop_event = Event()
        self.__hid_send_thread = None

        super().__init__()
        self.__register_shortcuts()
        #self.__start_hid_read_thread()
        self.__start_hid_sender_thread()

    def close(self):
        self.__hid_thread_stop_event.set()
        self.__clear_shortcuts()

    def send_profile_name(self, name: str):
        data = bytes([3]) + name[:8].encode('ascii', errors='ignore')
        if len(data) < 9:
            data += b'\0' * (9 - len(data)) 
        assert len(data) == 9
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

    def __register_shortcuts(self):
        for i in range(13, 24+1):
            key = f'F{i}'
            keyboard.add_hotkey(key, lambda k=key: self.__shortcut_handler(k), suppress=True)

    def __clear_shortcuts(self):
        for i in range(13, 24+1):
            key = f'F{i}'
            keyboard.clear_hotkey(key)

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
                    logger.debug("Connected to %s", dev.get_product_string())
                    while not self.__hid_thread_stop_event.is_set():
                        try:
                            msg = self.msg_queue.get(block=True, timeout=1)
                        except Empty:
                            continue
                    
                        if not isinstance(msg, list) and not isinstance(msg, bytes):
                            logger.warn("Invalid message %s", msg)
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
                            parsed_rot, parsed_btn = Hal.__parse_encoder_hid_data(data)
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