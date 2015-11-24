#!/usr/bin/env python2
import networkmetamanager
import netcheck

network = 'SPACE'

m = networkmetamanager.NetworkMetaManager(600, 20)

print('NMM.connect returns %s.' % m.connect(network))
print('NMM.is_connected returns %s.' % m.is_connected(network))
print('IP address: %s' % m.get_interface_ip(network))
print('Gateway address: %s' % m.get_gateway_ip(network))
print('Has Internet access: %s' % m.has_internet_access(network))
print('NMM.disconnect returns %s.' % m.disconnect(network))
