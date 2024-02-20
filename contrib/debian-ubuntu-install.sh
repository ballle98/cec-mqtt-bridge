#!/bin/sh

PREFIX="/usr/local"

cd ..

python3 -m build
sudo pip install --force-reinstall dist/cec_mqtt_bridge-*.whl

if [ -f /etc/cec-mqtt-bridge.ini ]; then
  echo "/etc/cec-mqtt-bridge.ini exists, did not copy new config, you may need to edit existing!" 
else
  sudo cp config.ini.default /etc/cec-mqtt-bridge.ini
fi

sudo install -m 644 -C debian/cec-mqtt-bridge.service /etc/systemd/system/cec-mqtt-bridge.service

sudo systemctl enable cec-mqtt-bridge
sudo systemctl daemon-reload
sudo systemctl start cec-mqtt-bridge