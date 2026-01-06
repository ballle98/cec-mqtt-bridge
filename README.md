cec-mqtt-bridge
===============

A HDMI-CEC and IR to MQTT bridge written in Python 3 for connecting your AV-devices to your Home Automation system. You can control and monitor power status and volume.

# Features
* HDMI-CEC
  * Power control and feedback
  * Volume control (up/down/specific) and feedback
  * Relay HDMI-CEC messages from HDMI to broker (RX)
  * Relay HDMI-CEC messages from broker to HDMI (TX)
* IR
  * Relay IR keypresses from IR to broker (RX)
  * Relay IR keypresses from broker to IR (TX)

# Dependencies

* MQTT broker (like [Mosquitto](https://mosquitto.org/))
  * "apt-get install mosquitto"

* python paho-mqtt module
  * https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html
  * "apt-get install python3-paho-mqtt"

* python HDMI-CEC module
  * libcec4 with python bindings (https://github.com/Pulse-Eight/libcec)
  * **NOTE: cec python package is not available on pypi**
    * "apt-get install python3-cec" OR compile the bindings yourself
  * HDMI-CEC interface device (like a [Pulse-Eight](https://www.pulse-eight.com/) device, or a Raspberry Pi)

* python LIRC module
  * lirc with python bindings (https://www.lirc.org/api-docs/html/group__python__bindings.html)
  * **NOTE: lirc python package is not available on pypi**
    * "apt-get install lirc"
    * "sudo pip install /usr/share/lirc/lirc-*.tar.gz" see #18
    * OR compile & install https://sourceforge.net/p/lirc/git/ci/master/tree/python-pkg/

* lircd + hardware to receive and send IR signals
  * cheep IR RX and TX with transistor https://www.aliexpress.us/item/2251801744452143.html
  * to get RX and TX working see https://github.com/raspberrypi/linux/issues/2993#issuecomment-497420228

# Install on Raspbian bullseye

If there is not a MQTT broker already on your network
```sh
sudo apt-get install mosquitto
```

Install packages and the bridge
```sh
# Base packages
sudo apt-get update
sudo apt-get install build-essential git python3 python3-dev python3-setuptools python3-pip python3-wheel python3-build python3-venv python3-paho-mqtt python3-cec

# Optional: LIRC support (includes build helper for source installs)
sudo apt-get install lirc liblirc-dev liblircclient-dev pkg-config
sudo pip install /usr/share/lirc/lirc-*.tar.gz

# Install the bridge
git clone https://github.com/ballle98/cec-mqtt-bridge.git
cd cec-mqtt-bridge/contrib/
./debian-ubuntu-install.sh
sudo vi /etc/cec-mqtt-bridge.ini
sudo systemctl restart cec-mqtt-bridge
```

to update

```sh
cd cec-mqtt-bridge/
git pull
./contrib/debian-ubuntu-install.sh
```


# MQTT Topics

The bridge subscribes to the following topics:

| topic                       | body                                    | remark                                                                    |
|:----------------------------|-----------------------------------------|---------------------------------------------------------------------------|
| `prefix`/cec/device/`laddr`/power/set | `on` / `standby`              | Turn on/standby device with with logical address `laddr` (0-14).  |
| `prefix`/cec/device/`laddr`/active/set | `yes` / `no`                 | activate/deactivate device with with logical address `laddr` (0-14).  |
| `prefix`/cec/audio/volume/set     | `integer (0-100)` / `up` / `down` | Sets the volume level of the audio system to a specific level or up/down. |
| `prefix`/cec/audio/mute/set       | `on` / `off`                      | Mute/Unmute the the audio system.                                         |
| `prefix`/cec/tx             | `commands`                              | Send the specified `commands` to the CEC bus. You can specify multiple commands by separating them with a space. Example: `cec/tx 15:44:41,15:45`. |
| `prefix`/ir/`remote`/tx     | `key`                                   | Send the specified `key` of `remote` to the IR transmitter.               |

The bridge publishes to the following topics:

| topic                          | body                                    | remark                                           |
|:-------------------------------|-----------------------------------------|--------------------------------------------------|
| `prefix`/bridge/status               | `online` / `offline`                    | Report availability status of the bridge.        |
| `prefix`/cec/device/`laddr`/type     | `on` / `off`                            | Report type of device with logical address `laddr` (0-14).      |
| `prefix`/cec/device/`laddr`/address  | `on` / `off`                            | Report physical address of device with logical address `laddr` (0-14).  |
| `prefix`/cec/device/`laddr`/active   | `yes` / `no`                            | Report active source status of device with logical address `laddr` (0-14).  |
| `prefix`/cec/device/`laddr`/vendor   | `string`                            | Report vendor of device with logical address `laddr` (0-14).  |
| `prefix`/cec/device/`laddr`/osd      | `string`                            | Report OSD of device with logical address `laddr` (0-14).  |
| `prefix`/cec/device/`laddr`/cecver   | `string`                            | Report CEC version of device with logical address `laddr` (0-14).  |
| `prefix`/cec/device/`laddr`/power    | `on` / `standby` / `toon` / `tostandby` / `unknown` | Report power status of device with logical address `laddr` (0-14).      |
| `prefix`/cec/device/`laddr`/language | `string`                            | Report langauge of device with logical address `laddr` (0-14).  |
| `prefix`/cec/audio/volume     | `integer (0-100)` /  `unknown = 127`                      | Report volume level of the audio system.         |
| `prefix`/cec/mute/status       | `on` / `off`                            | Report mute status of the audio system.          |
| `prefix`/cec/rx                | `command`                               | Notify that `command` was received.              |
| `prefix`/ir/`remote`/rx        | `key`                                   | Notify that `key` of `remote` was received. You have to configure `key` AND `remote` as config in the lircrc file.  |
| `prefix`/ir/rx                 | `key`                                   | Notify that `key` was received. You have to configure `key` in the lircrc file. This format is used if the remote is not given in the config file.  |

`id` is the address (0-15) of the device on the CEC-bus.

## Examples
* `mosquitto_pub -t media/cec/volup -m ''`
* `mosquitto_pub -t media/cec/tx -m '15:44:42,15:45'`

# Configuration

You can either copy `config.default.ini` to `config.ini` and adjust its properties, or alternatively declare any of those as environment variables using the format `SECTION_KEY` (e.g., `MQTT_USER`).


# Interesting links
* https://github.com/nvella/mqtt-cec
* http://www.cec-o-matic.com/
* https://kwikwai.com/knowledge-base/the-hdmi-cec-bus/
* https://www.hdmi.org/docs/Hdmi13aSpecs
* https://github.com/Pulse-Eight/libcec/blob/master/include/cec.h
* https://github.com/Pulse-Eight/libcec/blob/master/src/pyCecClient/pyCecClient.py
* https://github.com/ballle98/cec-lirc
