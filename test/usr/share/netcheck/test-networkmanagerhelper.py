#!/usr/bin/env python2

# Copyright 2015-2018 Joel Allen Luellwitz and Andrew Klapp
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# This is not an automated test script. This is an ugly dumping ground for bits of code I
#   have used to test the networkmanagerhelper module.

import logging
import NetworkManager
import networkmanagerhelper

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
