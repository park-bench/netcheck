#!/usr/bin/env python2

# Copyright 2017 Joel Allen Luellwitz and Andrew Klapp
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

__author__ = 'Joel Luellwitz and Andrew Klapp'
__version__ = '0.8'

import confighelper
import logging
import networkmetamanager
import netcheck

config_helper = confighelper.ConfigHelper()
config_helper.configure_logger('/dev/stdout', 'trace')

network = 'Wired connection 1'
config = {}
config['nmcli_timeout'] = 600
config['dig_timeout'] = 10

config['nameservers'] = ['8.8.8.8', '1.2.3.4', '8.8.4.4']
config['dns_queries'] = ['facebook.com', 'google.com', 'twitter.com']

m = networkmetamanager.NetworkMetaManager(config)

# print('NMM.connect returns %s.' % m.connect(network))
print('NMM.is_connected returns %s.' % m.is_connected(network))
print('IP address: %s' % m.get_interface_ip(network))
print('Gateway address: %s' % m.get_gateway_ip(network))

logger = logging.getLogger()
n = netcheck.NetCheck(config)

nameserver = '8.8.8.8'
query = 'facebook.com'

print(n._dns_query(network, nameserver, query))
#print(n._DNS_query(network, '8.8.8.255', query))

# TODO: Test further for negatives.
print('DNS works for %s: %s.' % (network, n._dns_works(network)))

# print('NMM.disconnect returns %s.' % m.disconnect(network))
