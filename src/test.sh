#!/bin/bash
echo stopping cec-mqtt-bridge service
sudo systemctl stop cec-mqtt-bridge
./run.py -v -f config.ini |& tee -a $(date +"%Y_%m_%d_%I_%M_%p").log
echo starting cec-mqtt-bridge service
sudo systemctl start cec-mqtt-bridge
