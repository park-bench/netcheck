#!/usr/bin/env python2

# Copyright 2017-2019 Joel Allen Luellwitz and Emily Frost
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

__author__ = 'Joel Luellwitz and Emily Frost'
__version__ = '0.8'

import datetime
import logging
import confighelper
import netcheck
import networkmanagerhelper

config_helper = confighelper.ConfigHelper()
config_helper.configure_logger('/dev/stdout', 'trace')

network = 'Wired connection 1'
config = {}
config['connection_ids'] = ['Wired connection 1']
config['connection_activation_timeout'] = 15
config['dns_timeout'] = 10
config['available_connections_check_time'] = 5
config['required_usage_connection_ids'] = []
config['periodic_status_delay'] = 900

config['nameservers'] = ['8.8.8.8', '1.2.3.4', '8.8.4.4']
config['dns_queries'] = ['facebook.com', 'google.com', 'twitter.com']

m = networkmanagerhelper.NetworkManagerHelper(config)

# print('NMM.activate_connection_with_available_device returns %s.' % 
#    m.activate_connection_with_available_device(network))
print('NMM.connection_is_activated returns %s.' % m.connection_is_activated(network))
print('Interface is: %s' % m.get_connection_interface(network))

logger = logging.getLogger()
n = netcheck.NetCheck(config)

time = datetime.datetime.now()
connection_context = {
    id: network,
}
nameserver = '8.8.8.8'
query = 'facebook.com'

print(n._dns_query(time, connection_context, nameserver, query))
#print(n._dns_query(time, connection_context, '8.8.8.255', query))

# TODO: Test further for negatives.
print('DNS works for %s: %s.' % (network, n._dns_works(time, connection_context)))

# print('NMM.deactivate_connection:')
# m.deactivate_connection(network)
