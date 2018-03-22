#!/usr/bin/env python2

import logging
import NetworkManager
import networkmanagerhelper

### This is not an automated test script. This is an ugly dumping ground for bits of code I
#   have used to test the networkmanagerhelper module.
WIRED_TEST_NETWORK_NAME = 'ethernet-ens8'
MISSING_TEST_NETWORK_NAME = 'please-dont-have-a-network-with-this-name'

config = {}

config['wired_interface_name'] = 'ens3'
config['wireless_interface_name'] = 'ens8'
config['network_activation_timeout'] = 15

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

nmh = networkmanagerhelper.NetworkManagerHelper(config)

nmh.activate_network(WIRED_TEST_NETWORK_NAME)
device = nmh._get_device_for_connection(nmh.network_id_table[WIRED_TEST_NETWORK_NAME])
#print(device.GetAppliedConnection(0))

print(nmh.network_is_ready(WIRED_TEST_NETWORK_NAME))
print(nmh.get_network_ip(WIRED_TEST_NETWORK_NAME))
#print(NetworkManager.NetworkManager.ActiveConnections)