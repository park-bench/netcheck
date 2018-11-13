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

__all__ = ['NetCheck']
__author__ = 'Joel Luellwitz and Andrew Klapp'
__version__ = '0.8'

import datetime
import logging
import random
import time
import traceback
import dns.resolver
import networkmanagerhelper

class UnknownConnectionException(Exception):
    """Thrown during instantiation if a connection ID is not known to NetworkManager."""


# TODO: Eventually make multithreaded. (issue 8)
# TODO: Consider checking if gpgmailer authenticated with the mail server and is sending
#   mail. (issue 9)
class NetCheck(object):
    """NetCheck tries to maintain as many active connections to the Internet as possible. It
    activates connections from a list of known connections using all available network
    devices. It also periodically makes DNS requests to make sure the connections are
    actually on the Internet.
    """

    def __init__(self, config):
        """Instantiates the class.

        config: The program configuration dictionary.
        """

        self.config = config

        # Get logger
        self.logger = logging.getLogger()

        self.network_helper = networkmanagerhelper.NetworkManagerHelper(self.config)

        self.backup_connection_check_time = datetime.datetime.now()
        self.activated_wireless_index = 0

        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = config['dns_timeout']
        self.resolver.lifetime = config['dns_timeout']

        # Verify each connection is known to NetworkManager.
        # TODO: This is currently pseduocode. Clean this up.
        nm_connections_set = set(self.network_helper.get_all_enabled_connections())
        known_connections_set = set(config['connection_ids'])
        missing_connections = known_connections_set - nm_connections_set
        if missing_connections:
            raise UnknownConnectionException(
                'Connection "%s" is not known to NetworkManager.' % missing_connections[0])

        self.connection_contexts = {}
        for connection_id in config['connection_ids']:
            connection_context = {}
            connection_context.id = connection_id
            connection_context.activated = False
            connection_context.next_check = None
            connection_context.last_successful_check = None
            connection_context.next_required_usage_check = None
            self.connection_contexts[connection_id] = connection_context

        for connection_id in config['required_usage_max_delay']:
            self.connection_contexts[connection_id].next_required_usage_check = \
                time.time() + random(0, number(config['required_usage_max_delay']));

        self.logger.info('NetCheck initialized.')

    def _dns_query(self, connection_id, nameserver, query_name):
        """Attempts a DNS query for query_name on 'nameserver' via 'connection_id'.

        connection_id: The name of the connection as displayed in NetworkManager.
        nameserver: The IP address of the name server to use in the query.
        query_name: The DNS name to query.
        Returns True if successful, False otherwise.
        """
        # TODO: Use something more secure than unauthenticated plaintext DNS requests.
        #   (issue 5)

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
                # Connection is probably deactivated.
                self.logger.error(
                    'DNS query for %s from nameserver %s on connection %s timed out. %s: '
                    '%s', query_name, nameserver, connection_id, type(exception).__name__,
                    str(exception))

            except dns.resolver.NXDOMAIN as exception:
                # Could be either a config error or malicious DNS
                self.logger.error(
                    'DNS query for %s from nameserver %s on connection %s was successful,'
                    ' but the provided domain was not found. %s: %s', query_name,
                    nameserver, connection_id, type(exception).__name__, str(exception))

            except dns.resolver.NoNameservers as exception:
                # Probably a config error, but chosen DNS could be down or blocked.
                self.logger.error(
                    'Could not access nameserver %s on connection %s. %s: %s',
                    nameserver, connection_id, type(exception).__name__, str(exception))

            except Exception as exception:
                # Something happened that is outside of Netcheck's scope.
                self.logger.error(
                    'Unexpected error querying %s from nameserver %s on connection %s. %s: '
                    '%s', query_name, nameserver, connection_id, type(exception).__name__,
                    str(exception))

        return success

    def _dns_works(self, connection_id):
        """Runs up to two DNS queries over the given connection using two random nameservers
        for two random domains from the config file's list of DNS servers and domains.

        connection_id: The name of the connection as displayed in NetworkManager.
        Returns True if either DNS query succeeds.  False otherwise.
        """

        # Picks two exclusive-random choices from the nameserver and domain name lists.
        nameservers = random.sample(self.config['nameservers'], 2)
        query_names = random.sample(self.config['dns_queries'], 2)

        dns_works = False

        self.logger.trace(
            '_dns_works: Attempting first DNS query for %s on connection %s '
            'using name server %s.', query_names[0], connection_id, nameservers[0])
        if self._dns_query(connection_id, nameservers[0], query_names[0]):
            dns_works = True
            self.logger.trace('_dns_works: First DNS query on connection %s successful.',
                              connection_id)
        else:
            self.logger.debug(
                '_dns_works: First DNS query for %s failed on connection %s using '
                'name server %s. Attempting second query.', query_names[0], connection_id,
                nameservers[0])
            self.logger.trace(
                '_dns_works: Attempting second DNS query for %s on connection %s '
                'using name server %s.', query_names[1], connection_id, nameservers[1])
            if self._dns_query(connection_id, nameservers[1], query_names[1]):
                dns_works = True
                self.logger.trace(
                    '_dns_works: Second DNS query on connection %s successful.',
                    connection_id)
            else:
                self.logger.debug(
                    '_dns_works: Second DNS query for %s failed on connection %s using name '
                    'server %s. Assuming connection is down.', query_names[1],
                    connection_id, nameservers[1])

        return dns_works

    def _activate_connection_and_check_dns(self, connection_id):
        """Activates a connection and checks DNS availability if the activation was
        successful.

        connection_id: The name of the connection as displayed in NetworkManager.
        Returns True on successful DNS lookup, False otherwise.
        """

        self.logger.trace('_activate_connection_and_check_dns: Attempting to activate and '
                          'reach the Internet over connection %s.', connection_id)

        overall_success = False
        activation_successful = self.network_helper.activate_connection(connection_id)
        if not activation_successful:
            self.logger.debug('_activate_connection_and_check_dns: Could not activate '
                              'connection %s.', connection_id)
        else:
            self.logger.trace('_activate_connection_and_check_dns: Connection %s activated.',
                              connection_id)
            dns_successful = self._dns_works(connection_id)
            if not dns_successful:
                self.logger.debug('_activate_connection_and_check_dns: DNS on connection %s '
                                  'failed.', connection_id)
            else:
                self.logger.trace('_activate_connection_and_check_dns: DNS on connection %s '
                                  'successful.', connection_id)
                overall_success = True

        return overall_success

    def _check_connection_and_check_dns(self, connection_id):
        """Checks if a connection is active and if successful, checks DNS availability.

        connection_id: The name of the connection as displayed in NetworkManager.
        Returns True on successful DNS lookup, False otherwise.
        """
        self.logger.trace('_check_connection_and_check_dns: Attempting to reach the '
                          'Internet over connection %s.', connection_id)

        overall_success = False
        connection_active = self.network_helper.connection_is_activated(connection_id)
        if not connection_active:
            self.logger.debug(
                '_check_connection_and_check_dns: Connection %s not activated.',
                connection_id)
        else:
            self.logger.trace('_check_connection_and_check_dns: Connection %s activated.',
                              connection_id)
            dns_successful = self._dns_works(connection_id)
            if not dns_successful:
                self.logger.debug(
                    '_check_connection_and_check_dns: DNS on connection %s failed.',
                    connection_id)
            else:
                self.logger.trace(
                    '_check_connection_and_check_dns: DNS on connection %s successful.',
                    connection_id)
                overall_success = True

        return overall_success

    def _activate_available_connections(self, index):
        """Tries to activate the connection at the specified index of the config file's list
        of connection IDs.

        Returns True if a connection activation is successful, False otherwise.
        """

        available_connections = self.network_helper.get_available_connections()

        self.logger.trace(
            '_activate_available_connections: Available connections: %s' %
            available_connections.join(', '))

        success = False

        if index >= len(self.config['wireless_connection_ids']):
            # Out of bounds means that we're out of connections.
            self.logger.debug(
                '_try_connections: Reached end of connection list. '
                'Setting first connection as the currently activated wireless connection.')
            self.activated_wireless_index = 0

        else:
            connection_id = self.config['connection_ids'][index]

            wireless_activation_successful = self._activate_connection_and_check_dns(
                connection_id)

            if wireless_activation_successful:
                self.logger.debug(
                    '_try_connections: Connection %s is activated with successful DNS '
                    'check.', connection_id)
                success = True

            else:
                self.logger.debug(
                    '_try_connections: connection %s failed to activate or failed DNS '
                    'check.', connection_id)

        return success

    # TODO: Consider downloading a small file upon successful connection so we are sure
    #   FreedomPop considers this connection used. (issue 11)
    # TODO: The random interval should probably be applied after the last DNS check on the
    #   backup connection. (We might have used the backup connection since the last check or
    #   the backup connection might even be currently activated.) (issue 12)
    def _use_required_usage_connections(self):
        # TODO: Update comment.
        """Use the 'required usage' connections randomly between zero and a user-specified
        number of days.  Recalculate the interval for the connection every time that
        connection is checked and then call _try_connections.
        """
        self.logger.trace(
            '_use_backup_connection: Determining if the main wireless backup connection '
            'should be used.')

        if datetime.datetime.now() < self.backup_connection_check_time:
            self.logger.trace(
                'Skipping backup connection check because it is not time yet.')
        else:
            self.logger.info('Trying to use the backup wireless connection.')

            # TODO: Make the backup connection actually separate from the list. It should use
            #   the backup_connection_id property from from the config file. (issue 6)
            backup_connection_is_active = self._check_connection_and_check_dns(
                self.config['wireless_connection_ids'][0])

            if backup_connection_is_active:
                self._update_successful_backup_check_time()
            else:
                self.logger.info('Trying to activate and use backup wireless connection.')
                wireless_activation_successful = self._activate_connection_and_check_dns(
                    self.config['wireless_connection_ids'][0])

                if wireless_activation_successful:
                    self._update_successful_backup_check_time()
                else:
                    self.backup_connection_check_time = datetime.datetime.now(
                        ) + datetime.timedelta(seconds=random.uniform(
                            0, self.config['backup_connection_failed_usage_max_delay']))
                    self.logger.error(
                        'Failed to use backup connection. Will try again on %s.',
                        self.backup_connection_check_time)

    def _update_successful_backup_check_time(self):
        """Determine the next time the main backup wireless connection should be activated
        after a successful use.
        """
        self.logger.trace(
            '_update_successful_backup_check_time: Successfully activated main backup '
            'wireless connection.')

        # Convert days to seconds.
        delay_range_in_seconds = self.config[
            'backup_connection_usage_max_delay'] * 24 * 60 * 60

        self.backup_connection_check_time = datetime.datetime.now() + \
            datetime.timedelta(seconds=random.uniform(0, delay_range_in_seconds))
        self.logger.info('Successfully used backup connection. Will try again on %s.',
                         self.backup_connection_check_time)

    # TODO: Is this still appropriately named?
    def check_loop(self):
        """Attempts to activate the wired connection and falls back to wireless connections
        in a specified priority order. Also, activates the main backup wireless connection
        periodically to comply with carrier requirements.
        """
        # TODO: Get all the devices connected to something right away without checking if
        #   connection activations are actually successful. The thinking here is that the
        #   main loop can be relatively slow and the first activation attempt takes a long
        #   time delaying the availability of the other connections.
        for connection_id in config['connection_ids']:
            self.network_helper.activate_connection(connection_id)

        self.logger.info('Check loop starting.')

        current_connection_id = None
        # We want this to be different than None so that we record when there is no
        #   activated connection when the program first starts.
        prior_connection_id = -1

        while True:
            try:
                self.logger.debug('check_loop: Check loop iteration starting.')

                # Periodically activates the main backup connection because the carrier
                #   requires this.
                # TODO: Eventually store the last required usage access times under var.
                self._use_required_usage_backup_connections()

                current_connection_id = self.config['connection_ids'][self.activated_index]
                connection_is_activated = self._check_connection_and_check_dns(
                    current_connection_id)

                if connection_is_activated:
                    # Set current_connection_id because connection may have been
                    #   activated during initialization.
                    self.logger.debug(
                        'check_loop: Current wireless connection %s still active.',
                        current_connection_id)
                else:
                    self.logger.debug(
                        'check_loop: Current wireless connection %s is no longer '
                        'active.', current_wireless_connection_id)

                    activation_successful = self._try_connections(0)

                    if activation_successful:
                        current_connection_id = self.config[
                            'wireless_connection_ids'][self.activated_wireless_index]
                        self.logger.info('Connected to wireless connection %s.',
                                         current_connection_id)
                    else:
                        current_connection_id = None
                        self.logger.debug(
                            'check_loop: All wireless connections failed to '
                            'activate.')

                self._log_connection_change(prior_connection_id, current_connection_id)
                prior_connection_id = current_connection_id

            except Exception as exception:
                self.logger.error('Unexpected error %s: %s\n', type(exception).__name__,
                                  str(exception))
                self.logger.error(traceback.format_exc())

            # TODO: Scan wireless devices.
            self.network_helper.update_available_connections()

            sleep_time = random.uniform(0, self.config['sleep_range'])
            self.logger.debug('Sleeping for %f seconds!', sleep_time)
            # TODO: Check for Disconnection While "Sleeping" (issue 20)
            # TODO: Don't Sleep Until There is an Active Connection (issue 21)
            time.sleep(sleep_time)

    def _log_connection_change(self, prior_connection_id, current_connection_id):
        """Logs changes to the connection in use.

        prior_connection_id: The NetworkManager display name of the prior connection.
        current_connection_id: The NetworkManager display name of the current connection.
        """
        if prior_connection_id != current_connection_id:
            if current_connection_id is None:
                self.logger.error('Connection change: No connections are active!')
            elif current_connection_id != self.config['wired_connection_id']:
                self.logger.warn('Connection change: Wireless connection %s is active.',
                                 current_connection_id)
            else:
                self.logger.info('Connection change: Wired connection is active.')
