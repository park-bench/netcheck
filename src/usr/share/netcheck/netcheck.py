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

        # Create a logger.
        self.logger = logging.getLogger(__name__)

        self.network_helper = networkmanagerhelper.NetworkManagerHelper(self.config)

        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = self.config['dns_timeout']
        self.resolver.lifetime = self.config['dns_timeout']

        self.next_available_connections_check_time = \
            self._calculate_available_connections_check_time(datetime.datetime.now())

        # Verify each connection is known to NetworkManager.
        nm_connection_set = set(self.network_helper.get_all_connection_ids())
        known_connection_set = set(self.config['connection_ids'])
        missing_connections = known_connection_set - nm_connection_set
        if missing_connections:
            raise UnknownConnectionException(
                'Connection "%s" is not known to NetworkManager.'
                % missing_connections.pop())

        required_usage_connection_set = set(self.config['required_usage_connection_ids'])
        missing_required_usage_connections = \
            required_usage_connection_set - known_connection_set
        if missing_required_usage_connections:
            raise UnknownConnectionException(
                'Connection "%s" is not in the list of configured connection_ids.' %
                missing_required_usage_connections.pop())

        self.connection_contexts = {}
        for connection_id in self.config['connection_ids']:
            connection_context = {}
            connection_context['id'] = connection_id
            connection_context['activated'] = False
            connection_context['next_check'] = None
            connection_context['last_check_time'] = None
            connection_context['is_required_usage_connection'] = False
            connection_context['next_required_usage_check'] = None
            self.connection_contexts[connection_id] = connection_context

        for connection_id in required_usage_connection_set:
            self.connection_contexts[connection_id]['is_required_usage_connection'] = True

        self.prior_connection_ids = []

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

    def _activate_with_free_device_and_check_dns(self, loop_time, connection_context):
        """ TODO: Update.
        Activates a connection and checks DNS availability if the activation was
        successful.

        connection_context: TODO: The name of the connection as displayed in NetworkManager.
        Returns True on successful DNS lookup, False otherwise.
        """

        self.logger.trace('_activate_connection_and_check_dns: Attempting to activate and '
                          'reach the Internet over connection %s.', connection_context['id'])

        activation_successful = self.network_helper. \
            activate_connection_with_available_device(connection_context['id'])
        if not activation_successful:
            self.logger.debug('_activate_connection_and_check_dns: Could not activate '
                              'connection %s.', connection_context['id'])
            connection_context['activated'] = False
        else:
            self.logger.trace('_activate_connection_and_check_dns: Connection %s activated.',
                              connection_context['id'])
            dns_successful = self._dns_works(connection_context['id'])
            if not dns_successful:
                self.logger.debug('_activate_connection_and_check_dns: DNS on connection %s '
                                  'failed.', connection_context['id'])

                connection_context['activated'] = False
                deactivation_successful = self.network_helper. \
                    deactivate_connection(connection_context['id'])

                if deactivation_successful:
                    self.logger.info(
                        'Deactivated connection "%s".', connection_context['id'])
                else:
                    self.logger.error('Deactivation failed for connection "%s".',
                                      connection_context['id'])
            else:
                self.logger.trace('_activate_connection_and_check_dns: DNS on connection %s '
                                  'successful.', connection_context['id'])
                connection_context['activated'] = True
                connection_context['last_check_time'] = loop_time
                connection_context['next_check'] = self._calculate_periodic_check_time()

        return connection_context['activated']

    def _steal_device_and_check_dns(self, loop_time, connection_context,
                                    excluded_connection_ids=None):
        """ TODO: Update.
        Activates a connection and checks DNS availability if the activation was
        successful.

        connection_context: TODO: The name of the connection as displayed in NetworkManager.
        excluded_connection_ids:
        Returns True on successful DNS lookup, False otherwise.
        """

        self.logger.trace('_activate_connection_and_check_dns: Attempting to activate and '
                          'reach the Internet over connection %s.', connection_context['id'])

        activation_successful, deactivated_connection_id = self.network_helper. \
            activate_connection_and_steal_device(
                connection_context['id'], excluded_connection_ids)
        if not activation_successful:
            self.logger.debug('_activate_connection_and_check_dns: Could not activate '
                              'connection %s.', connection_context['id'])
            connection_context['activated'] = False
        else:
            self.logger.trace('_activate_connection_and_check_dns: Connection %s activated.',
                              connection_context['id'])
            dns_successful = self._dns_works(connection_context['id'])
            if not dns_successful:
                self.logger.debug('_activate_connection_and_check_dns: DNS on connection %s '
                                  'failed.', connection_context['id'])

                connection_context['activated'] = False
                deactivation_successful = self.network_helper. \
                    deactivate_connection(connection_context['id'])

                if deactivation_successful:
                    self.logger.info(
                        'Deactivated connection "%s".', connection_context['id'])
                else:
                    self.logger.error('Deactivation failed for connection "%s".',
                                      connection_context['id'])
            else:
                self.logger.trace('_activate_connection_and_check_dns: DNS on connection %s '
                                  'successful.', connection_context['id'])
                connection_context['activated'] = True
                connection_context['last_check_time'] = loop_time
                connection_context['next_check'] = self._calculate_periodic_check_time()
                if deactivated_connection_id:
                    self.connection_contexts[deactivated_connection_id]['activated'] = False

        return connection_context['activated']

    def _check_connection_and_check_dns(self, connection_context):
        """Checks if a connection is active and if successful, checks DNS availability.

        connection_context: TODO: The name of the connection as displayed in NetworkManager.
        Returns True on successful DNS lookup, False otherwise.
        """
        self.logger.trace('_check_connection_and_check_dns: Attempting to reach the '
                          'Internet over connection %s.', connection_context['id'])

        overall_success = False
        connection_active = self.network_helper.connection_is_activated(
            connection_context['id'])
        if not connection_active:
            self.logger.debug(
                '_check_connection_and_check_dns: Connection %s not activated.',
                connection_context['id'])
            connection_context['activated'] = False
        else:
            self.logger.trace('_check_connection_and_check_dns: Connection %s activated.',
                              connection_context['id'])
            dns_successful = self._dns_works(connection_context['id'])
            if not dns_successful:
                self.logger.debug(
                    '_check_connection_and_check_dns: DNS on connection %s failed.',
                    connection_context['id'])
                connection_context['activated'] = False

                deactivation_successful = self.network_helper. \
                    deactivate_connection(connection_context['id'])

                if deactivation_successful:
                    self.logger.info(
                        'Deactivated connection "%s".', connection_context['id'])
                else:
                    self.logger.error('Deactivation failed for connection '
                                      '"%s".', connection_context['id'])

            else:
                self.logger.trace(
                    '_check_connection_and_check_dns: DNS on connection %s successful.',
                    connection_context['id'])
                overall_success = True

        return overall_success

    # TODO: Consider downloading a small file upon successful connection so we are sure
    #   FreedomPop considers this connection used. (issue 11)
    # TODO: The random interval should probably be applied after the last DNS check on the
    #   backup connection. (We might have used the backup connection since the last check or
    #   the backup connection might even be currently activated.) (issue 12)
    def _activate_required_usage_connections(self, loop_time):
        """Activate the 'required usage' connections randomly between zero and a
        user-specified number of days.  Recalculate the activation check interval for each
        connection after every activation attempt.
        """
        self.logger.trace(
            "_use_required_usage_connections: Determining if a 'required usage' connection "
            'attempt should be made.')

        for connection_id in self.connection_contexts:
            connection_context = self.connection_contexts[connection_id]
            if connection_context['is_required_usage_connection']:
                if loop_time < connection_context['last_check_time'] \
                        + connection_context['next_required_usage_check']:
                    self.logger.trace(
                        "_use_required_usage_connections: Skipping 'required usage'"
                        ' connection check for "%s" because it is not time yet.',
                        connection_context['id'])
                else:
                    self.logger.debug("Trying to use 'required usage' connection "
                                      '"%s".', connection_context['id'])

                    connection_is_active = False
                    if connection_context['activated']:
                        connection_is_active = self._check_connection_and_check_dns(
                            connection_context)

                    if connection_is_active:
                        self._update_required_check_time_on_success(
                            loop_time, connection_context)
                    else:
                        self.logger.debug("Trying to activate and use 'required usage' "
                                          'connection "%s".', connection_context['id'])
                        activation_successful = self._steal_device_and_check_dns(
                            loop_time, connection_context)

                        if activation_successful:
                            self._update_required_check_time_on_success(
                                loop_time, connection_context)
                        else:
                            self._update_required_check_time_on_failure(
                                loop_time, connection_context)

    def _update_required_check_time_on_success(self, loop_time, connection_context):
        """Determine the next time the 'required usage' connection should be activated
        after a successful use.

        connection_context: TODO:
        """
        # Convert days to seconds.
        delay_range_in_seconds = self.config['required_usage_max_delay'] * 24 * 60 * 60

        connection_context['last_check_time'] = loop_time
        connection_context['next_required_usage_check'] = datetime.timedelta(
            seconds=random.uniform(0, delay_range_in_seconds))
        self.logger.info(
            'Will attempt \'required usage\' connection "%s" on %s.',
            connection_context['id'], connection_context['last_check_time']
            + connection_context['next_required_usage_check'])

    def _update_required_check_time_on_failure(self, loop_time, connection_context):
        """ TODO: """
        connection_context['last_check_time'] = loop_time
        connection_context['next_required_usage_check'] = datetime.timedelta(
            seconds=random.uniform(0, self.config['required_usage_failed_retry_delay']))
        self.logger.debug(
            'Failed to use \'required usage\' connection "%s". Will try again on %s.',
            connection_context['id'], connection_context['last_check_time']
            + connection_context['next_required_usage_check'])

    # TODO: Put this at the begining fo the class and put internal methods in calling order.
    def start(self):
        """ TODO: """

        # Quickly connect to connections in priority order.
        self.network_helper.activate_connections_quickly(self.config['connection_ids'])

        init_time = datetime.datetime.now()

        # Go through all required usage connections.
        self._cycle_through_required_usage_connections(init_time)

        # Connect back to connections in priority order.
        self._activate_and_check_connections_in_priority_order(init_time)

        self._main_loop()

    def _cycle_through_required_usage_connections(self, init_time):
        """ TODO: """
        for connection_id in self.connection_contexts:
            connection_context = self.connection_contexts[connection_id]
            if connection_context['is_required_usage_connection']:
                activation_successful = False
                try:
                    activation_successful = \
                        self._steal_device_and_check_dns(init_time, connection_context)
                except Exception as exception:
                    connection_context['activated'] = False
                    self.logger.error(
                        'Exception thrown while initially attempting to activate required '
                        'usage connection "%s". %s: %s', connection_context['id'],
                        type(exception).__name__, str(exception))
                    self.logger.error(traceback.format_exc())
                if activation_successful:
                    self._update_required_check_time_on_success(
                        init_time, connection_context)
                else:
                    self._update_required_check_time_on_failure(
                        init_time, connection_context)

    def _activate_and_check_connections_in_priority_order(self, init_time):
        """ TODO: """
        for connection_id in self.config['connection_ids']:
            connection_context = self.connection_contexts[connection_id]
            if connection_context['activated']:
                self.prior_connection_ids.append(connection_context['id'])
            else:
                activation_successful = False
                try:
                    activation_successful = self._steal_device_and_check_dns(
                        loop_time=init_time,
                        connection_context=connection_context,
                        excluded_connection_ids=self.prior_connection_ids)
                except Exception as exception:
                    connection_context['activated'] = False
                    self.logger.error(
                        'Exception thrown while initially attempting to activate '
                        'prioritized connection "%s". %s: %s', connection_context['id'],
                        type(exception).__name__, str(exception))

                if activation_successful:
                    self.prior_connection_ids.append(connection_context['id'])

        if not self.prior_connection_ids:
            self.logger.error('Initial connection state: No connections are active!')
        else:
            self.logger.info('Initial connection state: Activated connections: "%s".',
                             '", "'.join(self.prior_connection_ids))

    def _calculate_periodic_check_time(self):
        return datetime.timedelta(seconds=random.uniform(
            0, self.config['connection_periodic_check_time']))

    def _main_loop(self):
        """ TODO: Update:
        Attempts to activate the wired connection and falls back to wireless connections
        in a specified priority order. Also, activates the main backup wireless connection
        periodically to comply with carrier requirements.
        """
        self.logger.info('Check loop starting.')

        while True:
            self.logger.debug('check_loop: Check loop iteration starting.')
            try:
                loop_time = datetime.datetime.now()

                # Periodically activates the main backup connection because the carrier
                #   requires this.
                # TODO: Eventually store the last required usage access times under var.
                self._activate_required_usage_connections(loop_time)

                for connection_id in self.connection_contexts:
                    try:
                        connection_context = self.connection_contexts[connection_id]
                        if connection_context['activated'] and \
                                connection_context['last_check_time'] \
                                + connection_context['next_check'] < loop_time:

                            connection_is_activated = self._check_connection_and_check_dns(
                                connection_context)

                            if connection_is_activated:
                                self.logger.debug(
                                    'check_loop: Connection %s still active.',
                                    connection_id)
                            else:
                                self.logger.debug(
                                    'check_loop: Connection %s is no longer active.',
                                    connection_id)

                    except Exception as exception:
                        self.logger.error('Unexpected error while checking if connection is '
                                          'active %s: %s\n',
                                          type(exception).__name__, str(exception))
                        self.logger.error(traceback.format_exc())

                    connection_context['next_check'] = self._calculate_periodic_check_time()

                current_connection_ids = []
                for connection_id in self.connection_contexts:
                    try:
                        connection_context = self.connection_contexts[connection_id]
                        if not self.network_helper.connection_is_activated(
                                connection_context['id']):
                            connection_context['activated'] = False
                        elif not connection_context['activated']:
                            self.network_helper.deactivate_connection(
                                connection_context['id'])
                        self._activate_with_free_device_and_check_dns(
                            loop_time, connection_context)
                        if connection_context['activated']:
                            current_connection_ids.append(connection_context['id'])
                    except Exception as exception:
                        self.logger.error('Unexpected error while attepting to activate '
                                          'free devices %s: %s\n',
                                          type(exception).__name__, str(exception))
                        self.logger.error(traceback.format_exc())

                # TODO: Consider having a periodic update indicating the program is still
                #   running and its current status.
                self._log_connection_change(
                    self.prior_connection_ids, current_connection_ids)
                self.prior_connection_ids = current_connection_ids

                # Scan wireless devices.
                if self.next_available_connections_check_time < loop_time:
                    self.network_helper.update_available_connections()
                    self.next_available_connections_check_time = \
                        self._calculate_available_connections_check_time(loop_time)

            except Exception as exception:
                self.logger.error('Unexpected error %s: %s\n',
                                  type(exception).__name__, str(exception))
                self.logger.error(traceback.format_exc())

            time.sleep(.1)

    def _calculate_available_connections_check_time(self, loop_time):
        """ TODO: """
        return loop_time + datetime.timedelta(seconds=random.uniform(
            0, self.config['available_connections_check_time']))

    def _log_connection_change(self, prior_connection_ids, current_connection_ids):
        """Logs changes to the connections in use.

        prior_connection_id: The NetworkManager display names of the active connections at
          the end of the prior main program loop.
        current_connection_id: The NetworkManager display names of the active connections at
          the end of the current main program loop.
        """
        prior_connection_set = set(prior_connection_ids)
        current_connection_set = set(current_connection_ids)
        if prior_connection_set != current_connection_set:
            if not current_connection_set:
                self.logger.error('Connection change: No connections are active!')
            else:
                connections_deactivated = prior_connection_set - current_connection_set
                connections_activated = current_connection_set - prior_connection_set

                if connections_activated:
                    connections_activated_string = '\n  Newly activated connections "%s"' % \
                        '", "'.join(connections_activated)

                if connections_deactivated:
                    if connections_deactivated:
                        connections_deactivated_string = \
                            '\n  Newly deactivated connection: "%s"' % \
                            '", "'.join(connections_deactivated)

                    self.logger.warn('Connection change: %s%s', connections_activated_string,
                                     connections_deactivated_string)
                else:
                    self.logger.info('Connection change: %s', connections_activated_string)
