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
import random
import time
import traceback
import dns
import networkmanagerhelper

# TODO: Eventually make multithreaded.
# TODO: Consider checking if gpgmailer authenticated with the mail server and is
#   sending mail.
class NetCheck(object):
    """NetCheck monitors the wired network connection. If it is down, it attempts
    to connect to a prioritized list of wireless networks.  If nothing works, it
    will cycle through both the wired and wireless networks until one is available.
    """

    def __init__(self, config):

        self.config = config

        # Get logger
        self.logger = logging.getLogger()

        self.network_helper = networkmanagerhelper.NetworkManagerHelper(
            self.config)

        self.backup_network_check_time = datetime.datetime.now()
        self.connected_wifi_index = 0

        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = config['dns_timeout']
        self.resolver.lifetime = config['dns_timeout']

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

        self.logger.info('NetCheck initialized.')

    def _dns_query(self, connection_id, nameserver, query_name):
        """Attempts a DNS query for query_name on 'nameserver' via 'network'.
        Returns True if successful, False otherwise.
        """
        # TODO: Use something more secure than unauthenticated plaintext DNS requests.

        self.logger.trace('Querying %s for %s on connection %s.', nameserver, query_name,
                          connection_id)
        success = False

        interface_ip = self.network_helper.get_connection_ip(connection_id)

        if interface_ip is not None:
            self.resolver.nameservers = [nameserver]
            try:
                self.resolver.query(query_name, source=interface_ip)
                success = True

            except dns.resolver.Timeout as exception:
                # Network probably disconnected.
                self.logger.error(
                    'DNS query for %s from nameserver %s on connection %s timed out. %s: %s',
                    query_name, nameserver, connection_id, type(exception).__name__, str(exception))

            except dns.resolver.NXDOMAIN as exception:
                # Could be either a config error or malicious DNS
                self.logger.error(
                    'DNS query for %s from nameserver %s on connection %s was successful,'
                    ' but the provided domain was not found. %s: %s',
                    query_name, nameserver, connection_id, type(exception).__name__, str(exception))

            except dns.resolver.NoNameservers as exception:
                # Probably a config error, but chosen DNS could be down or blocked.
                self.logger.error('Could not access nameserver %s on connection %s. %s: %s',
                    nameserver, connection_id, type(exception).__name__, str(exception))

            except Exception as exception:
                # Something happened that is outside of Netcheck's scope.
                self.logger.error(
                    'Unexpected error querying %s from nameserver %s on connection %s. %s: %s',
                    query_name, nameserver, connection_id, type(exception).__name__,
                    str(exception))

        return success

    def _dns_works(self, connection_id):
        """Runs up to two DNS queries over the given connection using two random nameservers
        for two random domains from the config file's list of DNS servers and domains.

        Returns True if either DNS query succeeds. False otherwise.
        """

        # Picks two exclusive-random choices from the nameserver and domain name lists.
        nameservers = random.sample(self.config['nameservers'], 2)
        query_names = random.sample(self.config['dns_queries'], 2)

        dns_works = False

        self.logger.trace(
            '_dns_works: Attempting first DNS query for connection %s on interface %s '
            'using name server %s.', query_names[0], connection_id, nameservers[0])
        if self._dns_query(connection_id, nameservers[0], query_names[0]):
            dns_works = True
            self.logger.trace('_dns_works: First DNS query on connection %s successful.',
                              connection_id)
        else:
            self.logger.debug(
                '_dns_works: First DNS query for connection %s failed on interface %s using '
                'name server %s. Attempting second query.', query_names[0], connection_id,
                nameservers[0])
            self.logger.trace(
                '_dns_works: Attempting second DNS query for connection %s on interface %s '
                'using name server %s.', query_names[1], connection_id, nameservers[1])
            if (self._dns_query(connection_id, nameservers[1], query_names[1])):
                dns_works = True
                self.logger.trace(
                    '_dns_works: Second DNS query on connection %s successful.',
                    connection_id)
            else:
                self.logger.debug(
                    '_dns_works: Second DNS query for %s failed on interface %s using name '
                    'server %s. Assuming connection is down.', query_names[1],
                    connection_id, nameservers[1])

        return dns_works

    def _connect_and_check_dns(self, connection_id):
        """Connects to a connection and checks DNS availability if connection was successful.
        Returns true on success, false on failure.
        """

        self.logger.trace('_connect_and_check_dns: Attempting to connect to and reach the '
                          'Internet over connection %s.', connection_id)

        overall_success = False
        connection_successful = self.network_helper.activate_connection(connection_id)
        if not(connection_successful):
            self.logger.debug('_connect_and_check_dns: Could not activate connection %s.',
                              connection_id)
        else:
            self.logger.trace('_connect_and_check_dns: Connection %s activated.',
                              connection_id)
            dns_successful = self._dns_works(connection_id)
            if not(dns_successful):
                self.logger.debug('_connect_and_check_dns: DNS on connection %s failed.',
                                  connection_id)
            else:
                self.logger.trace('_connect_and_check_dns: DNS on connection %s successful.',
                                  connection_id)
                overall_success = True

        return overall_success

    # Checks if a connection is active and checks DNS availability if it is.
    #   Returns true on success, false on failure.
    def _check_connection_and_check_dns(self, connection_id):
        self.logger.trace('_check_connection_and_check_dns: Attempting to reach the '
                          'Internet over connection %s.', connection_id)

        overall_success = False
        connection_active = self.network_helper.connection_is_activated(connection_id)
        if not(connection_active):
            self.logger.debug(
                '_check_connection_and_check_dns: Connection %s not activated.',
                connection_id)
        else:
            self.logger.trace('_check_connection_and_check_dns: Connection %s activated.',
                              connection_id)
            dns_successful = self._dns_works(connection_id)
            if not(dns_successful):
                self.logger.debug(
                    '_check_connection_and_check_dns: DNS on connection %s failed.',
                    connection_id)
            else:
                self.logger.trace(
                    '_check_connection_and_check_dns: DNS on connection %s successful.',
                    connection_id)
                overall_success = True

        return overall_success

    def _try_wifi_networks(self, index):
        """Tries to connect to the wireless connection at a specific index of the config file's
        list of connection IDs.  If it fails, it calls itself on the next connection in the
        list.
        """

        self.logger.trace(
            '_try_wifi_networks: Attempting wireless connection with priority %d.', index)

        success = None

        if index >= len(self.config['wifi_network_names']):
            # Out of bounds means that we're out of connection.
            self.logger.debug(
                '_try_wifi_networks: Reached end of wireless connection list. Setting first '
                'connection as the currently connected connection.')
            self.connected_wifi_index = 0
            success = False

        else:
            connection_id = self.config['wifi_network_names'][index]

            wifi_connection_successful = self._connect_and_check_dns(connection_id)

            if wifi_connection_successful:
                self.logger.debug(
                    '_try_wifi_networks: wireless connection %s is activated with successful '
                    'DNS check.', connection_id)
                self.connected_wifi_index = index
                success = True

            else:
                self.logger.debug(
                    '_try_wifi_networks: wireless connection %s failed to activate or failed '
                    ' DNS check.', connection_id)
                success = self._try_wifi_networks(index + 1)

        return success

    # TODO: Consider downloading a small file upon successful connection so we are sure
    #   FreedomPop considers this network used.
    # TODO: The random interval should probably be applied after the last DNS check on the
    #   backup connection. (We might have used the backup connection since the last check or
    #   might even be currently connected to it.)
    def _use_backup_network(self):
        """Use the highest-priority wireless connection randomly between zero and a
        user-specified number of days. Recalculate that interval every time the connection
        is checked and then call _try_wifi_networks. FreedomPop requires monthly usage and
        is assumed to be the highest-priority connection.
        """

        self.logger.trace(
            '_use_backup_network: Determining if we should use the main wireless backup '
            'connection.')

        if datetime.datetime.now() >= self.backup_network_check_time:

            self.logger.info('Trying to use backup wifi connection.')

            # TODO: Make the backup connection actually separate from the list.
            #   It should use the backup_network_name property from
            #   from the config file.
            backup_connection_is_active = self._check_connection_and_check_dns(
                self.config['wifi_network_names'][0])

            if backup_connection_is_active:
                self._update_successful_backup_check_time()

            else:
                self.logger.info('Trying to connect and use backup wifi connection.')
                wifi_connection_successful = self._connect_and_check_dns(
                    self.config['wifi_network_names'][0])

                if wifi_connection_successful:
                    self._update_successful_backup_check_time()
                else:
                    self.backup_network_check_time = datetime.datetime.now(
                        ) + datetime.timedelta(seconds=random.uniform(
                            0, self.config['backup_network_failed_max_usage_delay']))
                    self.logger.error(
                        'Failed to use backup connection. Will try again on %s.',
                        self.backup_network_check_time)

        else:
            self.logger.trace('Skipping backup connection check because it is not time yet.')

    def _update_successful_backup_check_time(self):
        """Determine the next time we will try to connect to the main backup wireless
        connection after a successful use.
        """
        self.logger.trace(
            '_update_successful_backup_check_time: Successfully connected to main backup '
            'wireless connection.')

        # Convert days to seconds.
        delay_range_in_seconds = self.config[
            'backup_network_max_usage_delay'] * 24 * 60 * 60

        self.backup_network_check_time = datetime.datetime.now() + \
            datetime.timedelta(seconds=random.uniform(0, delay_range_in_seconds))
        self.logger.info('Successfully used to backup connection. Will try again on %s.',
            self.backup_network_check_time)

    def check_loop(self):
        """Attempts to connect to the wired connection and falls back to wireless
        connections in a specified priority order. Also, connects to the main backup
        wireless connections periodically to comply with carrier requirements.
        """
        self.logger.info('Check loop starting.')

        current_connection_name = None
        # We want this to be different than None so that we record when there is no
        #   connection when the program first starts.
        prior_connection_name = -1

        while True:

            try:
                self.logger.debug('check_loop: Check loop iteration starting.')

                # Periodically connect to the main backup connection because the carrier
                #   requires this.
                self._use_backup_network()

                wired_is_connected = self._check_connection_and_check_dns(
                    self.config['wired_network_name'])

                if (wired_is_connected):
                    self.logger.debug(
                        'check_loop: Wired connection still active with successful DNS '
                        'check.')
                    current_connection_name = self.config['wired_network_name']
                else:
                    self.logger.debug('check_loop: Wired connection is not active.')

                    wired_connection_success = self._connect_and_check_dns(
                        self.config['wired_network_name'])

                    if (wired_connection_success):
                        current_connection_name = self.config['wired_network_name']
                        self.logger.info(
                            'Wired connection active with successful DNS check.')
                    else:
                        self.logger.debug(
                            'check_loop: Wired connection failed to activate.')

                        current_wifi_connection_id = self.config[
                            'wifi_network_names'][self.connected_wifi_index]
                        wifi_is_connected = self._check_connection_and_check_dns(
                            current_wifi_connection_id)

                        if (wifi_is_connected):
                            # Set current_connection_name because connection may have been
                            #   activated during initialization.
                            current_connection_name = current_wifi_connection_id
                            self.logger.debug(
                                'check_loop: Current wireless connection %s still active.',
                                current_wifi_connection_id)
                        else:
                            self.logger.debug(
                                'check_loop: Current wireless connection %s is no longer '
                                'active.', current_wifi_connection_id)

                            wifi_connection_successful = self._try_wifi_networks(0)

                            if (wifi_connection_successful):
                                current_connection_name = self.config[
                                    'wifi_network_names'][self.connected_wifi_index]
                                self.logger.info('Connected to wireless connection %s.',
                                                 current_connection_name)
                            else:
                                current_connection_name = None
                                self.logger.debug(
                                    'check_loop: All wireless connections failed to activate.')

                prior_connection_name = self._log_connection_change(
                    prior_connection_name, current_connection_name)

            except Exception as exception:
                self.logger.error('Unexpected error %s: %s\n', type(exception).__name__,
                                  str(exception))
                self.logger.error(traceback.format_exc())

            sleep_time = random.uniform(0, self.config['sleep_range'])
            self.logger.debug('Sleeping for %f seconds!', sleep_time)
            time.sleep(sleep_time)

    def _log_connection_change(self, prior_connection_name, current_connection_name):
        """Logs changes to the connection in use."""
        if prior_connection_name != current_connection_name:
            if current_connection_name is None:
                self.logger.error('Connection change: No connections are active!')
            elif current_connection_name != self.config['wired_network_name']:
                self.logger.warn('Connection change: Wireless connection %s is active.',
                                 current_connection_name)
            else:
                self.logger.info('Connection change: Wired connection is active.')

        return current_connection_name
