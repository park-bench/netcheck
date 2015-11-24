import dns.resolver
import networkmetamanager
import random
import subprocess
import time
import timber

class checker:
    def __init__(self, config):
        self.config = config
        # TODO: Add sleep interval range config option, set it manually for now
        self.sleep_time = random.randrange(150)

        # Get logger
        self.logger = timber.get_instance()

        # Instantiate NetworkManagerManager
        self.network_meta = networkmetamanager.NetworkMetaManager(self.config['nmcli_timeout'], self.config['dig_timeout'])

    def _DNS_query(self, network, nameserver, query):
        # Attempts a DNS query for query on nameserver via network
        # Returns True if successful, None otherwise

        gateway_ip = self.network_meta.get_gateway_ip(network)
        interface_ip = self.network_meta.get_interface_ip(network)
        sucess = None
        if(subprocess.check_output(['ip', 'route', 'replace', '%s/32' % nameserver, 'via', gateway_ip != ''):
            pass
        else:
            pass

    def _DNS_works(self, network):
        # Pick two exclusive-random choices from the nameserver and query list
        # and call _DNS_query with them
        pass

    def _try_wifi_networks(self):
        # See design file
        pass

    def check_loop(self):
        # Check wired network and call _try_wifi_networks
        pass
