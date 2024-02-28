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

* MQTT (required)
  * MQTT broker (like [Mosquitto](https://mosquitto.org/))

* HDMI-CEC (optional)
  * libcec4 with python bindings (https://github.com/Pulse-Eight/libcec)
    * You can compile the bindings yourself, or use precompiled packages from my [libcec directory](libcec/).
  * HDMI-CEC interface device (like a [Pulse-Eight](https://www.pulse-eight.com/) device, or a Raspberry Pi)

* IR (optional)
  * lirc + hardware to receive and send IR signals
  * python-lirc (https://pypi.python.org/pypi/python-lirc/)

# Install on Raspbian bullseye

```sh
apt-get update
apt-get install build-essential git lirc python3 python3-dev python3-setuptools python3-pip python3-wheel python3-build python3-venv python3-paho-mqtt python3-cec
git clone https://github.com/michaelarnauts/cec-mqtt-bridge.git
cd cec-mqtt-bridge/
python3 -m build
sudo pip install dist/cec_mqtt_bridge-*.whl
cp config.ini.default config.ini
vi config.ini
```


# MQTT Topics

The bridge subscribes to the following topics:

| topic                       | body                                    | remark                                                                    |
|:----------------------------|-----------------------------------------|---------------------------------------------------------------------------|
| `prefix`/cec/device/`laddr`/power/set | `on` / `standby`              | Turn on/standby device with with logical address `laddr` (0-14).  |
| `prefix`/cec/device/`laddr`/active/set | `yes` / `no`                 | Turn on/standby device with with logical address `laddr` (0-14).  |
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

## Lirc

You need a `lircrc` config file. This can be generated from the `lircd.conf` of your lirc daemon using the script `create_lircrc.py`.
Simply call this script with the `lircd.conf` path as first argument.
It will print the lircrc contents to stdout and can be easily written to a file:
```
$ ./create_lircrc.py /etc/lirc/lircd.conf > lircrc
```

If you write your own lircrc file, notice that the `config` parameter for each configuration is what is given to the bridge.
It is assumed that it is in the format `<remote>,<key>`.
If only one value is given, the remote is expected to be omitted.

The lircrc format (that would be generated by the `create_lircrc.py` script) should look like:
```
begin
  remote = <remote-name>
  button = <key-name>
  prog = cec-ir-mqtt
  config = <remote-name>,<key-name>
end
```

To only get the key (without the remote name in the MQTT topic) use the format without the remote in the `config`:
```
begin
  remote = <remote-name>
  button = <key-name>
  prog = cec-ir-mqtt
  config = <key-name>
end
```

# Interesting links
* https://github.com/nvella/mqtt-cec
* http://www.cec-o-matic.com/
* http://wiki.kwikwai.com/index.php?title=The_HDMI-CEC_bus
* https://www.hdmi.org/docs/Hdmi13aSpecs
* https://github.com/Pulse-Eight/libcec/blob/master/include/cec.h
* https://github.com/Pulse-Eight/libcec/blob/master/src/pyCecClient/pyCecClient.py