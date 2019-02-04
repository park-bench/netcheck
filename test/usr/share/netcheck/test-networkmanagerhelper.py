#!/usr/bin/env python2

# Copyright 2015-2019 Joel Allen Luellwitz and Andrew Klapp
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
import confighelper
import networkmanagerhelper

TEST_CONNECTION_NAME = 'ens3'
MISSING_TEST_CONNECTION_NAME = 'please-dont-have-a-connection-with-this-name'

config = {}
config['connection_ids'] = TEST_CONNECTION_NAME
config['connection_activation_timeout'] = 15

config_helper = confighelper.ConfigHelper()
config_helper.configure_logger('/dev/stdout', 'DEBUG')
logger = logging.getLogger()

nmh = networkmanagerhelper.NetworkManagerHelper(config)

nmh.activate_connection_with_available_device(TEST_CONNECTION_NAME)
print(nmh.get_connection_ip(TEST_CONNECTION_NAME))
print(nmh.connection_is_activated(TEST_CONNECTION_NAME))
