import threading
from PIL import Image, ImageDraw
import pystray
from threading import Thread, Event, current_thread
import os.path

def get_sys_icon(layer_file_path: str) -> pystray.Icon:
    i = pystray.Icon('macropadd', icon=_get_icon_image(), title='macropadd')
    menu = pystray.Menu(
        pystray.MenuItem('macropadd', None, enabled=False),
        pystray.MenuItem('Edit layers...', lambda: _start_edit_layers(layer_file_path), enabled=True),
        pystray.MenuItem('Quit', lambda: i.stop(), enabled=True)
    )

    i.menu = menu

    return i

def run(layer_file_path: str) -> Thread:
    icon_ref = None
    start_event = Event()
    def _icon_thread_loop():
        nonlocal icon_ref
        i = get_sys_icon(layer_file_path)
        icon_ref = i
        start_event.set()
        i.run()
    t = Thread(target=_icon_thread_loop, name='systray_icon')
    t.start()
    start_event.wait()
    return t, icon_ref

def _get_icon_image() -> Image:
    return Image.open(os.path.join(os.path.dirname(__file__), 'tray_icon.png'))
def _start_edit_layers(path: str):
    import subprocess, os, platform
    if platform.system() == 'Darwin':
        subprocess.call(('open', path))
    elif platform.system() == 'Windows':
        os.startfile(path)
    else:
        subprocess.call(('xdg-open', path))