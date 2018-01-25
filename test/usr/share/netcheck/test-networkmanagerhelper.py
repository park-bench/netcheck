#!/usr/bin/env python2

import logging
import networkmanagerhelper

config = {}

config['wired_interface_name'] = 'ens3'
config['wireless_interface_name'] = 'ens8'
config['network_activation_timeout'] = 15

logging.basicConfig()
logger = logging.getLogger()

nmh = networkmanagerhelper.NetworkManagerHelper(config)

print(nmh.network_id_table['ethernet-ens3'].GetSettings()['connection']['type'])

nmh.activate_network('ethernet-ens3')
