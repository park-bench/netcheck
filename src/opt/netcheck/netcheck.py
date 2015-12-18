import datetime
import dns.resolver
import networkmetamanager
import random
import subprocess
import time
import timber
import traceback

# NetCheck monitors the wired network connection. If it is down, it attempts
#   to connect to a prioritized list of wireless networks.  If nothing works, it
#   will cycle through both the wired and wireless networks until one is available.
# TODO: Test this more thoroughly.
class NetCheck:

    def __init__(self, config):

        self.config = config

        # Get logger
        self.logger = timber.get_instance()

        # Instantiate NetworkMetaManager
        self.network_meta = networkmetamanager.NetworkMetaManager(self.config['nmcli_timeout'])

        self.backup_network_check_time = datetime.date.today()
        self.connected_wifi_index = None

        wifi_connection_successful = self._try_wifi_networks(0)

        if (wifi_connection_successful):
            self.logger.info('Connected to wifi network %s during initialization.' % \
                    self.config['wifi_network_names'][self.connected_wifi_index])
        else:
            self.logger.warn('All wifi networks failed to connect during initialization.')

        self.logger.info('NetCheck initialized.')

    # Attempts a DNS query for query_name on 'nameserver' via 'network'.
    #   Returns True if successful, None otherwise.
    def _DNS_query(self, network, nameserver, query_name):

        gateway_ip = self.network_meta.get_gateway_ip(network)
        interface_ip = self.network_meta.get_interface_ip(network)
        self.logger.trace('_DNS_query: Querying %s for %s on network %s.' % (nameserver, query_name, network))
        success = False
        # Add a route for this query, otherwise it will not use the specified network.
        route_command = ['ip', 'route', 'replace', '%s/32' % nameserver, 'via', gateway_ip]
        if (self.network_meta._subprocess_call(route_command)):
            self.logger.debug('_DNS_query: Route added.')
            dig_command_list = ['dig', '@%s' % nameserver, '-b', interface_ip, query_name, \
                    '+time=%d' % self.config['dig_timeout'], '+tries=1']
            if(self.network_meta._subprocess_call(dig_command_list)):
                self.logger.debug('_DNS_query: DNS query successful.')
                success = True
            else:
                self.logger.debug('_DNS_query: DNS query failed.')
 
        else:
            self.logger.warn('Failed to set route for DNS lookup.')
 
        # Try to remove the route whether it failed or not
        if (self.network_meta._subprocess_call(['ip', 'route', 'del', nameserver])):
            self.logger.debug('_DNS_query: Removed route.')
        else:
            # TODO: Find a better way to deal with DNS over a specific interface than using route
            # TODO: This is not a problem if removing the route failed because 
            #   it isn't there in the first place, which is usually why it fails.
            #   It is a problem if somehow the old route is still there.  Figure
            #   out how to recover from that gracefully.
            self.logger.error('Removing route failed.')
        return success

    # Runs up to two DNS queries using the config file's list of DNS servers
    #   and domains to query over the given network and returns True if either
    #   one of them succeeds.
    def _DNS_works(self, network):
        # Pick two exclusive-random choices from the nameserver and query list
        #   and call _DNS_query with them.
        nameservers = random.sample(self.config['nameservers'], 2)
        query_names = random.sample(self.config['dns_queries'], 2)

        dns_works = False
        
        self.logger.info('Trying DNS on %s.' % network)
        self.logger.trace('_DNS_works: First DNS query on %s.' % network)
        if (self._DNS_query(network, nameservers[0], query_names[0])):
            dns_works = True
            self.logger.trace('_DNS_works: First DNS query on %s successful.' % network)
        else:
            self.logger.warn('First DNS query failed %s.' % network)
            self.logger.trace('_DNS_works: Second DNS query on %s.' % network)
            if (self._DNS_query(network, nameservers[1], query_names[1])):
                dns_works = True
                self.logger.trace('_DNS_works: Second DNS query on %s successful.' % network)
            else:
                self.logger.warn('Two failed DNS queries on %s, assume it is down.' % network)

        return dns_works

    # Connects to a network and checks DNS availability if connection was successful.
    #   Returns true on success, false on failure.
    def _connect_and_check_DNS(self, network_name):
        
        overall_success = False
        connection_successful = self.network_meta.connect(network_name)
        if (not(connection_successful)):
            self.logger.warn('Could not connect to network %s' % network_name)
        else:
            self.logger.trace('_connect_and_check_DNS: Connected to network %s' % network_name)
            dns_successful = self._DNS_works(network_name)
            if (not(dns_successful)):
                self.logger.debug('_connect_and_check_DNS: DNS on network %s failed.' % network_name)
            else:
                self.logger.trace('_connect_and_check_DNS: DNS on network %s successful.' % network_name)
                overall_success = True

        return overall_success



    # Checks the connection to a network and checks DNS availability if connection was successful.
    #   Returns true on success, false on failure.
    def _check_connection_and_check_DNS(self, network_name):
        
        overall_success = False
        connection_active = self.network_meta.is_connected(network_name)
        if (not(connection_active)):
            self.logger.warn('Not connected to network %s' % network_name)
        else:
            self.logger.trace('_check_connection_and_check_DNS: Connected to network  %s.' % network_name)
            dns_successful = self._DNS_works(network_name)
            if (not(dns_successful)):
                self.logger.debug('_check_connection_and_check_DNS: DNS on network %s failed.' % network_name)
            else:
                self.logger.trace('_check_connection_and_check_DNS: DNS on network %s successful.' % network_name)
                overall_success = True

        return overall_success


    # Tries to connect to the wifi network at a specific index of the config
    #   file's list of networks.  If it fails, it calls itself on the next
    #   network in the list.
    def _try_wifi_networks(self, index):
        success = None

        if (index >= len(self.config['wifi_network_names'])):
            # Out of bounds means that we're out of networks.
            self.logger.warn('Reached end of wifi network list. ' + \
                    'Setting first network as the currently connected wifi network.')
            self.connected_wifi_index = 0
            success = False

        else:
            network_name = self.config['wifi_network_names'][index]

            wifi_connection_successful = self._connect_and_check_DNS(network_name)

            if (wifi_connection_successful):
                self.logger.info('Wifi network %s connected with successful DNS check.' % network_name)
                self.connected_wifi_index = index
                success = True

            else:
                self.logger.warn('Wifi network %s failed to connect or failed DNS check.' % network_name)
                success = self._try_wifi_networks(index + 1)

        return success


    # Check the highest-priority network randomly between zero and a user-specified number of days.
    #   Recalculate that interval every time the network is checked and then call _try_wifi_networks.
    #   FreedomPop requires monthly usage and is assumed to be the highest-priority network.
    # TODO: Download a small file upon successful connection so we are sure FreedomPop considers
    #   this network used.
    def _check_backup_network(self):
        if (datetime.date.today() >= self.backup_network_check_time):

            self.logger.info('Trying to use backup wifi network.')

            overall_success = False

            backup_network_is_connected = self._check_connection_and_check_DNS( \
                    self.config['wifi_network_names'][0])

            if (backup_network_is_connected):
                self.logger.info('Successfully used existing backup wifi connection.')
                overall_success = True

            else:
                self.logger.info('Trying to connect and use backup wifi network.')
                #wifi_connection_successful = self._try_wifi_networks(0)
                wifi_connection_successful = self._connect_and_check_DNS(\
                    self.config['wifi_network_names'][0])

                if (not(wifi_connection_successful) or (self.connected_wifi_index != 0)):
                    self.backup_network_check_time = datetime.date.today() + \
                            datetime.timedelta(seconds=random.randrange( \
                            self.config['backup_network_failed_max_usage_delay']))
                    self.logger.warn('Failed to use backup network. Will try again on %s.' % \
                            self.backup_network_check_time)
                
                else:
                    self.backup_network_check_time = datetime.date.today() + \
                        datetime.timedelta(days=random.randrange(self.config['backup_network_max_usage_delay']))
                    self.logger.info('Successfully connected to backup network. Will try again on %s.' % \
                        self.backup_network_check_time)

        else:
            self.logger.trace('Skipping backup network check because it is not time yet.')


    # TODO: Document
    def check_loop(self):
        # Check wired network and call _try_wifi_networks if it's down
        self.logger.info('Check loop starting.')

        while True:
            # TODO: Lower log levels should be used higher on the stack.

            self.logger.debug('Check loop iteration starting.')

            try:
                self._check_backup_network()
                
                wired_is_connected = self._check_connection_and_check_DNS(self.config['wired_network_name'])

                if (not(wired_is_connected)):
                    self.logger.warn('Wired network is not connected.')

                    wired_connection_success = self._connect_and_check_DNS(self.config['wired_network_name'])

                    if (not(wired_connection_success)):
                        self.logger.warn('Wired network failed to connect.')
                    
                        current_wifi_network_name = self.config['wifi_network_names'][self.connected_wifi_index]
                        wifi_is_connected = self._check_connection_and_check_DNS(current_wifi_network_name)

                        if (not(wifi_is_connected)):
                            self.warn('Current wifi network %s is no longer connected.' % \
                                    current_wifi_network_name)

                            wifi_connection_successful = self._try_wifi_networks(0)

                            if (not(wifi_connection_successful)):
                                self.logger.warn('All wireless networks failed to connect.')
                            else:
                                self.logger.info('Connected to wireless network %s.' % \
                                        self.config['wifi_network_names'][self.connected_wifi_index])
                        else:
                            self.logger.debug('Current wifi network %s still active.' % \
                                    current_wifi_network_name)
                    else:
                        self.logger.trace('Wired network connected with successful DNS check.')
                else:
                    self.logger.trace('Wired network still connected with successful DNS check.')

                self.logger.debug('Sleeping!')
                time.sleep(random.randrange(self.config['sleep_range']))

            except Exception as e:
                self.logger.error('Unexpected error %s: %s\n' % (type(e).__name__, e.message))
                self.logger.error(traceback.format_exc())

