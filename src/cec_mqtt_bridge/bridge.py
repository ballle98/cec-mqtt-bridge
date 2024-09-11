#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main HDMI CEC MQTT bridge module

Raises:
    ValueError: Invalid config value
    ConnectionError: Failed to connect to MQTT brocker
"""
import configparser as ConfigParser
import logging
import os
import threading
import time
import argparse
import paho.mqtt.client as mqtt

from cec_mqtt_bridge import hdmicec
from cec_mqtt_bridge import lirc_if

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
    'ir': lirc_if.DEFAULT_CONFIGURATION,
}


class Bridge:
    """Main bridge class"""
    def __init__(self, config: dict):
        self.config = config

        # Do some checks
        if (int(self.config['cec']['enabled']) != 1) and \
                (int(self.config['ir']['enabled']) != 1):
            raise ValueError('IR and CEC are both disabled. Can\'t continue.')

        def mqtt_on_message(client: mqtt, userdata, message):
            """Run mqtt callback in a seperate thread."""
            thread = threading.Thread(
                target=self.mqtt_on_message, args=(client, userdata, message))
            thread.start()

        # Setup MQTT
        LOGGER.info("Initialising MQTT...")
        self.mqtt_client = mqtt.Client(self.config['mqtt']['name'])
        self.mqtt_client.on_connect = self.mqtt_on_connect
        self.mqtt_client.on_message = mqtt_on_message
        if self.config['mqtt']['user']:
            self.mqtt_client.username_pw_set(
                self.config['mqtt']['user'],
                password=self.config['mqtt']['password'])
        if int(self.config['mqtt']['tls']) == 1:
            self.mqtt_client.tls_set()
        self.mqtt_client.will_set(
            self.config['mqtt']['prefix'] + '/bridge/status', 'offline', qos=1,
            retain=True)

        tries = 30
        while tries > 0:
            tries -= 1
            try:
                self.mqtt_client.connect(self.config['mqtt']['broker'],
                                         int(self.config['mqtt']['port']), 60)
                break
            except ConnectionRefusedError:
                LOGGER.error("Connection was refused by the server")
            except OSError as err:
                LOGGER.error("OS error: %s", str(err))

            if tries > 0:
                LOGGER.debug("Retrying in 10 seconds... (%d tries left)", tries)
                time.sleep(10)
        else:
            LOGGER.error("Failed to connect to the MQTT broker after multiple attempts")
            raise ConnectionError('MQTT connect retries exhausted. Can\'t continue.')

        self.mqtt_client.loop_start()

        # Setup HDMI-CEC
        if int(self.config['cec']['enabled']) == 1:
            LOGGER.info("Initialising CEC...")
            self.cec_class = hdmicec.HdmiCec(
                port=self.config['cec']['port'],
                name=self.config['cec']['name'],
                devices=[
                    int(x) for x in self.config['cec']['devices'].split(',')],
                mqtt_send=self.mqtt_publish)

        # Setup IR
        if int(self.config['ir']['enabled']) == 1:
            LOGGER.info("Initialising IR...")
            self.ir_class = lirc_if.Lirc(self.mqtt_publish, self.config['ir'])

    @staticmethod
    def load_config(filename='config.ini'):
        """Generate bridge config from config ini file.

        Args:
            filename (str, optional): config ini file. Defaults to 'config.ini'.

        Returns:
            dict: bridge configuration
        """
        config = DEFAULT_CONFIGURATION
        LOGGER.info("Loading config %s", filename)

        # Load all sections and overwrite default configuration
        config_parser = ConfigParser.ConfigParser()
        if config_parser.read(filename):
            for section in config_parser.sections():
                config[section].update(dict(config_parser.items(section)))

        # Override with environment variables
        for section, key_values in config.items():
            for key, value in key_values.items():
                env = os.getenv(section.upper() + '_' + key.upper())
                if env:
                    config[section][key] = type(value)(env)

        return config

    def mqtt_on_connect(self, client: mqtt, _userdata, _flags, ret):
        """MQTT on connect callback

        Args:
            client (mqtt): _description_
            _userdata (_type_): _description_
            _flags (_type_): _description_
            ret (_type_): _description_
        """
        if ret == 0:
            LOGGER.info("Connected successfully")
        else:
            LOGGER.error("Connection failed with code %d", ret)

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
        """Publish a MQTT message prefixed with bridge prefix

        Args:
            topic (str): The topic that the message should be published on
            message (_type_, optional): _description_. Defaults to None.
            qos (int, optional): _description_. Defaults to 0.
            retain (bool, optional): _description_. Defaults to True.
        """
        LOGGER.debug('Send to topic %s: %s', topic, message)
        self.mqtt_client.publish(
            self.config['mqtt']['prefix'] + '/' + topic, message, qos=qos,
            retain=retain)

    def mqtt_on_message(self, _client: mqtt, _userdata, message):
        """Process message on subscibed MQTT topic

        Args:
            _client (mqtt): Not Used
            _userdata (_type_): Not Used
            message (_type_): topic and payload

        Raises:
            ValueError: _description_
            ValueError: _description_
            ValueError: _description_
        """
        # Decode topic and split off the prefix
        topic = message.topic.replace(self.config['mqtt']['prefix'], '').split('/')[1:]
        action = message.payload.decode()
        LOGGER.debug("Command received: %s (%s)", topic, message.payload)

        if topic[0] == 'cec':

            if topic[1] == 'device':
                device = int(topic[2])
                if topic[3] == 'power':
                    if action == 'on':
                        self.cec_class.power_on(device)
                    elif action == 'standby':
                        self.cec_class.power_off(device)
                    else:
                        raise ValueError(f"Unknown power command: {topic} {action}")

            elif topic[1] == 'audio':
                if topic[2] == 'volume':
                    if action == 'up':
                        self.cec_class.volume_up()
                    elif action == 'down':
                        self.cec_class.volume_down()
                    elif action.isdigit() and int(action) <= 100:
                        self.cec_class.volume_set(int(action))
                    else:
                        raise ValueError(f"Unknown power command: {topic} {action}")

                if topic[2] == 'mute':
                    if action == 'on':
                        self.cec_class.volume_mute()
                    elif action == 'off':
                        self.cec_class.volume_unmute()
                    else:
                        raise ValueError(f"Unknown power command: {topic} {action}")

            elif topic[1] == 'tx':
                commands = message.payload.decode().split(',')
                for command in commands:
                    self.cec_class.tx_command(command)

            elif topic[1] == 'refresh':
                self.cec_class.refresh()

            elif topic[1] == 'scan':
                self.cec_class.scan()

        elif topic[0] == 'ir':
            if topic[2] == 'tx':
                self.ir_class.ir_send(topic[1], action)


    def cleanup(self):
        """Terminates the connection."""
        if int(self.config['ir']['enabled']) == 1:
            LOGGER.info("Cleanup IR...")
            self.ir_class.stop_event.set()
            self.ir_class.lirc_thread.join()
        self.mqtt_client.loop_stop()
        self.mqtt_publish('bridge/status', 'offline', qos=1, retain=True)
        self.mqtt_client.disconnect()

def main():
    """main for cec_mqtt_bridge"""
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
    elif os.path.isfile('/etc/cec-mqtt-bridge.ini'):
        config_file = '/etc/cec-mqtt-bridge.ini'
    else:
        config_file = 'config.ini'

    config = Bridge.load_config(config_file)
    if args.cec:
        config['cec']['enabled'] = 1

    if args.ir:
        config['ir']['enabled'] = 1

    if args.refreshtime is not None:
        config['cec']['refresh'] = str(args.refreshtime)

    bridge = Bridge(config)

    refresh_delay = int(bridge.config['cec']['refresh'])
    if 0 < refresh_delay < 10:
        refresh_delay = 10

    LOGGER.debug("refresh delay %d", refresh_delay)

    try:
        while True:
            # Refresh CEC state
            if (int(bridge.config['cec']['enabled']) == 1) and bridge.cec_class and refresh_delay:
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
