#!/usr/bin/env python2

import networkmanagerhelper

config = {}

config['wired_interface_name'] = 'ens3'
config['wireless_interface_name'] = 'ens8'
config['network_activation_timeout'] = 15

nmh = networkmanagerhelper.NetworkManagerHelper(config)
