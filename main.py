from typing import Dict, List
import hal
import time
import logging
from layer import Layer, LayerFileWatcher, create_default_layer, parse_layers
from active_window import get_active_window_listener
from os.path import basename
from threading import Event


logger = logging.getLogger(__name__)


class Macropadd():
    def __init__(self):
        self.active_layers: List[Layer] = []
        self.all_layers: Dict[str, Layer]  = {}
        self.hal = hal.get_hal()
        self.last_encoder_rot = 0
        self.stop_event = Event()

    def set_layers(self, layers: Dict[str, Layer]):
        self.all_layers = layers
        new_active = [create_default_layer()]
        if 'base' in self.all_layers:
            self.active_layers.append(self.all_layers['base'])
        self.active_layers = new_active


    def run(self):
        self.stop_event = Event()
        self.all_layers = parse_layers('layers.yaml')

        LayerFileWatcher('layers.yaml', self.set_layers).start()

        try:
            self.hal.key_event_handler = self.handle_key_event
            self.hal.encoder_handler = self.handle_encoder_event

            l = get_active_window_listener(self.handle_process_change)
            l.listen_forever()

            self.stop_event.wait()

        except KeyboardInterrupt:
            self.hal.close()

    def handle_key_event(self, key: str):
        layers = self.active_layers.copy()
        for l in reversed(layers):
            if l.run_action_for_key(key):
                return
        logger.warn("Unhandled key event for key %s", key)

    def handle_encoder_inc(self):
        layers = self.active_layers.copy()
        for l in reversed(layers):
            if l.run_action_for_encoder_inc():
                return
        logger.warn("Unhandled encoder inc event")

    def handle_encoder_dec(self):
        layers = self.active_layers.copy()
        for l in reversed(layers):
            if l.run_action_for_encoder_dec():
                return
        logger.warn("Unhandled encoder dec event")

    def handle_encoder_event(self, val: int):
        if self.last_encoder_rot < val:
            logger.debug(f'{self.last_encoder_rot=} < {val=}')
            self.handle_encoder_inc()
        else:
            self.handle_encoder_dec()

        self.last_encoder_rot = val

    def handle_encoder_button(self, layers: List[Layer]):
        layers = self.active_layers.copy()
        for l in reversed(layers):
            if l.run_action_for_encoder_btn():
                return
        logger.warn("Unhandled encoder btn event")

    def handle_process_change(self, path):
        new_active = self.active_layers.copy()
        base_layer = self.all_layers.get('base', None)
        if base_layer is not None:
            while len(new_active) > 0 and new_active[-1] != base_layer:
                new_active.pop()
        
        # Get process name from path
        process = basename(path)

        for l in self.all_layers.values():
            if l.application == process:
                new_active.append(l)
                break
        else:
            logger.debug("No layer found for %s", process)

        self.active_layers = new_active
        logger.debug("Active layers: %s", self.active_layers)

        # Use the topmost layer name as the "profile" name
        if self.active_layers:
            profile_name = self.active_layers[-1].name
            self.hal.send_profile_name(profile_name)

            key_names = self.active_layers[0].get_key_names()
            for l in self.active_layers[1:]:
                lkn = l.get_key_names()
                assert len(lkn) == len(key_names)
                for i in range(len(key_names)):
                    if lkn[i] is not None:
                        key_names[i] = lkn[i]
            
            self.hal.send_key_names(key_names)


def main():
    FORMAT = '%(asctime)-15s [%(name)s %(levelname)s] %(message)s'
    logging.basicConfig(level=logging.DEBUG, format=FORMAT)
    m = Macropadd()

    m.run()



if __name__ == '__main__':
    main()