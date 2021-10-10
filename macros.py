from abc import ABC, abstractmethod
from typing import Dict, List
import keyboard
import yaml
from keys import VALID_KEY_NAMES
from logging import getLogger
import time

logger = getLogger(__name__)

class BaseAction(ABC):
    def __init__(self, name):
        self.name = name

    @abstractmethod
    def run(self):
        pass

class HotkeyAction(BaseAction):
    def __init__(self, hotkey: str, name: str):
        super().__init__(name)
        self.hotkey = hotkey

    def __str__(self):
        return f'Hotkey({self.hotkey})'

    def run(self):
        keyboard.send(self.hotkey)

class TypeAction(BaseAction):
    def __init__(self, text: str, name: str):
        super().__init__(name)
        self.text = text

    def __str__(self):
        return f'Type({self.text})'

    def run(self):
        keyboard.write(self.text)

class SequentialAction(BaseAction):
    def __init__(self, actions: str, name: str):
        super().__init__(name)
        self.actions = actions

    def __str__(self):
        return f'Sequence(\n  ' + '\n  '.join(map(str, self.actions)) + ')'

    def run(self):
        for a in self.actions:
            time.sleep(0.01)
            a.run()

class ActivateWindowAction(BaseAction):
    def __init__(self, program_path: str, name: str):
        super().__init__(name)
        import pywinauto
        self.program_path = program_path
        self.a = pywinauto.Application(backend='win32', allow_magic_lookup=False)
    
    def __str__(self):
        return f'Activate({self.program_path})'

    def run(self):
        from pywinauto.application import ProcessNotFoundError
        try:
            self.a.connect(path=self.program_path, timeout=0.1)
            self.a.top_window().set_focus()
        except ProcessNotFoundError:
            self.a.start(self.program_path)
            self.a.top_window().set_focus()

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
        return f'Layer({self.name})'
    
    def __repr__(self):
        return str(self)

    @staticmethod
    def from_spec_dict(spec: dict):
        l = Layer(spec['name'])

        if 'application' in spec:
            l.application = spec['application']

        for k, action_spec in spec.items():
            if k not in VALID_KEY_NAMES:
                continue
            
            a = Layer.__parse_action(action_spec)

            if a is None:
                logger.warn("Invalid action: %s", action_spec)
                continue
            l.key_actions[k] = a

        return l

    @staticmethod
    def __parse_action(spec: dict):
        if not isinstance(spec, dict):
            logger.warn("Invalid action: %s", spec)
            return None

        name = ''
        if 'name' in spec and isinstance(spec['name'], str):
            name = spec['name']

        if 'hotkey' in spec:
            return HotkeyAction(spec['hotkey'], name)
        elif 'type' in spec:
            return TypeAction(spec['type'], name)
        elif 'activateWindow' in spec:
            return ActivateWindowAction(spec['activateWindow'], name)
        elif 'sequence' in spec:
            step_specs = spec['sequence']
            step_actions = []
            for s in step_specs:
                a = Layer.__parse_action(s)
                if a is None:
                    return None
                step_actions.append(a)
            return SequentialAction(step_actions, name)

        return None

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
    for i in range(13, 24+1):
        key_name = f'F{i}'
        layer.key_actions[key_name] = HotkeyAction(key_name, key_name)
    return layer

def parse_layers(layer_yaml_file: str) -> Dict[str, Layer]:
    with open(layer_yaml_file, 'r') as f:
        file_content: dict = yaml.load(f)
    
    layers = {}
    for layer_key, layer_spec in file_content.items():
        l = Layer.from_spec_dict(layer_spec)
        layers[layer_key] = l
    return layers
