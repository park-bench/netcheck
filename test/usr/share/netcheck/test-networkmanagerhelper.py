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

"""This is not an automated test script. This is an ugly dumping ground for bits of code I
have used to test the networkmanagerhelper module.
"""

__author__ = 'Joel Luellwitz and Andrew Klapp'
__version__ = '0.8'

import logging
import networkmanagerhelper

WIRED_TEST_CONNECTION_NAME = 'ens3'
MISSING_TEST_CONNECTION_NAME = 'please-dont-have-a-connection-with-this-name'

config = {}

config['wired_interface_name'] = 'ens3'
config['wireless_interface_name'] = 'ens3'
config['connection_activation_timeout'] = 15

config['wired_connection_id'] = WIRED_TEST_CONNECTION_NAME
config['wireless_connection_ids'] = []

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

nmh = networkmanagerhelper.NetworkManagerHelper(config)

nmh.activate_connection(WIRED_TEST_CONNECTION_NAME)
print(nmh.get_connection_ip(WIRED_TEST_CONNECTION_NAME))
print(nmh.connection_is_activated(WIRED_TEST_CONNECTION_NAME))

#device = nmh._get_device_for_connection(
#    nmh.connection_id_to_connection_dict[WIRED_TEST_CONNECTION_NAME])
#print(device.GetAppliedConnection(0))
