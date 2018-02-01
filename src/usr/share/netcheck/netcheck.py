# Copyright 2015-2018 Joel Allen Luellwitz and Andrew Klapp
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
import logging
import os
import random
import subprocess
import time
import traceback

import dns
import NetworkManager
import networkmetamanager

# TODO: Make these configuration options before merging in.
WIRED_DEVICE = "eth0"
WIRELESS_DEVICE = "eth1"
NETWORKMANAGER_ACTIVATION_CHECK_INTERVAL = 0.1

# TODO: Eventually make multithreaded.
# TODO: Consider checking if gpgmailer authenticated with the mail server and is
#   sending mail.
class NetCheck:
    """NetCheck monitors the wired network connection. If it is down, it attempts
    to connect to a prioritized list of wireless networks.  If nothing works, it
    will cycle through both the wired and wireless networks until one is available.
    """

    def __init__(self, config):

        self.config = config

        # Get logger
        self.logger = logging.getLogger()

        # Instantiate NetworkMetaManager
        self.network_meta = networkmetamanager.NetworkMetaManager(
            self.config['nmcli_timeout'])

        self.backup_network_check_time = datetime.datetime.now()
        self.connected_wifi_index = 0

        self.resolver = dns.resolver.Resolver()

        # This section is commented out because we connect to the backup network
        #   as soon as the program starts anyway. If FreedomPop's monthly usage
        #   requirement goes away, we should revert back to using this.
        #wifi_connection_successful = self._try_wifi_networks(0)
        #
        #if wifi_connection_successful:
        #    self.logger.info('Connected to wifi network %s during initialization.' % \
        #            self.config['wifi_network_names'][self.connected_wifi_index])
        #else:
        #    self.logger.warn('All wifi networks failed to connect during initialization.')

        # TODO: Make this change in the config file.
        self.config['network_activation_timeout'] = self.config['nmcli_timeout']

        # TODO: Add these options in the config file before merging in.
        self.wired_device = WIRED_DEVICE
        self.wireless_device = WIRELESS_DEVICE

        self.logger.info('NetCheck initialized.')

    def _dns_query(self, network, nameserver, query_name):
        """Attempts a DNS query for query_name on 'nameserver' via 'network'.
        Returns True if successful, False otherwise.
        """
        # TODO: Use something more secure than unauthenticated plaintext DNS requests.

        self.logger.trace('Querying %s for %s on network %s.' % (nameserver, query_name, network))
        success = False

        # TODO: Add support for when this is not able to obtain the IP.
        interface_ip = self._get_network_device_from_id(network).Dhcp4Config.Options['ip_address']

        self.resolver.nameservers = [nameserver]
        try:
            query_result = self.resolver.query(query_name, source=interface_ip)
            success = True

        except dns.resolver.Timeout as detail:
            # Network probably disconnected.
            self.logger.error('DNS query for %s from nameserver %s on network %s timed out. %s: %s' %
                (query_name, nameserver, network, type(detail).__name__, detail.message))

        except dns.resolver.NXDOMAIN as detail:
            # Could be either a config error or malicious DNS
            self.logger.error('DNS query for %s from nameserver %s on network %s was successful, ' +
                'but the provided domain was not found. %s: %s' %
                (query_name, nameserver, network, type(detail).__name__, detail.message))

        except dns.resolver.NoNameservers as detail:
            # Probably a config error, but chosen DNS could be down or blocked.
            self.logger.error('Could not access nameserver %s on network %s. %s: %s' % (nameserver,
                network, type(detail).__name__, detail.message))

        except Exception as detail:
            # Something happened that is outside of Netcheck's scope.
            self.logger.error(
                'Unexpected error querying %s from nameserver %s on network %s. %s: %s' %
                (query_name, nameserver, network, type(detail).__name__, detail.message))

        return success

    def _dns_works(self, network):
        """Runs up to two DNS queries over the given network using two random nameservers for
        two random domains from the config file's list of DNS servers and domains. Returns
        True if either DNS query succeeds. False otherwise.
        """

        # Picks two exclusive-random choices from the nameserver and domain name lists.
        nameservers = random.sample(self.config['nameservers'], 2)
        query_names = random.sample(self.config['dns_queries'], 2)

        dns_works = False

        self.logger.trace(
            '_dns_works: Attempting first DNS query for %s on interface %s '
            'using name server %s.' % (query_names[0], network, nameservers[0]))
        if self._dns_query(network, nameservers[0], query_names[0]):
            dns_works = True
            self.logger.trace('_dns_works: First DNS query on %s successful.' % network)
        else:
            self.logger.debug(
                '_dns_works: First DNS query for %s failed on interface %s using name '
                'server %s. Attempting second query.' %
                (query_names[0], network, nameservers[0]))
            self.logger.trace(
                '_dns_works: Attempting second DNS query for %s on interface %s using name '
                'server %s.' % (query_names[1], network, nameservers[1]))
            if (self._dns_query(network, nameservers[1], query_names[1])):
                dns_works = True
                self.logger.trace('_dns_works: Second DNS query on %s successful.' %
                                  network)
            else:
                self.logger.debug(
                    '_dns_works: Second DNS query for %s failed on interface %s using name '
                    'server %s. Assuming network is down.' %
                    (query_names[1], network, nameservers[1]))

        return dns_works

    def _connect_and_check_dns(self, network_name):
        """Connects to a network and checks DNS availability if connection was successful.
        Returns true on success, false on failure.
        """

        self.logger.trace('_connect_and_check_dns: Attempting to connect to and reach the '
                          'Internet over %s.' % network_name)

        overall_success = False
        connection_successful = self.network_meta.connect(network_name)
        if not(connection_successful):
            self.logger.debug('_connect_and_check_dns: Could not connect to network %s.' %
                              network_name)
        else:
            self.logger.trace('_connect_and_check_dns: Connected to network %s.' %
                              network_name)
            dns_successful = self._dns_works(network_name)
            if not(dns_successful):
                self.logger.debug('_connect_and_check_dns: DNS on network %s failed.' %
                                  network_name)
            else:
                self.logger.trace('_connect_and_check_dns: DNS on network %s successful.' %
                                  network_name)
                overall_success = True

        return overall_success

    # Checks the connection to a network and checks DNS availability if connection exists.
    #   Returns true on success, false on failure.
    def _check_connection_and_check_dns(self, network_name):
        self.logger.trace('_check_connection_and_check_dns: Attempting to reach the '
                          'Internet over %s.' % network_name)

        overall_success = False
        connection_active = self.network_meta.is_connected(network_name)
        if not(connection_active):
            self.logger.debug('_check_connection_and_check_dns: Not connected to network '
                              '%s.' % network_name)
        else:
            self.logger.trace('_check_connection_and_check_dns: Connected to network %s.' %
                              network_name)
            dns_successful = self._dns_works(network_name)
            if not(dns_successful):
                self.logger.debug('_check_connection_and_check_dns: DNS on network %s '
                                  'failed.' % network_name)
            else:
                self.logger.trace('_check_connection_and_check_dns: DNS on network %s '
                                  'successful.' % network_name)
                overall_success = True

        return overall_success

    def _try_wifi_networks(self, index):
        """Tries to connect to the wifi network at a specific index of the config file's
        list of networks.  If it fails, it calls itself on the next network in the list.
        """

        self.logger.trace('_try_wifi_networks: Attempting WiFi network with priority %d.' %
                          index)

        success = None

        if index >= len(self.config['wifi_network_names']):
            # Out of bounds means that we're out of networks.
            self.logger.debug('_try_wifi_networks: Reached end of wifi network list. '
                    'Setting first network as the currently connected wifi network.')
            self.connected_wifi_index = 0
            success = False

        else:
            network_name = self.config['wifi_network_names'][index]

            wifi_connection_successful = self._connect_and_check_dns(network_name)

            if wifi_connection_successful:
                self.logger.debug('_try_wifi_networks: Wifi network %s connected with '
                                  'successful DNS check.' % network_name)
                self.connected_wifi_index = index
                success = True

            else:
                self.logger.debug('_try_wifi_networks: Wifi network %s failed to connect or '
                                  'failed DNS check.' % network_name)
                success = self._try_wifi_networks(index + 1)

        return success

    # TODO: Consider downloading a small file upon successful connection so we are sure
    #   FreedomPop considers this network used.
    # TODO: The random interval should probably be applied after the last DNS check on the
    #   backup network. (We might have used the backup network since the last check or
    #   might even be currently connected to it.)
    def _use_backup_network(self):
        """Use the highest-priority wireless network randomly between zero and a
        user-specified number of days. Recalculate that interval every time the network is
        checked and then call _try_wifi_networks. FreedomPop requires monthly usage and is
        assumed to be the highest-priority network.
        """

        self.logger.trace('_use_backup_network: Determining if we should use the main WiFi '
                          'backup network.')

        if datetime.datetime.now() >= self.backup_network_check_time:

            self.logger.info('Trying to use backup wifi network.')

            backup_network_is_connected = self._check_connection_and_check_dns(
                # TODO: Make the backup network actually separate from the list.
                #   It should use the backup_network_name property from
                #   from the config file.
                self.config['wifi_network_names'][0])

            if backup_network_is_connected:
                self._update_successful_backup_check_time()

            else:
                self.logger.info('Trying to connect and use backup wifi network.')
                wifi_connection_successful = self._connect_and_check_dns(
                    self.config['wifi_network_names'][0])

                if wifi_connection_successful:
                    self._update_successful_backup_check_time()
                else:
                    self.backup_network_check_time = datetime.datetime.now(
                        ) + datetime.timedelta(seconds=random.uniform(
                            0, self.config['backup_network_failed_max_usage_delay']))
                    self.logger.error('Failed to use backup network. Will try again on %s.' %
                                      self.backup_network_check_time)

        else:
            self.logger.trace('Skipping backup network check because it is not time yet.')

    def _update_successful_backup_check_time(self):
        """Determine the next time we will try to connect to the main backup WiFi network
        after a successful use.
        """
        self.logger.trace('_update_successful_backup_check_time: Successfully connected to '
                          'main backup WiFi network.')

        # Convert days to seconds.
        delay_range_in_seconds = self.config[
            'backup_network_max_usage_delay'] * 24 * 60 * 60

        self.backup_network_check_time = datetime.datetime.now() + \
            datetime.timedelta(seconds=random.uniform(0, delay_range_in_seconds))
        self.logger.info('Successfully used to backup network. Will try again on %s.' %
            self.backup_network_check_time)

    def check_loop(self):
        """Attempts to connect to the wired network and falls back to wireless networks in a
        specified priority order. Also, connects to the main backup wireless network
        periodically to comply with carrier requirements.
        """
        self.logger.info('Check loop starting.')

        current_network_name = None
        # We want this to be different than None so that we record when there is no
        #   connection when the program first starts.
        prior_network_name = -1

        while True:

            try:
                self.logger.debug('check_loop: Check loop iteration starting.')

                # Periodically connect to the main backup network because the carrier
                #   requires this.
                self._use_backup_network()

                wired_is_connected = self._check_connection_and_check_dns(
                    self.config['wired_network_name'])

                if (wired_is_connected):
                    self.logger.debug('check_loop: Wired network still connected with '
                                      'successful DNS check.')
                    current_network_name = self.config['wired_network_name']
                else:
                    self.logger.debug('check_loop: Wired network is not connected.')

                    wired_connection_success = self._connect_and_check_dns(
                        self.config['wired_network_name'])

                    if (wired_connection_success):
                        current_network_name = self.config['wired_network_name']
                        self.logger.info(
                            'Wired network connected with successful DNS check.')
                    else:
                        self.logger.debug('check_loop: Wired network failed to connect.')

                        current_wifi_network_name = self.config[
                            'wifi_network_names'][self.connected_wifi_index]
                        wifi_is_connected = self._check_connection_and_check_dns(
                            current_wifi_network_name)

                        if (wifi_is_connected):
                            # Set current_network_name because network may already be
                            #   connected during initialization.
                            current_network_name = current_wifi_network_name
                            self.logger.debug('check_loop: Current wifi network %s still '
                                              'active.' % current_wifi_network_name)
                        else:
                            self.logger.debug(
                                'check_loop: Current wifi network %s is no longer '
                                'connected.' % current_wifi_network_name)

                            wifi_connection_successful = self._try_wifi_networks(0)

                            if (wifi_connection_successful):
                                current_network_name = self.config[
                                    'wifi_network_names'][self.connected_wifi_index]
                                self.logger.info('Connected to wireless network %s.' %
                                                 current_network_name)
                            else:
                                current_network_name = None
                                self.logger.debug(
                                    'check_loop: All wireless networks failed to connect.')

                prior_network_name = self._log_connection_change(
                    prior_network_name, current_network_name)

            except Exception as e:
                self.logger.error('Unexpected error %s: %s\n' % (type(e).__name__,
                                  e.message))
                self.logger.error(traceback.format_exc())

            sleep_time = random.uniform(0, self.config['sleep_range'])
            self.logger.debug('Sleeping for %f seconds!' % sleep_time)
            time.sleep(sleep_time)

    def _log_connection_change(self, prior_network_name, current_network_name):
        """Logs changes to the network in use."""
        if prior_network_name != current_network_name:
            if current_network_name is None:
                self.logger.error('Connection change: Not connected to any network!')
            elif current_network_name != self.config['wired_network_name']:
                self.logger.warn('Connection change: Connected to wireless network %s.' %
                                 current_network_name)
            else:
                self.logger.info('Connection change: Connected to the wired network.')

        return current_network_name

    def _activate_network(self, network_id):
        """Attempts to activate a network with the provided network id on the provided network
        device. Returns true on success, false on failure or timeout."""
        success = False
        give_up = False

        network_device = self._get_network_device_from_id(network_id)

        active_connection = NetworkManager.NetworkManager.ActivateConnection(
            self.connection_id_table[network_id], network_device, '/')

        time_to_give_up = datetime.datetime.now() + self.config['network_activation_timeout']

        while (success is not True and give_up is not False):
            if active_connection.State == 2:
                success = True
            elif (active_connection.State == 3 or active_connection.State == 4 or
                  datetime.datetime.now() > time_to_give_up):
                give_up = True
            time.sleep(NETWORKMANAGER_ACTIVATION_CHECK_INTERVAL)

        return success

    def _get_network_device_from_id(self, network_id):
        """Guesses which network device to use based on the wired_network_name config
        value. Returns a NetworkManager device object."""
        # This will probably be a little smarter later on.
        network_device = self.wireless_device

        if network_id == self.config['wired_network_name']:
            network_device = self.wired_device

        return network_device
