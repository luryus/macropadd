import yaml
from action import BaseAction, parse_action, HotkeyAction
from typing import Callable, Dict, List
from keys import VALID_KEY_NAMES
from logging import getLogger
import time
from watchdog.observers import Observer
from watchdog.events import FileModifiedEvent, FileSystemEventHandler


logger = getLogger(__name__)

# -------


class Layer:
    def __init__(self, name: str):
        self.name = name
        self.application = None
        self.key_actions: Dict[str, BaseAction] = {}
        self.encoder_inc_action: BaseAction = None
        self.encoder_dec_action: BaseAction = None
        self.encoder_btn_action: BaseAction = None

    def __str__(self):
        return f"Layer({self.name})"

    def __repr__(self):
        return str(self)

    @staticmethod
    def from_spec_dict(spec: dict):
        l = Layer(spec["name"])

        if "application" in spec:
            l.application = spec["application"]

        for k, action_spec in spec.items():
            if k not in VALID_KEY_NAMES:
                continue

            a = parse_action(action_spec)

            if a is None:
                logger.warn("Invalid action: %s", action_spec)
                continue
            l.key_actions[k] = a

        return l

    def get_key_names(self) -> List[str]:
        o = []
        for k in VALID_KEY_NAMES:
            if k in self.key_actions:
                o.append(self.key_actions[k].name)
            else:
                o.append(None)
        return o

    def run_action_for_key(self, key: str) -> bool:
        if key not in self.key_actions:
            return False

        action = self.key_actions[key]
        action.run()
        logger.debug("Ran action %s", action)
        return True

    def run_action_for_encoder_inc(self) -> bool:
        if self.encoder_inc_action:
            self.encoder_inc_action.run()
            logger.debug("Ran action %s", self.encoder_inc_action)
            return True
        return False

    def run_action_for_encoder_dec(self) -> bool:
        if self.encoder_dec_action:
            self.encoder_dec_action.run()
            logger.debug("Ran action %s", self.encoder_dec_action)
            return True
        return False

    def run_action_for_encoder_btn(self) -> bool:
        if self.encoder_btn_action:
            self.encoder_btn_action.run()
            logger.debug("Ran action %s", self.encoder_btn_action)
            return True
        return False


def create_default_layer() -> Layer:
    layer = Layer("default")
    for i in range(13, 24 + 1):
        key_name = f"F{i}"
        layer.key_actions[key_name] = HotkeyAction(key_name, key_name)
    return layer


def parse_layers(layer_yaml_file: str) -> Dict[str, Layer]:
    with open(layer_yaml_file, "r") as f:
        file_content: dict = yaml.safe_load(f)

    layers = {}
    for layer_key, layer_spec in file_content.items():
        l = Layer.from_spec_dict(layer_spec)
        layers[layer_key] = l
    return layers


# -- Layer file watcher --


class LayerFileWatcher:
    class _Handler(FileSystemEventHandler):
        def __init__(self, filename, cb):
            self.filename = filename
            self.cb = cb
            self.last_trigger_time = 0

        def on_modified(self, event: FileModifiedEvent):
            # Debounce the modification events
            if time.time() - self.last_trigger_time < 0.5:
                return
            self.last_trigger_time = time.time()

            try:
                logger.info("Reloading layers file %s...", self.filename)
                new_layers = parse_layers(self.filename)
                self.cb(new_layers)
            except Exception as e:
                logger.warn("Loading new layers failed: %s", e)

    def __init__(
        self, filename: str, new_layers_callback: Callable[[Dict[str, Layer]], None]
    ):
        self.filename = filename
        self.new_layers_callback = new_layers_callback

    def start(self):
        event_handler = LayerFileWatcher._Handler(
            self.filename, self.new_layers_callback
        )
        observer = Observer()
        observer.schedule(event_handler, self.filename, False)
        observer.setDaemon(True)
        observer.start()
