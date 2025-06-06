from abc import ABC, abstractmethod
from typing import List, Optional 
import keyboard
from logging import getLogger
import time
from sys import platform
import os.path
import os

if platform == 'win32':
    import win32utils

logger = getLogger(__name__)

class BaseAction(ABC):
    def __init__(self, name):
        self.name = name

    @abstractmethod
    def run(self):
        pass

    @staticmethod
    @abstractmethod
    def parse(data: dict) -> Optional['BaseAction']:
        pass

class HotkeyAction(BaseAction):
    def __init__(self, hotkey: str, name: str):
        super().__init__(name)
        self.hotkey = hotkey

    def __str__(self):
        return f'Hotkey({self.hotkey})'

    def run(self):
        keyboard.send(self.hotkey)

    @staticmethod
    def parse(data: dict):
        if 'hotkey' in data:
            return HotkeyAction(data['hotkey'], data.get('name', ''))
        return None

class TypeAction(BaseAction):
    def __init__(self, text: str, name: str):
        super().__init__(name)
        self.text = text

    def __str__(self):
        return f'Type({self.text})'

    def run(self):
        keyboard.write(self.text)

    @staticmethod
    def parse(data: dict):
        if 'type' in data:
            return TypeAction(data['type'], data.get('name', ''))
        return None

class RepeatAction(BaseAction):
    def __init__(self, inner: BaseAction, name: str, count: int, delay_ms: int):
        super().__init__(name)
        self.inner = inner
        self.delay_ms = delay_ms
        self.count = count
    
    def __str__(self):
        return f'Repeat({self.count}, {self.inner})'

    def run(self):
        delay = float(self.delay_ms) / 1000
        for i in range(self.count):
            time.sleep(delay)
            self.inner.run()
    
    @staticmethod
    def parse(data: dict):
        if 'repeat' in data:
            inner = parse_action(data['repeat']['action'])
            if inner is None:
                raise ValueError('Could not parse repeat action')
            count = int(data['repeat'].get('count', 0))
            delay_ms = int(data['repeat'].get('delayMs', 20))
            return RepeatAction(inner, data.get('name', ''), count, delay_ms)
        return None


class SequentialAction(BaseAction):
    def __init__(self, actions: List[BaseAction], name: str, delay_ms: int):
        super().__init__(name)
        self.actions = actions
        self.delay_ms = delay_ms

    def __str__(self):
        return f'Sequence(\n  ' + '\n  '.join(map(str, self.actions)) + ')'

    def run(self):
        delay = float(self.delay_ms) / 1000
        for a in self.actions:
            time.sleep(delay)
            a.run()

    @staticmethod
    def parse(data: dict):
        if 'sequence' in data:
            step_actions = []
            for step in data['sequence']['steps']:
                a = parse_action(step)
                if a is None:
                    raise ValueError('Could not parse step action')
                step_actions.append(a)
            return SequentialAction(step_actions, data.get('name', ''), int(data['sequence'].get('delayMs', 20)))

        return None


class ActivateWindowAction(BaseAction):
    def __init__(self, program_path: str, name: str):
        super().__init__(name)
        self.program_path = program_path
    
    def __str__(self):
        return f'Activate({self.program_path})'

    def run(self):
        if platform == 'win32':
            self.__run_windows()
        else:
            pass

    def __run_windows(self):
        found_hwnd = None
        def enum_callback(hwnd, lParam) -> bool:
            nonlocal found_hwnd
            if not win32utils.is_window_visible(hwnd):
                # Skip hidden windows
                return True
            pid = win32utils.get_window_process_id(hwnd)
            process_file = win32utils.get_process_filename(pid)
            if process_file and process_file == os.path.realpath(self.program_path):
                found_hwnd = hwnd
                return False
            return True
        
        win32utils.enum_windows(enum_callback)

        if found_hwnd:
            if win32utils.get_foreground_window() == found_hwnd:
                logger.debug("Window %s already in foreground", found_hwnd)
                return

            if win32utils.is_minimized(found_hwnd):
                win32utils.restore_minimized_window(found_hwnd)

            logger.debug("Setting window %s to foreground", found_hwnd)
            win32utils.set_foreground_window(found_hwnd)
            return

        logger.debug("Existing window not found for %s, launching...", self.program_path)
        os.startfile(self.program_path)
        
    @staticmethod
    def parse(data: dict):
        if 'activateWindow' in data:
            return ActivateWindowAction(data['activateWindow'], data.get('name', ''))
        return None

def parse_action(spec: dict):
    if not isinstance(spec, dict):
        logger.warning("Invalid action: %s", spec)
        return None

    a = HotkeyAction.parse(spec) or \
        TypeAction.parse(spec) or \
        ActivateWindowAction.parse(spec) or \
        SequentialAction.parse(spec) or \
        RepeatAction.parse(spec)

    if a is None:
        logger.warning("Invalid action %s", spec)
        raise ValueError("Invalid action: %s", spec)

    return a