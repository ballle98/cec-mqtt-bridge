#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import configparser as ConfigParser
import logging
import os
import threading
import time
import paho.mqtt.client as mqtt
import argparse

from cec_mqtt_bridge import hdmicec
from cec_mqtt_bridge import lirc

LOGGER = logging.getLogger('bridge')

# Default configuration
DEFAULT_CONFIGURATION = {
    'mqtt': {
        'broker': 'localhost',
        'name': 'CEC Bridge',
        'port': 1883,
        'prefix': 'media',
        'user': '',
        'password': '',
        'tls': 0,
    },
    'cec': hdmicec.DEFAULT_CONFIGURATION,
    'ir': lirc.DEFAULT_CONFIGURATION,
}


class Bridge:

    def __init__(self, config_file: str):
        self.config = self._load_config(config_file)

        # Do some checks
        if (not int(self.config['cec']['enabled']) == 1) and \
                (not int(self.config['ir']['enabled']) == 1):
            raise Exception('IR and CEC are both disabled. Can\'t continue.')

        def mqtt_on_message(client: mqtt, userdata, message):
            """Run mqtt callback in a seperate thread."""
            thread = threading.Thread(target=self.mqtt_on_message, args=(client, userdata, message))
            thread.start()

        # Setup MQTT
        LOGGER.info("Initialising MQTT...")
        self.mqtt_client = mqtt.Client(self.config['mqtt']['name'])
        self.mqtt_client.on_connect = self.mqtt_on_connect
        self.mqtt_client.on_message = mqtt_on_message
        if self.config['mqtt']['user']:
            self.mqtt_client.username_pw_set(self.config['mqtt']['user'], password=self.config['mqtt']['password']);
        if int(self.config['mqtt']['tls']) == 1:
            self.mqtt_client.tls_set()
        self.mqtt_client.will_set(self.config['mqtt']['prefix'] + '/bridge/status', 'offline', qos=1, retain=True)
        self.mqtt_client.connect(self.config['mqtt']['broker'], int(self.config['mqtt']['port']), 60)
        self.mqtt_client.loop_start()

        # Setup HDMI-CEC
        if int(self.config['cec']['enabled']) == 1:
            self.cec_class = hdmicec.HdmiCec(port=self.config['cec']['port'],
                                             name=self.config['cec']['name'],
                                             devices=[int(x) for x in self.config['cec']['devices'].split(',')],
                                             mqtt_send=self.mqtt_publish)

        # Setup IR
        if int(self.config['ir']['enabled']) == 1:
            self.ir_class = lirc.Lirc(mqtt_send=self.mqtt_publish)

    @staticmethod
    def _load_config(filename='config.ini'):
        config = DEFAULT_CONFIGURATION
        LOGGER.info("Loading config %s", filename)

        try:
            # Load all sections and overwrite default configuration
            config_parser = ConfigParser.ConfigParser()
            if config_parser.read(filename):
                for section in config_parser.sections():
                    config[section].update(dict(config_parser.items(section)))

            # Override with environment variables
            for section in config:
                for key, value in config[section].items():
                    env = os.getenv(section.upper() + '_' + key.upper());
                    if env:
                        config[section][key] = type(value)(env)

        except Exception as e:
            raise Exception("Could not configure: %s" % str(e))

        return config

    def mqtt_on_connect(self, client: mqtt, userdata, flags, rc):
        # Subscribe to CEC commands
        if int(self.config['cec']['enabled']) == 1:
            client.subscribe([
                (self.config['mqtt']['prefix'] + '/cec/device/+/power/set', 0),
                (self.config['mqtt']['prefix'] + '/cec/audio/volume/set', 0),
                (self.config['mqtt']['prefix'] + '/cec/audio/mute/set', 0),
                (self.config['mqtt']['prefix'] + '/cec/tx', 0),
                (self.config['mqtt']['prefix'] + '/cec/refresh', 0),
                (self.config['mqtt']['prefix'] + '/cec/scan', 0)
            ])

        # Subscribe to IR commands
        if int(self.config['ir']['enabled']) == 1:
            client.subscribe([
                (self.config['mqtt']['prefix'] + '/ir/+/tx', 0)
            ])

        # Publish birth message
        self.mqtt_publish('bridge/status', 'online', qos=1, retain=True)

    def mqtt_publish(self, topic, message=None, qos=0, retain=True):
        """Publish a MQTT message"""
        LOGGER.debug('Send to topic %s: %s', topic, message)
        self.mqtt_client.publish(self.config['mqtt']['prefix'] + '/' + topic, message, qos=qos, retain=retain)

    def mqtt_on_message(self, client: mqtt, userdata, message):

        # Decode topic and split off the prefix
        topic = message.topic.replace(self.config['mqtt']['prefix'], '').split('/')[1:]
        action = message.payload.decode()
        LOGGER.debug("Command received: %s (%s)" % (topic, message.payload))

        if topic[0] == 'cec':

            if topic[1] == 'device':
                device = int(topic[2])
                if topic[3] == 'power':
                    if action == 'on':
                        self.cec_class.power_on(device)
                        return
                    if action == 'standby':
                        self.cec_class.power_off(device)
                        return
                    raise Exception("Unknown power command: %s (%s)" % (topic, action))

            if topic[1] == 'audio':
                if topic[2] == 'volume':
                    if action == 'up':
                        self.cec_class.volume_up()
                        return
                    if action == 'down':
                        self.cec_class.volume_down()
                        return
                    if action.isdigit() and int(action) <= 100:
                        self.cec_class.volume_set(int(action))
                        return
                    raise Exception("Unknown volume command: %s (%s)" % (topic, action))

                if topic[2] == 'mute':
                    if action == 'on':
                        self.cec_class.volume_mute()
                        return
                    if action == 'off':
                        self.cec_class.volume_unmute()
                        return
                    raise Exception("Unknown mute command: %s (%s)" % (topic, action))

            if topic[1] == 'tx':
                commands = message.payload.decode().split(',')
                for command in commands:
                    self.cec_class.tx_command(command)
                return
            
            if topic[1] == 'refresh':
                self.cec_class.refresh()
                return

            if topic[1] == 'scan':
                self.cec_class.scan()
                return

    def cleanup(self):
        """Terminates the connection."""
        self.mqtt_client.loop_stop()
        self.mqtt_publish('bridge/status', 'offline', qos=1, retain=True)
        self.mqtt_client.disconnect()

