from typing import Dict, List
import hal
import time
import logging
from macros import Layer, create_default_layer, parse_layers
from active_window import ActiveWindowListener
from os.path import basename


logger = logging.getLogger(__name__)


class Macropadd():
    def __init__(self):
        self.active_layers: List[Layer] = []
        self.all_layers: Dict[str, Layer]  = {}
        self.hal = hal.Hal()
        self.last_encoder_rot = 0

    def run(self):
        self.all_layers = parse_layers('layers.yaml')
        self.active_layers = [create_default_layer()]

        if 'base' in self.all_layers:
            self.active_layers.append(self.all_layers['base'])

        try:
            h = hal.Hal()
            h.key_event_handler = self.handle_key_event
            h.encoder_handler = self.handle_encoder_event

            l = ActiveWindowListener(self.handle_process_change)
            l.listen_forever()

            time.sleep(100000)

        except KeyboardInterrupt:
            h.close()

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
    logging.basicConfig(level=logging.DEBUG)
    m = Macropadd()

    m.run()



if __name__ == '__main__':
    main()