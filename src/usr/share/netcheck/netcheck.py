# Copyright 2015-2016 Joel Allen Luellwitz and Andrew Klapp
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

import datetime
import dns.resolver
import logging
import networkmetamanager
import os
import random
import subprocess
import time
import traceback

# NetCheck monitors the wired network connection. If it is down, it attempts
#   to connect to a prioritized list of wireless networks.  If nothing works, it
#   will cycle through both the wired and wireless networks until one is available.
# TODO: Make multithreaded.
# TODO: Consider checking if gpgmailer authenticated with the mail server and is
#   sending mail.
class NetCheck:


    def __init__(self, config):

        self.config = config

        # Get logger
        self.logger = logging.getLogger()

        # Easy and efficient /dev/null access
        self.devnull = open(os.devnull, 'w')

        # Instantiate NetworkMetaManager
        self.network_meta = networkmetamanager.NetworkMetaManager(self.config['nmcli_timeout'])

        self.backup_network_check_time = datetime.datetime.now()
        self.connected_wifi_index = 0

        # This section is commented out because we connect to the backup network
        #   as soon as the program starts anyway. If FreedomPop's monthly usage requirement
        #   goes away, we should revert back to using this.
        #wifi_connection_successful = self._try_wifi_networks(0)
        #
        #if wifi_connection_successful:
        #    self.logger.info('Connected to wifi network %s during initialization.' % \
        #            self.config['wifi_network_names'][self.connected_wifi_index])
        #else:
        #    self.logger.warn('All wifi networks failed to connect during initialization.')

        self.logger.info('NetCheck initialized.')


    # Attempts a DNS query for query_name on 'nameserver' via 'network'.
    #   Returns True if successful, False otherwise.
    def _dns_query(self, network, nameserver, query_name):
        # TODO: Switch this to use dnspython's resolver module instead of route.

        self.logger.trace('_dns_query: Querying %s for %s on network %s.' % (nameserver, query_name, network))

        # TODO: Add support for when these are not able to obtain the IP.
        gateway_ip = self.network_meta.get_gateway_ip(network)
        interface_ip = self.network_meta.get_interface_ip(network)

        success = False

        # Add a route for this query, otherwise it might not use the specified network.
        route_command = ['ip', 'route', 'replace', '%s/32' % nameserver, 'via', gateway_ip]
        if not(self._subprocess_call(route_command)):
            self.logger.error('Failed to set route for %s nameserver over gateway %s.' % \
                    (nameserver, gateway_ip))
 
        else:
            self.logger.trace('_dns_query: Route added.')
            dig_command = ['dig', '@%s' % nameserver, '-b', interface_ip, query_name, \
                    '+time=%d' % self.config['dig_timeout'], '+tries=1']

            if not(self._subprocess_call(dig_command)):
                self.logger.debug('_dns_query: DNS query failed.')
            else:
                self.logger.trace('_dns_query: DNS query successful.')
                success = True
 
        # Try to remove the route whether it failed or not.
        if self._subprocess_call(['ip', 'route', 'del', nameserver]):
            self.logger.trace('_dns_query: Removed route.')
        else:
            # TODO: Find a better way to deal with DNS over a specific interface than using 'route'.
            # TODO: This is not a problem if removing the route failed because 
            #   it isn't there in the first place, which is usually why it fails.
            #   It is a problem if somehow the old route is still there. Figure
            #   out how to recover from that gracefully.
            self.logger.error('Removing route for %s failed.' % nameserver)

        return success


    # Runs up to two DNS queries over the given network using two random nameservers for two 
    #   random domains from the config file's list of DNS servers and domains. Returns 
    #   True if either DNS query succeeds. False otherwise.
    def _dns_works(self, network):

        # Picks two exclusive-random choices from the nameserver and domain name lists.
        nameservers = random.sample(self.config['nameservers'], 2)
        query_names = random.sample(self.config['dns_queries'], 2)

        dns_works = False
        
        self.logger.trace('_dns_works: Attempting first DNS query for %s on interface %s using name server %s.' % \
                (query_names[0], network, nameservers[0]))
        if self._dns_query(network, nameservers[0], query_names[0]):
            dns_works = True
            self.logger.trace('_dns_works: First DNS query on %s successful.' % network)
        else:
            self.logger.debug('_dns_works: First DNS query for %s failed on interface %s using name server %s. ' % \
                    (query_names[0], network, nameservers[0]) + 'Attempting second query.')
            self.logger.trace('_dns_works: Attempting second DNS query for %s on interface %s using name server %s.' % \
                    (query_names[1], network, nameservers[1]))
            if (self._dns_query(network, nameservers[1], query_names[1])):
                dns_works = True
                self.logger.trace('_dns_works: Second DNS query on %s successful.' % network)
            else:
                self.logger.debug('_dns_works: Second DNS query for %s failed on interface %s using name server %s. ' % \
                         (query_names[1], network, nameservers[1]) + 'Assuming network is down.')

        return dns_works


    # Connects to a network and checks DNS availability if connection was successful.
    #   Returns true on success, false on failure.
    def _connect_and_check_dns(self, network_name):

        self.logger.trace('_connect_and_check_dns: Attempting to connect to and reach the Internet over %s.' % \
                network_name)
        
        overall_success = False
        connection_successful = self.network_meta.connect(network_name)
        if not(connection_successful):
            self.logger.debug('_connect_and_check_dns: Could not connect to network %s.' % network_name)
        else:
            self.logger.trace('_connect_and_check_dns: Connected to network %s.' % network_name)
            dns_successful = self._dns_works(network_name)
            if not(dns_successful):
                self.logger.debug('_connect_and_check_dns: DNS on network %s failed.' % network_name)
            else:
                self.logger.trace('_connect_and_check_dns: DNS on network %s successful.' % network_name)
                overall_success = True

        return overall_success


    # Checks the connection to a network and checks DNS availability if connection exists.
    #   Returns true on success, false on failure.
    def _check_connection_and_check_dns(self, network_name):
        self.logger.trace('_check_connection_and_check_dns: Attempting to reach the ' + \
                'Internet over %s.' % network_name)
        
        overall_success = False
        connection_active = self.network_meta.is_connected(network_name)
        if not(connection_active):
            self.logger.debug('_check_connection_and_check_dns: Not connected to network %s.' % network_name)
        else:
            self.logger.trace('_check_connection_and_check_dns: Connected to network  %s.' % network_name)
            dns_successful = self._dns_works(network_name)
            if not(dns_successful):
                self.logger.debug('_check_connection_and_check_dns: DNS on network %s failed.' % network_name)
            else:
                self.logger.trace('_check_connection_and_check_dns: DNS on network %s successful.' % network_name)
                overall_success = True

        return overall_success


    # Tries to connect to the wifi network at a specific index of the config
    #   file's list of networks.  If it fails, it calls itself on the next
    #   network in the list.
    def _try_wifi_networks(self, index):

        self.logger.trace('_try_wifi_networks: Attempting WiFi network with priority %d.' % index)

        success = None

        if index >= len(self.config['wifi_network_names']):
            # Out of bounds means that we're out of networks.
            self.logger.debug('_try_wifi_networks: Reached end of wifi network list. ' + \
                    'Setting first network as the currently connected wifi network.')
            self.connected_wifi_index = 0
            success = False

        else:
            network_name = self.config['wifi_network_names'][index]

            wifi_connection_successful = self._connect_and_check_dns(network_name)

            if wifi_connection_successful:
                self.logger.debug('_try_wifi_networks: Wifi network %s connected with successful DNS check.' % network_name)
                self.connected_wifi_index = index
                success = True

            else:
                self.logger.debug('_try_wifi_networks: Wifi network %s failed to connect or failed DNS check.' % network_name)
                success = self._try_wifi_networks(index + 1)

        return success


    # Use the highest-priority wireless network randomly between zero and a user-specified number of days.
    #   Recalculate that interval every time the network is checked and then call _try_wifi_networks.
    #   FreedomPop requires monthly usage and is assumed to be the highest-priority network.
    # TODO: Consider downloading a small file upon successful connection so we are sure FreedomPop 
    #   considers this network used.
    # TODO: The random interval should probably be applied after the last DNS check on the backup 
    #   network. (We might have used the backup network since the last check or might even be 
    #   currently connected to it.)
    def _use_backup_network(self):

        self.logger.trace('_use_backup_network: Determining if we should use the main WiFi backup network.')

        if datetime.datetime.now() >= self.backup_network_check_time:

            self.logger.info('Trying to use backup wifi network.')

            backup_network_is_connected = self._check_connection_and_check_dns( \
                    # TODO: Make the backup network actually separate from the list.
                    #   It should use the backup_network_name property from
                    #   from the config file.
                    self.config['wifi_network_names'][0])

            if backup_network_is_connected:
                self._update_successful_backup_check_time()

            else:
                self.logger.info('Trying to connect and use backup wifi network.')
                wifi_connection_successful = self._connect_and_check_dns(\
                    self.config['wifi_network_names'][0])

                if wifi_connection_successful:
                    self._update_successful_backup_check_time()
                else:
                    self.backup_network_check_time = datetime.datetime.now() + \
                            datetime.timedelta(seconds=random.uniform(0,  \
                            self.config['backup_network_failed_max_usage_delay']))
                    self.logger.error('Failed to use backup network. Will try again on %s.' % \
                            self.backup_network_check_time)
        
        else:
            self.logger.trace('Skipping backup network check because it is not time yet.')


    # Determine the next time we will try to connect to the main backup WiFi network after a
    #   successful use.
    def _update_successful_backup_check_time(self):
        self.logger.trace('_update_successful_backup_check_time: Successfully connected to main backup WiFi network.')

        # Convert days to seconds.
        delay_range_in_seconds = self.config['backup_network_max_usage_delay'] * 24 * 60 * 60

        self.backup_network_check_time = datetime.datetime.now() + \
            datetime.timedelta(seconds=random.uniform(0, delay_range_in_seconds))
        self.logger.info('Successfully used to backup network. Will try again on %s.' % \
            self.backup_network_check_time)


    # Attempts to connect to the wired network and falls back to wireless networks in a specified priority order.
    #   Also, connects to the main backup wireless network periodically to comply with carrier requirements.
    def check_loop(self):
        self.logger.info('Check loop starting.')

        current_network_name = None
        # We want this to be different than None so that we record when there is no connection when
        #   the program first starts.
        prior_network_name = -1  

        while True:

            try:
                self.logger.debug('check_loop: Check loop iteration starting.')

                # Periodically connect to the main backup network because the carrier requires this.
                self._use_backup_network()
                
                wired_is_connected = self._check_connection_and_check_dns(self.config['wired_network_name'])

                if (wired_is_connected):
                    self.logger.debug('check_loop: Wired network still connected with successful DNS check.')
                    current_network_name = self.config['wired_network_name']
                else:
                    self.logger.debug('check_loop: Wired network is not connected.')

                    wired_connection_success = self._connect_and_check_dns(self.config['wired_network_name'])

                    if (wired_connection_success):
                        current_network_name = self.config['wired_network_name']
                        self.logger.info('Wired network connected with successful DNS check.')
                    else:
                        self.logger.debug('check_loop: Wired network failed to connect.')
                    
                        current_wifi_network_name = self.config['wifi_network_names'][self.connected_wifi_index]
                        wifi_is_connected = self._check_connection_and_check_dns(current_wifi_network_name)

                        if (wifi_is_connected):
                            # Set current_network_name because network may already be connected during
                            #   initialization.
                            current_network_name = current_wifi_network_name
                            self.logger.debug('check_loop: Current wifi network %s still active.' % \
                                    current_wifi_network_name)
                        else:
                            self.logger.debug('check_loop: Current wifi network %s is no longer connected.' % \
                                    current_wifi_network_name)

                            wifi_connection_successful = self._try_wifi_networks(0)

                            if (wifi_connection_successful):
                                current_network_name = self.config['wifi_network_names'][self.connected_wifi_index]
                                self.logger.info('Connected to wireless network %s.' % current_network_name)
                            else:
                                current_network_name = None
                                self.logger.debug('check_loop: All wireless networks failed to connect.')

                prior_network_name = self._log_connection_change(prior_network_name, current_network_name)

                sleep_time = random.uniform(0, self.config['sleep_range'])
                self.logger.debug('Sleeping for %f seconds!' % sleep_time)
                time.sleep(sleep_time)

            except Exception as e:
                self.logger.error('Unexpected error %s: %s\n' % (type(e).__name__, e.message))
                self.logger.error(traceback.format_exc())


    # Logs changes to the network in use.
    def _log_connection_change(self, prior_network_name, current_network_name):
        if prior_network_name <> current_network_name:
            if current_network_name == None:
                self.logger.error('Connection change: Not connected to any network!')
            elif current_network_name <> self.config['wired_network_name']:
                self.logger.warn('Connection change: Connected to wireless network %s.' % \
                        current_network_name)
            else:
                self.logger.info('Connection change: Connected to the wired network.')

        return current_network_name


    # Invokes a program on the system.
    #   Param command_list is a command split into a list, not a list of separate commands.
    #   Returns True upon success, False otherwise.
    def _subprocess_call(self, command_list):

        exit_code = None

        self.logger.trace('_subprocess_call: Calling "%s".' % ' '.join(command_list))
        try:
            # Run command with subprocess.call, redirecting output to /dev/null.
            exit_code = subprocess.call(command_list, stdin=self.devnull, stdout=self.devnull, stderr=self.devnull)
            self.logger.trace('_subprocess_call: Subprocess returned code %d.' % exit_code)
        except subprocess.CalledProcessError as process_error:
            # Eat exceptions because it will properly return False this way.
            self.logger.error('Subprocess call failed!')

        return exit_code == 0
