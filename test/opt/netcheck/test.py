#!/usr/bin/env python2
import networkmetamanager
import netcheck
import timber

network = 'SPACE'
m = networkmetamanager.NetworkMetaManager(600, 10)

# print('NMM.connect returns %s.' % m.connect(network))
print('NMM.is_connected returns %s.' % m.is_connected(network))
print('IP address: %s' % m.get_interface_ip(network))
print('Gateway address: %s' % m.get_gateway_ip(network))

config = {}
config['nmcli_timeout'] = 600
config['dig_timeout'] = 10

config['nameservers'] = ['8.8.8.8', '1.2.3.4', '8.8.4.4']
config['dns_queries'] = ['facebook.com', 'google.com', 'twitter.com']

logger = timber.get_instance_with_filename('test.log', 'trace')
n = netcheck.NetCheck(config)

nameserver = '8.8.8.8'
query = 'facebook.com'

print(n._DNS_query(network, nameserver, query))
#print(n._DNS_query(network, '8.8.8.255', query))

# TODO: Test further for negatives.
print('DNS works for %s: %s.' % (network, n._DNS_works(network)))

# print('NMM.disconnect returns %s.' % m.disconnect(network))
