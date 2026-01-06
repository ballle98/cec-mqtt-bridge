#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HDMI CEC interface to HDMI CEC MQTT bridge"""

import logging
import math
import re
import threading
import time
import os
from typing import List
try:
    import cec
except ModuleNotFoundError:
    cec = None

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIGURATION = {
    'enabled': 0,
    'port': '',
    'devices': '0,1,2,3,4,5,6,7,8,9,10,11,12,13,14',
    'name': 'CEC Bridge',
    'refresh': '10'
}


class HdmiCec:
    """HDMI CEC interface class"""
    def __init__(self, port: str, name: str, devices: List[int], mqtt_send: callable):
        if cec is None:
            raise RuntimeError("CEC support is not available (python-cec not installed).")
        self._mqtt_send = mqtt_send
        self.devices = devices
        self.volume_correction = 1  # 80/100 = max volume of avr / reported max volume

        self.setting_volume = False
        self.refreshing = False
        self.volume_update = threading.Event()
        self.volume_update.clear()

        self.cec_config = cec.libcec_configuration()
        self.cec_config.strDeviceName = name
        self.cec_config.bActivateSource = 0
        self.cec_config.deviceTypes.Add(cec.CEC_DEVICE_TYPE_RECORDING_DEVICE)
        self.cec_config.clientVersion = cec.LIBCEC_VERSION_CURRENT
        self.cec_config.SetLogCallback(self._on_log_callback)
        self.cec_config.SetKeyPressCallback(self._on_key_press_callback)
        self.cec_config.SetCommandCallback(self._on_command_callback)

        # Open connection
        self.cec_client = cec.ICECAdapter.Create(self.cec_config)  # type: cec.ICECAdapter
        if not port:
            if os.path.exists('/dev/cec0'):
                port = '/dev/cec0'
            else:
                port = 'RPI'

        LOGGER.info('Opening HDMI-CEC device %s', port)
        if not self.cec_client.Open(port):
            raise ConnectionError(f"Could not connect to CEC adapter {port}")

        self.device_id = self.cec_client.GetLogicalAddresses().primary
        LOGGER.info('Connected to HDMI-CEC with ID %d', self.device_id)
        self.scan()

    def _on_log_callback(self, level, _time, message):
        level_map = {
            cec.CEC_LOG_ERROR: 'ERROR',
            cec.CEC_LOG_WARNING: 'WARNING',
            cec.CEC_LOG_NOTICE: 'NOTICE',
            cec.CEC_LOG_TRAFFIC: 'TRAFFIC',
            cec.CEC_LOG_DEBUG: 'DEBUG',
        }
        LOGGER.debug('LOG: [%s] %s', level_map.get(level), message)

        if not self.refreshing:
            # TV (0): power status changed from 'unknown' to 'on'
            match = re.search(
                r'\(([0-9a-fA-F])\): power status changed from \'.*\' to \'(.*)\'',
                message)
            if match:
                device = int(match.group(1),16)
                power = match.group(2)
                self._mqtt_send(f'cec/device/{device}/power', power)


    # key press callback
    def _on_key_press_callback(self, key, duration):
        LOGGER.debug('_on_key_press_callback %s %s', key, duration)
        return self.cec_client.KeyPressCallback(key, duration)

    # command callback
    # https://github.com/Pulse-Eight/libcec/blob/master/include/cectypes.h
    # https://www.hdmi.org/docs/Hdmi13aSpecs

    def _on_command_callback(self, cmd):
        initiator = int(cmd[3:4], base=16)
        destination = int(cmd[4:5], base=16)
        opcode = int(cmd[6:8], base=16)
        LOGGER.debug('_on_command_callback %02x %s %x -> %x %s',
                     opcode, self.cec_client.OpcodeToString(opcode), initiator,
                     destination, cmd)
        # Send raw command to mqtt
        self._mqtt_send('cec/rx', cmd[3:])

        if not self.refreshing:
            if opcode == cec.CEC_OPCODE_REPORT_POWER_STATUS:
                power = int(cmd[9:], base=16)
                self._mqtt_send(f'cec/device/{initiator}/power',
                                self.cec_client.PowerStatusToString(power))
            elif opcode == cec.CEC_OPCODE_DEVICE_VENDOR_ID:
                vendor_id = int((cmd[9:]).replace(':',''), base=16)
                self._mqtt_send(f'cec/device/{initiator}/vendor',
                                self.cec_client.VendorIdToString(vendor_id))
            elif opcode == cec.CEC_OPCODE_REPORT_PHYSICAL_ADDRESS:
                physical_address = int((cmd[9:14]).replace(':',''), base=16)
                self._mqtt_send(f'cec/device/{initiator}/address',
                                 f'{physical_address:04x}')
            elif opcode == cec.CEC_OPCODE_REPORT_AUDIO_STATUS:
                mute, volume = self.decode_volume(int(cmd[9:], base=16))
                self._mqtt_send('cec/audio/volume', volume)
                self._mqtt_send('cec/audio/mute', 'on' if mute else 'off')
            elif opcode == cec.CEC_OPCODE_SET_SYSTEM_AUDIO_MODE:
                if int(cmd[9:], base=16) == 1:
                    self._mqtt_send('cec/device/5/power', 'on')
                else:
                    self._mqtt_send('cec/device/5/power', 'standby')

        return self.cec_client.CommandCallback(cmd)

    def power_on(self, device: int):
        """Power on the specified device."""
        LOGGER.debug('Power on device %d', device)
        self._mqtt_send(f'cec/device/{device}/power', 'on')
        self.cec_client.PowerOnDevices(device)

    def power_off(self, device: int):
        """Power off the specified device."""
        LOGGER.debug('Power off device %d', device)
        self._mqtt_send(f'cec/device/{device}/power', 'standby')
        self.cec_client.StandbyDevices(device)

    def volume_up(self, amount=1, update=True):
        """Increase the volume on the AVR."""
        if amount >= 10:
            LOGGER.debug('Volume up fast with %d', amount)
            for i in range(amount):
                self.cec_client.VolumeUp(i == amount - 1)
                time.sleep(0.1)
        else:
            LOGGER.debug('Volume up with %d', amount)
            for i in range(amount):
                self.cec_client.VolumeUp()
                time.sleep(0.1)

        if update:
            # Ask AVR to send us an update
            self.tx_command('71', 5)

    def volume_down(self, amount=1, update=True):
        """Decrease the volume on the AVR."""
        if amount >= 10:
            LOGGER.debug('Volume down fast with %d', amount)
            for i in range(amount):
                self.cec_client.VolumeDown(i == amount - 1)
                time.sleep(0.1)
        else:
            LOGGER.debug('Volume down with %d', amount)
            for i in range(amount):
                self.cec_client.VolumeDown()
                time.sleep(0.1)

        if update:
            # Ask AVR to send us an update
            self.tx_command('71', 5)

    def volume_mute(self):
        """Mute the volume on the AVR."""
        LOGGER.debug('Mute AVR')
        self._mqtt_send('cec/audio/mute', 'on')
        self.cec_client.AudioMute()

    def volume_unmute(self):
        """Unmute the volume on the AVR."""
        LOGGER.debug('Unmute AVR')
        self._mqtt_send('cec/audio/mute', 'off')
        self.cec_client.AudioUnmute()

    def volume_set(self, requested_volume: int):
        """Set the volume to the AVR."""
        LOGGER.debug('Set volume to %d', requested_volume)
        self.setting_volume = True

        attempts = 0
        while attempts < 10:
            LOGGER.debug('Attempt %d to set volume', attempts)

            # Ask AVR to send us an update about its volume
            self.volume_update.clear()
            self.tx_command('71', device=5)

            # Wait for this update to arrive
            LOGGER.debug('Waiting for response...')
            if not self.volume_update.wait(0.2):
                LOGGER.warning('No response received. Retrying...')
                continue

            # Read the update
            _, current_volume = self.decode_volume(self.cec_client.AudioStatus())
            if current_volume == requested_volume:
                break

            diff = abs(current_volume - requested_volume)
            LOGGER.debug('Difference in volume is %s', diff)

            if diff >= 10:
                diff = math.ceil(diff / 2)
                LOGGER.debug('Changing fast with %d', diff)
                for i in range(diff):
                    if current_volume < requested_volume:
                        self.cec_client.VolumeUp(i == diff - 1)
                    elif current_volume > requested_volume:
                        self.cec_client.VolumeDown(i == diff - 1)
            else:
                LOGGER.debug('Changing slow with %d', diff)
                for i in range(diff):
                    if current_volume < requested_volume:
                        self.cec_client.VolumeUp()
                    elif current_volume > requested_volume:
                        self.cec_client.VolumeDown()
                    time.sleep(0.1)

            attempts += 1

        self.setting_volume = False

    def decode_volume(self, audio_status) -> tuple[bool, int]:
        """Decodes CEC audio status into mut and real volume

        Args:
            audio_status (int): CEC audio status

        Returns:
            tuple[bool, int]: mute, real volume
        """
        mute = audio_status > 127
        volume = audio_status - 128 if mute else audio_status
        real_volume = int(math.ceil(volume * self.volume_correction))

        LOGGER.debug('Audio Status = %s -> Mute = %s, Volume = %s, Real Volume = %s',
                     audio_status, mute, volume, real_volume)
        return mute, real_volume

    def tx_command(self, command: str, device: int = None):
        """Send a raw CEC command to the specified device."""
        if device is None:
            full_command = command
        else:
            full_command = f'{self.device_id * 16 + device:x}:{command}'

        LOGGER.debug('Sending %s', full_command)
        self.cec_client.Transmit(self.cec_client.CommandFromString(full_command))

    def refresh(self):
        """Refresh the audio status and power status."""
        # :TODO: This operation takes ~2 sec should it be done in seperate thread?
        if self.setting_volume:
            return

        LOGGER.debug('Refreshing HDMI-CEC...')
        self.refreshing = True
        for device in self.devices:
            # Get power status values of discovered devices from ceclib
            # This will setting unknown power state when device does not respond.
            physical_address = self.cec_client.GetDevicePhysicalAddress(device)
            if physical_address != 0xFFFF:
                power = self.cec_client.GetDevicePowerStatus(device)
                power_str = self.cec_client.PowerStatusToString(power)
                LOGGER.debug('device %d %04x %-12s power %d %s', device, physical_address,
                            self.cec_client.LogicalAddressToString(device), power,
                            power_str)
                self._mqtt_send(f'cec/device/{device}/power', power_str)

        # Ask AVR to send us an audio status update
        mute, volume = self.decode_volume(self.cec_client.AudioStatus())
        self._mqtt_send('cec/audio/volume', volume)
        self._mqtt_send('cec/audio/mute', 'on' if mute else 'off')
        self.refreshing = False

    def scan(self):
        """scan for devices on the HDMI CEC bus"""
        LOGGER.debug("requesting CEC bus information ...")
        self.refreshing = True
        for device in self.devices:
            # Get power status values of discovered devices from ceclib
            # This will setting unknown power state when device does not respond.
            physical_address = self.cec_client.GetDevicePhysicalAddress(device)
            if physical_address != 0xFFFF :
                vendor_id        = self.cec_client.GetDeviceVendorId(device)
                physical_address = self.cec_client.GetDevicePhysicalAddress(device)
                active           = self.cec_client.IsActiveSource(device)
                cec_version      = self.cec_client.GetDeviceCecVersion(device)
                power            = self.cec_client.GetDevicePowerStatus(device)
                osd_name         = self.cec_client.GetDeviceOSDName(device)

                self._mqtt_send(f'cec/device/{device}/type',
                                self.cec_client.LogicalAddressToString(device))
                self._mqtt_send(f'cec/device/{device}/address',
                                f'{physical_address:04x}')
                self._mqtt_send(f'cec/device/{device}/active',
                                str(active))
                self._mqtt_send(f'cec/device/{device}/vendor',
                                self.cec_client.VendorIdToString(vendor_id))
                self._mqtt_send(f'cec/device/{device}/osd', osd_name)
                self._mqtt_send(f'cec/device/{device}/cecver',
                                self.cec_client.CecVersionToString(cec_version))
                self._mqtt_send(f'cec/device/{device}/power',
                                self.cec_client.PowerStatusToString(power))

        # Ask AVR to send us an audio status update
        mute, volume = self.decode_volume(self.cec_client.AudioStatus())
        self._mqtt_send('cec/audio/volume', volume)
        self._mqtt_send('cec/audio/mute', 'on' if mute else 'off')
        self.refreshing = False
