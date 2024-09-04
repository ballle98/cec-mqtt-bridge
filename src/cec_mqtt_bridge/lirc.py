#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import threading
import time
import lirc

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIGURATION = {
    'enabled': 0,
    'rx_sock_path': None,
    'tx_sock_path': None
}


class Lirc:

    def __init__(self, mqtt_send, config: dict):
        self._config = config
        self._mqtt_send = mqtt_send
        self.stop_event = threading.Event()
        self.conn = None

        LOGGER.info("Initialising IR...")
        try:
            self.lirc_thread = threading.Thread(target=self.ir_listen_thread)
            self.lirc_thread.setDaemon(True)
            self.lirc_thread.start()
        except Exception as e:
            LOGGER.error("Could not initialise IR:", str(e))
            exit(1)

    def ir_listen_thread(self):
        LOGGER.info("Running IR listen thread %s rx_sock_path %s", threading.current_thread().name, self._config['rx_sock_path'])
        self.conn = lirc.RawConnection()
        while not self.stop_event.is_set():
            try:
                ir_rx_line = self.conn.readline(timeout=0.2)
                LOGGER.debug("ir_rx_line %s", ir_rx_line)
                (scan, repeat, key, remote) = ir_rx_line.split()
                LOGGER.debug("scan %s repeat %s key %s remote %s", scan, repeat, key, remote)
                if int (repeat) == 0:
                    self._mqtt_send('ir/' + remote + '/rx', key)
            except lirc.TimeoutException:
                pass

        LOGGER.info("Stopping IR listen thread %s", threading.current_thread().name)
        self.conn.close()

    def ir_send(self, remote, key):
        LOGGER.debug("ir_send(%s,%s) to tx_sock_path %s", remote, key, self._config['tx_sock_path'])
        cmd_conn = lirc.CommandConnection(self._config['tx_sock_path'])
        reply = lirc.SendCommand(cmd_conn, remote, [key]).run()
        LOGGER.debug("success = %s", str(reply.success))
        for line in reply.data:
            LOGGER.debug("%s", line)
        cmd_conn.close()
