import dns.resolver
import networkmetamanager
import random
import subprocess
import time
import timber

class NetCheck:
    def __init__(self, config):
        self.config = config
        # TODO: Add sleep interval range config option, set it manually for now
        self.sleep_time = random.randrange(150)

        # Get logger
        self.logger = timber.get_instance()

        # Instantiate NetworkManagerManager
        self.network_meta = networkmetamanager.NetworkMetaManager(self.config['nmcli_timeout'], self.config['dig_timeout'])

        # Convenient /dev/null access

    def _DNS_query(self, network, nameserver, query):
        # TODO: dig timeout seems to be ignored?
        # Attempts a DNS query for query on nameserver via network
        # Returns True if successful, None otherwise

        gateway_ip = self.network_meta.get_gateway_ip(network)
        interface_ip = self.network_meta.get_interface_ip(network)
        self.logger.trace('Querying %s for %s on network %s.' % (nameserver, query, network))
        success = None
        # Add a route for this query, otherwise it will not use the specified network
        route_command_list = ['ip', 'route', 'replace', '%s/32' % nameserver, 'via', gateway_ip]
        if(self.network_meta._subprocess_call(route_command_list)):
            # TODO: Figure out why you added this
            self.logger.debug('Route added.')
            time.sleep(1)
            dig_command_list = ['dig', '@%s' % nameserver, '-b', interface_ip, query, '+time=%d' % self.config['dig_timeout']]
            if(self.network_meta._subprocess_call(dig_command_list)):
                self.logger.debug('DNS query successful.')
                success = True
            else:
                self.logger.debug('DNS query failed.')
            
        else:
            self.logger.warn('Failed to set route for DNS lookup.')
        # Try to remove the route whether it failed or not
        
        self.network_meta._subprocess_call(['ip', 'route', 'del', nameserver])
        self.logger.debug('Removed route.')
        return success


    def _DNS_works(self, network):
        # Pick two exclusive-random choices from the nameserver and query list
        # and call _DNS_query with them
        nameservers = random.sample(self.config['nameservers'], 2)
        queries = random.sample(self.config['dns_queries'], 2)

        dns_works = None

        self.logger.debug('First DNS query on %s.' % network)
        if(self._DNS_query(network, nameservers[0], queries[0])):
            dns_works = True
        else:
            self.logger.debug('Second DNS query on %s.' % network)
            if(self._DNS_query(network, nameservers[1], queries[1])):
                dns_works = True

        return dns_works

    def _try_wifi_networks(self):
        # See pseudo file
        pass

    def check_loop(self):
        # Check wired network and call _try_wifi_networks
        pass
