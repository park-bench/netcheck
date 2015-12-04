import datetime
import dns.resolver
import networkmetamanager
import random
import subprocess
import time
import timber

# NetCheck monitors the wired network connection. If it is down, it attempts
#   to connect to a prioritized list of wireless networks.  If nothing works, it
#   will cycle through both the wired and wireless networks until one is available.
class NetCheck:

    def __init__(self, config):

        self.config = config
        self.backup_network_check_time = datetime.date.today()

        # Get logger
        self.logger = timber.get_instance()

        # Instantiate NetworkManagerManager
        self.network_meta = networkmetamanager.NetworkMetaManager(self.config['nmcli_timeout'])

        # Initialize wifi network list by putting them into our list of dicts.
        self.wifi_networks = []
        for network_name in self.config['wifi_network_names']:
            self.wifi_networks.append({'name': network_name, 'attempted': False})

        self.connected_wifi_index = None

    # Attempts a DNS query for query_name on 'nameserver' via 'network'.
    #   Returns True if successful, None otherwise.
    def _DNS_query(self, network, nameserver, query_name):
        # TODO: dig timeout seems to be ignored?  Investigate this further.

        gateway_ip = self.network_meta.get_gateway_ip(network)
        interface_ip = self.network_meta.get_interface_ip(network)
        self.logger.trace('Querying %s for %s on network %s.' % (nameserver, query_name, network))
        success = False
        # Add a route for this query, otherwise it will not use the specified network.
        route_command = ['ip', 'route', 'replace', '%s/32' % nameserver, 'via', gateway_ip]
        if(self.network_meta._subprocess_call(route_command)):
            self.logger.debug('Route added.')
            dig_command_list = ['dig', '@%s' % nameserver, '-b', interface_ip, query_name, \
                    '+time=%d' % self.config['dig_timeout']]
            if(self.network_meta._subprocess_call(dig_command_list)):
                self.logger.debug('DNS query successful.')
                success = True
            else:
                self.logger.debug('DNS query failed.')
 
        else:
            self.logger.warn('Failed to set route for DNS lookup.')
 
        # Try to remove the route whether it failed or not
        if(self.network_meta._subprocess_call(['ip', 'route', 'del', nameserver])):
            self.logger.debug('Removed route.')
        else:
            # TODO: Find a better way to deal with DNS over a specific interface than using route
            # TODO: This is not a problem if removing the route failed because 
            #   it isn't there in the first place, which is usually why it fails.
            #   It is a problem if somehow the old route is still there.  Figure
            #   out how to recover from that gracefully.
            self.logger.error('Removing route failed.')
        return success

    # TODO: Document
    def _DNS_works(self, network):
        # Pick two exclusive-random choices from the nameserver and query list
        #   and call _DNS_query with them.
        nameservers = random.sample(self.config['nameservers'], 2)
        query_names = random.sample(self.config['dns_queries'], 2)

        dns_works = False
        
        self.logger.info('Trying DNS on %s.' % network)
        self.logger.debug('First DNS query on %s.' % network)
        if(self._DNS_query(network, nameservers[0], query_names[0])):
            dns_works = True
        else:
            self.logger.debug('Second DNS query on %s.' % network)
            if(self._DNS_query(network, nameservers[1], query_names[1])):
                dns_works = True
            else:
                self.logger.warn('Two failed DNS queries on %s, assume it is down.' % network)

        return dns_works

    def _connect_and_check_DNS(self, network):
        pass

    # TODO: Document
    def _try_wifi_networks(self, index):
        # TODO: Test this more thoroughly.
        success = False
        network_name = self.wifi_networks[index]['name']
        try:
            # TODO: We actually aren't using attempted anywhere.
            self.wifi_networks[index]['attempted'] = True
            if (index <= self.connected_wifi_index):
                # No sense in going down to a lower priority network without
                #   checking the current one's availability.
                if (self.network_meta.is_connected(network_name)):
                    if (self._DNS_works(network_name)):
                        self.logger.info('Network %s still has DNS.' % network_name)
                        success = True
                    else:
                        self.logger.info('Network %s no longer has DNS.' % network_name)
                        self.connected_wifi_index = None
                        self._try_wifi_networks(index + 1)

            else:
                # check index
                # TODO: Combine the connect and DNS query into one method. That way if it fails,
                #   you just try the next network. (Talk to me before implementing this.)
                if (self.network_meta.connect(network_name)):
                    # try DNS
                    self.logger.info('%s connected.' % network_name)
                    if(self._DNS_works(network_name)):
                        self.logger.info('%s has working DNS.' % network_name)
                        self.connected_wifi_index = index
                        success = True
                    else:
                        self.logger.warn('%s does not have working DNS.' % network_name)
                        self._try_wifi_networks(index + 1)
                else:
                    self.logger.warn('Could not connect to %s.' % network_name)
                    self._try_wifi_networks(index + 1)

        # TODO: Typically relying on exceptions for legitmate program flow is frowned upon.
        except IndexError:
            # Out of bounds means that we're out of networks.
            # Clear attempted list
            self.logger.warn('Reached end of wifi network list.')
            for network in self.wifi_networks:
                network['attempted'] = False
            success = False

        return success

    # TODO: Document
    def check_loop(self):
        # Check wired network and call _try_wifi_networks if it's down
        self.logger.info('Check loop starting.')
        # TODO: Check a specific wifi network on a random range of 27 days.
        # TODO: Recalculate that interval every time the network is checked.

        if(datetime.date.today() >= self.backup_network_check_time):
            if(self.network_meta.connect(self.config['backup_network_name'])):
                if(self._DNS_works(self.config['backup_network_name'])):
                    # TODO: Download a small file here?
                    self.logger.info('Backup network still active.')
                else:
                    self.logger.warn('Backup network does not have DNS.')
            else:
                self.logger.warn('Cannot connect to backup network.')

            self.backup_network_check_time = datetime.date.today() + \
                datetime.timedelta(days=random.randrange(self.config['backup_network_max_usage_delay']))
            self.logger.info('Checking again in %s.' % self.backup_network_check_time)
        else:
            self.logger.debug('Skipping backup network check.')

        while True:
            # TODO: Add a try about here to make this loop fault tolerant.

            if(self.network_meta.is_connected(self.config['wired_network_name'])):
                self.logger.info('Wired network connected.')
                if(self._DNS_works(self.config['wired_network_name'])):
                    self.logger.info('Wired network has DNS. Sleeping')
                    # TODO: Consider putting the sleep at the bottom of the loop instead of 
                    #   everywhere. This seems error prone.
                    time.sleep(random.randrange(self.config['sleep_range']))
                elif(self._try_wifi_networks(0)):
                    self.logger.info('Wifi network working, sleeping.')
                    time.sleep(random.randrange(self.config['sleep_range']))
                else:
                    self.logger.warn('Wifi and wired networks are down.  Sleeping.')
                    time.sleep(random.randrange(self.config['sleep_range']))
                    

            elif(self.network_meta.connect(self.config['wired_network_name'])):
                self.logger.info('Wired network connected.')

            elif(self.connected_wifi_index):
                if(self._DNS_works(self.wifi_networks[self.connected_wifi_index]['name'])):
                    self.logger.warn('Wired network down, but current wifi network is up. Sleeping.')
                    time.sleep(random.randrange(self.config['sleep_range']))
                else:
                    self.logger.info('Current wifi network is down.')
                    self.connected_wifi_index = None
            else:
                self.logger.info('Wired network is down, trying wifi networks.')
                # TODO: Ideally this should be only called once in this method. I should
                #   take a stab a rewriting this method.
                self._try_wifi_networks(0)
                time.sleep(random.randrange(self.config['sleep_range']))
            
