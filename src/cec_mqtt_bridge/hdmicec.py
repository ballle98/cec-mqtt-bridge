#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import cec
import logging
import math
import re
import threading
import time
from typing import List

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIGURATION = {
    'enabled': 0,
    'port': 'RPI',
    'devices': '0,1,2,3,4,5,6,7,8,9,10,11,12,13,14',
    'name': 'CEC Bridge',
    'refresh': '10'
}


class HdmiCec:

    def __init__(self, port: str, name: str, devices: List[int], mqtt_send: callable):
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
        if not self.cec_client.Open(port):
            raise Exception("Could not connect to cec adapter")

        self.device_id = self.cec_client.GetLogicalAddresses().primary
        LOGGER.info('Connected to HDMI-CEC with ID %d', self.device_id)
        self.scan()

    def _on_log_callback(self, level, time, message):
        level_map = {
            cec.CEC_LOG_ERROR: 'ERROR',
            cec.CEC_LOG_WARNING: 'WARNING',
            cec.CEC_LOG_NOTICE: 'NOTICE',
            cec.CEC_LOG_TRAFFIC: 'TRAFFIC',
            cec.CEC_LOG_DEBUG: 'DEBUG',
        }
        LOGGER.debug('LOG: [%s] %s', level_map.get(level), message)

        if ((level == cec.CEC_LOG_TRAFFIC) and (not self.refreshing)):

            # Send raw command to mqtt
            m = re.search('>> ([0-9a-f:]+)', message)
            if m:
                self._mqtt_send('cec/rx', m.group(1))

            # :TODO: move to on_command Report Power Status
            m = re.search('>> ([0-9a-f])[0-9a-f]:90:([0-9a-f]{2})', message)
            if m:
                device = int(m.group(1), 16)
                if (m.group(2) == '00') or (m.group(2) == '02'):
                    power = 'on'
                else:
                    power = 'standby'
                self._mqtt_send('cec/device/%d/power' % device, power)
                return

            # # Device Vendor ID
            # m = re.search('>> ([0-9a-f])[0-9a-f]:87', message)
            # if m:
            #     device = int(m.group(1), 16)
            #     self._mqtt_send('cec/power/%d/status' % device, 'on')
            #     return

            # # Report Physical Address
            # m = re.search('>> ([0-9a-f])[0-9a-f]:84', message)
            # if m:
            #     device = int(m.group(1), 16)
            #     self._mqtt_send('cec/power/%d/status' % device, 'on')
            #     return

            # Report Audio Status
            m = re.search('>> ([0-9a-f])[0-9a-f]:7a:([0-9a-f]{2})', message)
            if m:
                audio_status = int(m.group(2), 16)
                mute, volume = self.decode_volume(audio_status)
                self._mqtt_send('cec/audio/volume', volume)
                self._mqtt_send('cec/audio/mute', 'on' if mute else 'off')
                self.volume_update.set()  # notify we have a volume update
                return

    # key press callback
    def _on_key_press_callback(self, key, duration):
      LOGGER.debug('_on_key_press_callback')
      return self.cec_client.KeyPressCallback(key, duration)
    
    # command callback
    def _on_command_callback(self, cmd):
      LOGGER.debug('_on_command_callback %s', cmd)
      return self.cec_client.CommandCallback(cmd)

    def power_on(self, device: int):
        """Power on the specified device."""
        LOGGER.debug('Power on device %d', device)
        self._mqtt_send('cec/device/%d/power' % device, 'on')
        self.cec_client.PowerOnDevices(device)

    def power_off(self, device: int):
        """Power off the specified device."""
        LOGGER.debug('Power off device %d', device)
        self._mqtt_send('cec/device/%d/power' % device, 'standby')
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
            LOGGER.debug('Attempt %d to set volume' % attempts)

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
            LOGGER.debug('Difference in volume is %s' % diff)

            if diff >= 10:
                diff = math.ceil(diff / 2)
                LOGGER.debug('Changing fast with %s' % diff)
                for i in range(diff):
                    if current_volume < requested_volume:
                        self.cec_client.VolumeUp(i == diff - 1)
                    elif current_volume > requested_volume:
                        self.cec_client.VolumeDown(i == diff - 1)
            else:
                LOGGER.debug('Changing slow with %s' % diff)
                for i in range(diff):
                    if current_volume < requested_volume:
                        self.cec_client.VolumeUp()
                    elif current_volume > requested_volume:
                        self.cec_client.VolumeDown()
                    time.sleep(0.1)

            attempts += 1

        self.setting_volume = False

    def decode_volume(self, audio_status) -> tuple[bool, int]:
        mute = audio_status > 127
        volume = audio_status - 128 if mute else audio_status
        real_volume = int(math.ceil(volume * self.volume_correction))

        LOGGER.debug('Audio Status = %s -> Mute = %s, Volume = %s, Real Volume = %s', audio_status, mute, volume, real_volume)
        return mute, real_volume

    def tx_command(self, command: str, device: int = None):
        """Send a raw CEC command to the specified device."""
        if device is None:
            full_command = command
        else:
            full_command = '%s:%s' % (format(self.device_id * 16 + device, 'x'), command)

        LOGGER.debug('Sending %s' % full_command)
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
            physicalAddress = self.cec_client.GetDevicePhysicalAddress(device)
            if (physicalAddress != 0xFFFF) :
                power = self.cec_client.GetDevicePowerStatus(device)
                powerStr = self.cec_client.PowerStatusToString(power)
                LOGGER.debug('device %d %04x %-12s power %d %s', device, physicalAddress,
                            self.cec_client.LogicalAddressToString(device), power,
                            powerStr)
                self._mqtt_send('cec/device/%d/power' % device, powerStr)
        
        # Ask AVR to send us an audio status update
        mute, volume = self.decode_volume(self.cec_client.AudioStatus())
        self._mqtt_send('cec/audio/volume', volume)
        self._mqtt_send('cec/audio/mute', 'on' if mute else 'off')
        self.refreshing = False

    def scan(self):
        LOGGER.debug("requesting CEC bus information ...")
        self.refreshing = True
        for device in self.devices:
            # Get power status values of discovered devices from ceclib
            # This will setting unknown power state when device does not respond.
            physicalAddress = self.cec_client.GetDevicePhysicalAddress(device)
            if (physicalAddress != 0xFFFF) :
                vendorId        = self.cec_client.GetDeviceVendorId(device)
                physicalAddress = self.cec_client.GetDevicePhysicalAddress(device)
                active          = self.cec_client.IsActiveSource(device)
                cecVersion      = self.cec_client.GetDeviceCecVersion(device)
                power           = self.cec_client.GetDevicePowerStatus(device)
                osdName         = self.cec_client.GetDeviceOSDName(device)

                self._mqtt_send('cec/device/%d/type' % device, self.cec_client.LogicalAddressToString(device))
                self._mqtt_send('cec/device/%d/address' % device, str(physicalAddress))
                self._mqtt_send('cec/device/%d/active' % device, str(active))
                self._mqtt_send('cec/device/%d/vendor' % device, self.cec_client.VendorIdToString(vendorId))
                self._mqtt_send('cec/device/%d/osd' % device, osdName)
                self._mqtt_send('cec/device/%d/cecver' % device, self.cec_client.CecVersionToString(cecVersion))
                self._mqtt_send('cec/device/%d/power' % device, self.cec_client.PowerStatusToString(power))

        # Ask AVR to send us an audio status update
        mute, volume = self.decode_volume(self.cec_client.AudioStatus())
        self._mqtt_send('cec/audio/volume', volume)
        self._mqtt_send('cec/audio/mute', 'on' if mute else 'off')
        self.refreshing = False