def main():
    parser = argparse.ArgumentParser(description='HDMI-CEC and IR to MQTT bridge')
    parser.add_argument('-v', '--verbose', action='count', help="increase output verbosity")
    parser.add_argument('-f', '--configfile')
    parser.add_argument('-c', '--cec', action="store_true", help="enable CEC")
    parser.add_argument('-i', '--ir', action="store_true", help="enable IR")
    parser.add_argument('-t', '--refreshtime', type=int)

    args = parser.parse_args()
    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG

    logging.basicConfig(level=log_level, format='%(asctime)s [%(name)s] %(funcName)s: %(message)s')

    if args.configfile:
        config_file = args.configfile
    elif (os.path.isfile('/etc/cec-mqtt-bridge.ini')):
        config_file = '/etc/cec-mqtt-bridge.ini'
    else:
        config_file = 'config.ini'
    
    bridge = Bridge(config_file)

    if args.refreshtime is not None:
        bridge.config['cec']['refresh'] = str(args.refreshtime)

    refresh_delay = int(bridge.config['cec']['refresh'])
    if (refresh_delay > 0 ) and (refresh_delay < 10):
        refresh_delay = 10
    
    LOGGER.debug("refresh delay %d", refresh_delay)
    
    try:
        while True:
            # Refresh CEC state
            if bridge.cec_class and refresh_delay:
                bridge.cec_class.refresh()
                time.sleep(refresh_delay)
            else:
                time.sleep(3600)

    except KeyboardInterrupt:
        bridge.cleanup()

    except RuntimeError:
        bridge.cleanup()

if __name__ == '__main__':
    main()
