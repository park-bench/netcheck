# Copyright 2015-2021 Joel Allen Luellwitz and Emily Frost
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

"""NetCheck tries to maintain as many active connections to the Internet as possible."""

from __future__ import division

__all__ = ['NetCheck']
__author__ = 'Joel Luellwitz and Emily Frost'
__version__ = '0.8'

import datetime
import logging
import random
import socket
import time
import traceback
import dns.resolver
import pyroute2
import networkmanagerhelper


class RetryExhaustionException(Exception):
    """Thrown if an operation is attempted too many times without successfully completing.
    """


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

    def __init__(self, config, broadcaster):
        """Constructor.

        config: The program configuration dictionary.
        broadcaster: A parkbenchcommon.broadcaster.Broadcaster object.
        """
        self.config = config
        self.broadcaster = broadcaster
        self.prior_default_gateway_state = None

        # Create a logger.
        self.logger = logging.getLogger(__name__)

        # Create a IPRoute instance here so we don't use up all the sockets at runtime.
        self.ip_route = pyroute2.IPRoute()

        self.network_helper = networkmanagerhelper.NetworkManagerHelper(self.config)

        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = self.config['dns_timeout']
        self.resolver.lifetime = self.config['dns_timeout']

        self.next_available_connections_check_time = \
            self._calculate_available_connections_check_time(datetime.datetime.now())
        self.next_log_time = self._calculate_next_log_time(datetime.datetime.now())

        self.connection_contexts = {}
        for connection_id in self.config['connection_ids']:
            # TODO: Break netcheck.py's Logic Into Multilple Modules (issue 25)
            connection_context = {
                'id': connection_id,
                'activated': False,
                'next_periodic_check': self._calculate_periodic_check_delay(),
                'confirmed_activated_time':  None,
                'is_required_usage_connection': False,
                'required_usage_activation_delay': None,
                'failed_required_usage_activation_time': None}
            self.connection_contexts[connection_id] = connection_context

        for connection_id in config['required_usage_connection_ids']:
            self.connection_contexts[connection_id]['is_required_usage_connection'] = True

        self.prior_connection_ids = []

        self.logger.info('NetCheck initialized.')

    def start(self):
        """Starts the main program loop after performing some initialization that is not
        appropriate for the constructor. Specifically, the initialization includes updating
        the list of connections available for activation (essentially WiFi scanning),
        attempting to activate as many connections as possible as quickly as possible,
        ensuring all required usage connections are used, and finally, activating connections
        in priority order.
        """

        try:
            self.prior_default_gateway_state = self._get_default_gateway_state()
        except Exception as exception:  #pylint: disable=broad-except
            self.logger.error(
                'Error getting the default gateway state during startup. Ignoring. '
                '%s: %s\n%s', type(exception).__name__, str(exception),
                traceback.format_exc())
            self.prior_default_gateway_state = None

        try:
            self.network_helper.update_available_connections()
        except Exception as exception:  #pylint: disable=broad-except
            self.logger.error(
                'Error occurred while trying to initially update available connections. '
                'Ignoring. %s: %s', type(exception).__name__, str(exception))
            self.logger.error(traceback.format_exc())

        # Quickly connect to connections in priority order.
        try:
            self.network_helper.activate_connections_quickly(self.config['connection_ids'])
        except Exception as exception:  #pylint: disable=broad-except
            self.logger.error(
                'Error occurred while trying to activate connections quickly. Ignoring. '
                '%s: %s', type(exception).__name__, str(exception))
            self.logger.error(traceback.format_exc())

        start_time = datetime.datetime.now()

        # Go through all required usage connections.
        self._initial_cycle_through_required_usage_connections(start_time)

        # Connect back to connections in priority order.
        self._initial_activate_and_check_connections_in_priority_order(start_time)

        # The initial cycling through networks might result in a new gateway being chosen.
        try:
            self._check_for_gateway_change()
        except Exception as exception:  #pylint: disable=broad-except
            self.logger.error(
                'Error checking for default gateway state change during startup. Ignoring. '
                '%s: %s\n%s', type(exception).__name__, str(exception),
                traceback.format_exc())

        self._main_loop()

    def _initial_cycle_through_required_usage_connections(self, start_time):
        """Attempts to activate each required usage connection. This is done when the program
        starts because it is not known when the last time each required usage connection was
        used. See the configuration file for more information about required usage
        connections.

        start_time: The datetime that represents when netcheck 'start'ed.
        """
        for connection_id in self.connection_contexts:
            connection_context = self.connection_contexts[connection_id]
            if connection_context['is_required_usage_connection']:
                self._update_required_activation_delay(connection_context)
                activation_successful = False
                try:
                    activation_successful = self._steal_device_and_check_dns(
                        start_time, connection_context)
                except Exception as exception:  #pylint: disable=broad-except
                    connection_context['activated'] = False
                    self.logger.error(
                        'Exception thrown while initially attempting to activate required '
                        'usage connection "%s". %s: %s', connection_context['id'],
                        type(exception).__name__, str(exception))
                    self.logger.error(traceback.format_exc())

                if activation_successful:
                    self._log_required_usage_activation(connection_context)
                else:
                    self._update_required_activation_time_on_failure(
                        start_time, connection_context)

    def _initial_activate_and_check_connections_in_priority_order(self, start_time):
        """Activates connections based on the priority order specified in the configuration
        file. Other connections will be deactivated if they use a network device required by
        a higher priority connection.

        start_time: The datetime that represents when netcheck 'start'ed.
        """
        for connection_id in self.config['connection_ids']:
            connection_context = self.connection_contexts[connection_id]
            if connection_context['activated']:
                self.prior_connection_ids.append(connection_context['id'])
            else:
                activation_successful = False
                try:
                    activation_successful = self._steal_device_and_check_dns(
                        loop_time=start_time,
                        connection_context=connection_context,
                        excluded_connection_ids=self.prior_connection_ids)
                except Exception as exception:  #pylint: disable=broad-except
                    connection_context['activated'] = False
                    self.logger.error(
                        'Exception thrown while initially attempting to activate '
                        'prioritized connection "%s". %s: %s', connection_context['id'],
                        type(exception).__name__, str(exception))
                    self.logger.error(traceback.format_exc())

                if activation_successful:
                    self.prior_connection_ids.append(connection_context['id'])

        if not self.prior_connection_ids:
            self.logger.error('Initial connection state: No connections are active!')
        else:
            self.logger.info('Initial connection state: Activated connections: "%s".',
                             '", "'.join(self.prior_connection_ids))

    def _main_loop(self):
        """The main program loop which periodically activates required usage connections,
        periodically checks to make sure connections can still access the Internet, activates
        connections if network devices are avaiable, and scans for available connections.
        """
        self.logger.info('Main loop starting.')

        # TODO: netcheck's Main Loop Runs Too Slowly (issue 26)
        while True:
            self.logger.debug('_main_loop: Main loop iteration starting.')
            try:
                loop_time = datetime.datetime.now()

                # Periodically activates the required usage connections to maintain active
                #   accounts with ISPs.
                self._activate_required_usage_connections(loop_time)

                self._periodic_connection_check(loop_time)

                current_connection_ids = \
                    self._fix_connection_statuses_and_activate_unused_connections(loop_time)

                self._log_connections(
                    loop_time, self.prior_connection_ids, current_connection_ids)
                self.prior_connection_ids = current_connection_ids

                # Essentially this scans for available WiFi connections.
                if self.next_available_connections_check_time < loop_time:
                    self.network_helper.update_available_connections()
                    self.next_available_connections_check_time = \
                        self._calculate_available_connections_check_time(loop_time)

                self._check_for_gateway_change()

            except Exception as exception:  #pylint: disable=broad-except
                self.logger.error(
                    'Unexpected error %s: %s\n%s', type(exception).__name__, str(exception),
                    traceback.format_exc())

            # This loop takes a rather long time (about a second). Give some other processes
            #   time to do stuff.
            time.sleep(self.config['main_loop_delay'])

    # TODO: Consider downloading a small file upon successful connection so we are sure
    #   FreedomPop considers this connection used. (issue 11)
    # TODO: Eventually store the last required usage access times under /var. (issue 22)
    def _activate_required_usage_connections(self, loop_time):
        """Activates the required-usage connections randomly between zero and a
        user-specified number of days following their last use. If an activation is not
        successful, the activation is retried randomly between zero and a user-specified
        number of seconds.

        loop_time: The datetime representing when the current program loop began.
        """
        self.logger.trace(
            '_activate_required_usage_connections: Determining if a required-usage '
            'connection attempt should be made.')

        for connection_id in self.connection_contexts:
            connection_context = self.connection_contexts[connection_id]
            if connection_context['is_required_usage_connection']:
                if self._is_time_for_required_usage_check(loop_time, connection_context):
                    self.logger.trace(
                        '_activate_required_usage_connections: Skipping required-usage '
                        'activation for connection "%s" because not enough time passed yet.',
                        connection_context['id'])
                else:
                    self.logger.debug(
                        "_activate_required_usage_connections: Trying to activate 'required "
                        "usage' connection \"%s\".", connection_context['id'])

                    self._update_required_activation_delay(connection_context)
                    connection_is_active = False
                    if connection_context['activated']:
                        connection_is_active = self._check_connection_and_check_dns(
                            loop_time, connection_context)

                    if connection_is_active:
                        self._log_required_usage_activation(connection_context)
                    else:
                        self.logger.debug(
                            '_activate_required_usage_connections: Trying to activate '
                            'required-usage connection "%s".', connection_context['id'])
                        activation_successful = self._steal_device_and_check_dns(
                            loop_time, connection_context)

                        if activation_successful:
                            self._log_required_usage_activation(connection_context)
                        else:
                            self._update_required_activation_time_on_failure(
                                loop_time, connection_context)

    #pylint: disable=no-self-use
    def _is_time_for_required_usage_check(self, loop_time, connection_context):
        """Determines if it is time to do a required-usage check for a required-usage
        connection.

        loop_time: The datetime representing when the current program loop began.
        connection_context: Contains stateful information for a connection. Used to obtain
          various required-usage check delays.
        """
        do_required_usage_check = False
        if connection_context['failed_required_usage_activation_time']:
            if loop_time < connection_context['failed_required_usage_activation_time']:
                do_required_usage_check = True
        else:
            delay_delta = datetime.timedelta(
                seconds=connection_context['required_usage_activation_delay'])
            if loop_time < connection_context['confirmed_activated_time'] + delay_delta:
                do_required_usage_check = True

        return do_required_usage_check

    def _update_required_activation_delay(self, connection_context):
        """Determines the next activation delay of a required-usage connection after a
        successful use. The delay is only applied once the connection is no longer active.

        connection_context: Contains stateful information for a connection. Used to store the
          delay of the next required usage activation.
        """
        # Convert days to seconds.
        connection_context['required_usage_activation_delay'] = random.uniform(
            0, self.config['required_usage_max_delay'] * 24 * 60 * 60)

    def _log_required_usage_activation(self, connection_context):
        """Logs a required usage activation.

        connection_context: Contains stateful information for a connection. Used to retrieve
          the delay of the next required usage activation.
        """
        self.logger.info(
            'Used required-usage connection "%s". Will try again after %f days of '
            'inactivity.', connection_context['id'],
            connection_context['required_usage_activation_delay'] / 60 / 60 / 24)

    def _update_required_activation_time_on_failure(self, loop_time, connection_context):
        """Determines the time of the next required-usage activation following a required
        usage activation failure. The calculated time is disregarded if a successful
        activation occurs.

        loop_time: The datetime representing when the current program loop began.
        connection_context: Contains stateful information for a connection. Used to store the
          time of the next required usage activation following a required usage activation
          failure.
        """
        connection_context['failed_required_usage_activation_time'] = loop_time + \
            datetime.timedelta(seconds=random.uniform(
                0, self.config['required_usage_failed_retry_delay']))
        self.logger.warning(
            'Failed to use \'required usage\' connection "%s". Will try again on %s.',
            connection_context['id'],
            connection_context['failed_required_usage_activation_time'])

    def _periodic_connection_check(self, loop_time):
        """At a random interval, checks that activated connections have access to the
        Internet. If a connection does not have access to the Internet, the connection is
        deactivated. Netcheck will attempt to activate the freed network device later in the
        main program loop.

        loop_time: The datetime representing when the current program loop began.
        """
        for connection_id in self.connection_contexts:
            try:
                connection_context = self.connection_contexts[connection_id]
                if connection_context['activated'] and \
                        connection_context['confirmed_activated_time'] \
                        + connection_context['next_periodic_check'] < loop_time:

                    connection_is_activated = self._check_connection_and_check_dns(
                        loop_time, connection_context)

                    if connection_is_activated:
                        self.logger.debug(
                            '_periodic_connection_check: '
                            'Connection "%s" still has Internet access.', connection_id)
                    else:
                        self.logger.debug(
                            '_periodic_connection_check: '
                            'Connection "%s" no longer has Internet access.', connection_id)

            except Exception as exception:  #pylint: disable=broad-except
                self.logger.error(
                    'Unexpected error while checking if connection is active. %s: %s\n%s',
                    type(exception).__name__, str(exception), traceback.format_exc())

            connection_context['next_periodic_check'] = \
                self._calculate_periodic_check_delay()

    def _fix_connection_statuses_and_activate_unused_connections(self, loop_time):
        """Attempts to fix inconsistencies between connection contexts and the state that
        NetworkManager reports connections to be in, and attempts to activate unused network
        devices by attempting to activate each deactivated connection.

        loop_time: The datetime representing when the current program loop began.
        """
        current_connection_ids = []
        for connection_id in self.config['connection_ids']:
            try:
                connection_context = self.connection_contexts[connection_id]
                if not self.network_helper.connection_is_activated(connection_context['id']):
                    connection_context['activated'] = False

                if not connection_context['activated']:
                    self._activate_with_free_device_and_check_dns(
                        loop_time, connection_context)

                if connection_context['activated']:
                    current_connection_ids.append(connection_context['id'])

            except Exception as exception:  #pylint: disable=broad-except
                self.logger.error(
                    'Unexpected error while attepting to fix connection statuses or '
                    'activate free devices. %s: %s\n%s', type(exception).__name__,
                    str(exception), traceback.format_exc())

        return current_connection_ids

    def _steal_device_and_check_dns(self, loop_time, connection_context,
                                    excluded_connection_ids=None):
        """Activates a connection and verifies Internet accessibility, deactivating other
        connections if a required network device is in use.

        loop_time: The datetime representing when the current program loop began.
        connection_context: Contains stateful information for the connection being activated.
          Some connection state information is set in this method.
        excluded_connection_ids: A list of NetworkManager connection IDs that the specified
          connection cannot steal a network device from.
        Returns True if the connection has access to the Internet, False otherwise.
        """
        self.logger.trace(
            '_steal_device_and_check_dns: Attempting to activate and reach the Internet '
            'over connection "%s".', connection_context['id'])

        deactivated_connection_ids = set()
        activation_successful = self.network_helper.activate_connection_and_steal_device(
            connection_context['id'], deactivated_connection_ids, excluded_connection_ids)

        for deactivated_connection_id in deactivated_connection_ids:
            self.connection_contexts[deactivated_connection_id]['activated'] = False

        if not activation_successful:
            self.logger.debug('_steal_device_and_check_dns: Could not activate '
                              'connection "%s".', connection_context['id'])
            connection_context['activated'] = False
        else:
            self.logger.trace('_steal_device_and_check_dns: Connection "%s" activated.',
                              connection_context['id'])
            dns_successful = self._dns_works(loop_time, connection_context)
            if not dns_successful:
                self.logger.debug('_steal_device_and_check_dns: DNS on connection "%s" '
                                  'failed.', connection_context['id'])

                self.network_helper.deactivate_connection(connection_context['id'])

            else:
                self.logger.trace('_steal_device_and_check_dns: DNS on connection "%s" '
                                  'successful.', connection_context['id'])

        return connection_context['activated']

    def _activate_with_free_device_and_check_dns(self, loop_time, connection_context):
        """Activates a connection and verifies Internet accessibility, but only if other
        connections are not using a required network device.

        loop_time: The datetime representing when the current program loop began.
        connection_context: Contains stateful information for the connection being activated.
          Some connection state information is set in this method.
        Returns True if the connection has access to the Internet, False otherwise.
        """
        self.logger.trace(
            '_activate_with_free_device_and_check_dns: Attempting to activate and reach the '
            'Internet over connection "%s".', connection_context['id'])

        activation_successful = self.network_helper. \
            activate_connection_with_available_device(connection_context['id'])
        if not activation_successful:
            self.logger.debug('_activate_with_free_device_and_check_dns: Could not activate '
                              'connection "%s".', connection_context['id'])
            connection_context['activated'] = False
        else:
            self.logger.trace('_activate_with_free_device_and_check_dns: Connection "%s" '
                              'activated.', connection_context['id'])
            dns_successful = self._dns_works(loop_time, connection_context)
            if not dns_successful:
                self.logger.debug('_activate_with_free_device_and_check_dns: DNS on '
                                  'connection "%s" failed.', connection_context['id'])

                self.network_helper.deactivate_connection(connection_context['id'])

            else:
                self.logger.trace('_activate_with_free_device_and_check_dns: DNS on '
                                  'connection "%s" successful.', connection_context['id'])

        return connection_context['activated']

    def _check_connection_and_check_dns(self, loop_time, connection_context):
        """Checks if a connection is activated and if so, checks DNS availability.

        loop_time: The datetime representing when the current program loop began.
        connection_context: Contains stateful information for the connection being checked.
          Some connection state information is set in this method.
        Returns True on successful DNS lookup, False otherwise.
        """
        self.logger.trace('_check_connection_and_check_dns: Attempting to reach the '
                          'Internet over connection "%s".', connection_context['id'])

        overall_success = False
        connection_active = self.network_helper.connection_is_activated(
            connection_context['id'])
        if not connection_active:
            self.logger.debug(
                '_check_connection_and_check_dns: Connection "%s" not activated.',
                connection_context['id'])
            connection_context['activated'] = False
        else:
            self.logger.trace('_check_connection_and_check_dns: Connection "%s" activated.',
                              connection_context['id'])
            dns_successful = self._dns_works(loop_time, connection_context)
            if not dns_successful:
                self.logger.debug(
                    '_check_connection_and_check_dns: DNS on connection "%s" failed.',
                    connection_context['id'])

                self.network_helper.deactivate_connection(connection_context['id'])

            else:
                self.logger.trace(
                    '_check_connection_and_check_dns: DNS on connection "%s" successful.',
                    connection_context['id'])
                overall_success = True

        return overall_success

    def _dns_works(self, loop_time, connection_context):
        """Queries up to two random nameservers for two random domains over the given
        connection. The possible nameservers and domains are defined in the program
        configuration file.

        loop_time: The datetime representing when the current program loop began.
        connection_context: Contains stateful information for the connection being checked.
          Some connection state information is set in this method.
        Returns True if either DNS query succeeds. False otherwise.
        """

        # Picks two exclusive-random choices from the nameserver and domain name lists.
        nameservers = random.sample(self.config['nameservers'], 2)
        query_names = random.sample(self.config['dns_queries'], 2)

        dns_works = False

        self.logger.trace(
            '_dns_works: Attempting first DNS query for %s on connection "%s" '
            'using name server %s.', query_names[0], connection_context['id'],
            nameservers[0])
        if self._dns_query(loop_time, connection_context, nameservers[0], query_names[0]):
            dns_works = True
            self.logger.trace('_dns_works: First DNS query on connection "%s" successful.',
                              connection_context['id'])
        else:
            self.logger.debug(
                '_dns_works: First DNS query for %s failed on connection "%s" using '
                'name server %s. Attempting second query.', query_names[0],
                connection_context['id'], nameservers[0])
            self.logger.trace(
                '_dns_works: Attempting second DNS query for %s on connection "%s" '
                'using name server %s.', query_names[1], connection_context['id'],
                nameservers[1])
            if self._dns_query(
                    loop_time, connection_context, nameservers[1], query_names[1]):
                dns_works = True
                self.logger.trace(
                    '_dns_works: Second DNS query on connection "%s" successful.',
                    connection_context['id'])
            else:
                connection_context['activated'] = False
                self.logger.warning(
                    'Two DNS lookups failed for %s and %s using nameservers %s and %s '
                    '(respectively) with connection "%s". Deactivating connection.',
                    query_names[0], query_names[1], nameservers[0], nameservers[1],
                    connection_context['id'])

        return dns_works

    # TODO: Use something more secure than unauthenticated DNS requests. (issue 5)
    def _dns_query(self, loop_time, connection_context, nameserver, query_name):
        """Attempts a DNS query for query_name on 'nameserver' via a connection.

        loop_time: The datetime representing when the current program loop began.
        connection_context: Contains stateful information for the connection being checked.
          Some connection state information is set in this method.
        nameserver: The IP address of the name server to use in the query.
        query_name: The DNS name to query.
        Returns True if successful, False otherwise.
        """
        self.logger.trace('_dns_query: Querying %s for %s on connection "%s".', nameserver,
                          query_name, connection_context['id'])
        success = False
        interface = self.network_helper.get_connection_interface(connection_context['id'])

        if not interface:
            self.logger.error('Connection "%s" has no interface and does not appear to be '
                              'activated.', connection_context['id'])
        else:
            # This is terrible if we ever want to go multithreaded, but this is the best work
            #   around I could find. It will work for now.
            dns.query.socket_factory = self._create_socket_factory(interface)
            self.resolver.nameservers = [nameserver]
            try:
                self.resolver.query(query_name)
                success = True

            except dns.resolver.Timeout as exception:
                # Connection is probably deactivated. This message occurs often so it is
                #   debug.
                self.logger.debug(
                    '_dns_query: DNS query for %s from nameserver %s on connection "%s" '
                    'timed out. %s: %s', query_name, nameserver, connection_context['id'],
                    type(exception).__name__, str(exception))

            except dns.resolver.NXDOMAIN as exception:
                # Could be either a config error or malicious DNS
                self.logger.error(
                    'DNS query for %s from nameserver %s on connection "%s" was successful, '
                    'but the provided domain was not found. %s: %s', query_name,
                    nameserver, connection_context['id'], type(exception).__name__,
                    str(exception))

            except dns.resolver.NoNameservers as exception:
                # Probably a config error, but chosen DNS could be down or blocked.
                self.logger.error(
                    'Could not access nameserver %s on connection "%s". %s: %s',
                    nameserver, connection_context['id'], type(exception).__name__,
                    str(exception))

            except Exception as exception:  #pylint: disable=broad-except
                # Something happened that is outside of Netcheck's scope.
                self.logger.error(
                    'Unexpected error querying %s from nameserver %s on connection "%s". '
                    '%s: %s\n%s', query_name, nameserver, connection_context['id'],
                    type(exception).__name__, str(exception), traceback.format_exc())

            if success:
                connection_context['activated'] = True
                connection_context['confirmed_activated_time'] = loop_time
                connection_context['failed_required_usage_activation_time'] = None

        return success

    #pylint: disable=no-self-use
    def _create_socket_factory(self, interface):
        """Creates a function that creates a socket that is bound to a network interface.

        interface: The name of the network interface the socket should be bound to.
        Returns a function that creates the socket.
        """
        def create_device_bound_socket(address_family, socket_type, protocol_number):
            """Creates a socket that is bound to a network interface. See the Python socket
            documentation for a description of the parameters and the return value.
            """
            device_bound_socket = socket.socket(address_family, socket_type, protocol_number)
            device_bound_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                                           interface.encode('utf-8'))
            return device_bound_socket

        return create_device_bound_socket

    def _calculate_periodic_check_delay(self):
        """Returns a datetime delta representing the next delay that should occur between a
        connection's Internet access checks."""
        return datetime.timedelta(seconds=random.uniform(
            0, self.config['connection_periodic_check_time']))

    def _calculate_available_connections_check_time(self, loop_time):
        """Returns the next time the program should refresh the list of available
        connections. Essentially, this returns the time of the next WiFi scan.

        loop_time: The datetime representing when the current program loop began.
        Returns the datetime that the list of available connections should be refreshed.
        """
        return loop_time + datetime.timedelta(
            seconds=self.config['available_connections_check_delay'])

    def _log_connections(self, loop_time, prior_connection_ids, current_connection_ids):
        """Logs changes to the activated connections and periodically logs the currently
        activated connections.

        loop_time: The datetime representing when the current program loop began.
        prior_connection_ids: The NetworkManager display names of the activated connections
          at the end of the prior main program loop.
        current_connection_ids: The NetworkManager display names of the activated
          connections at the end of the current main program loop.
        """
        prior_connection_set = set(prior_connection_ids)
        current_connection_set = set(current_connection_ids)

        if loop_time > self.next_log_time:
            current_connections_string = "Current connections: None"
            if current_connection_set:
                current_connections_string = 'Current connections: "%s"' \
                    % '", "'.join(current_connection_set)
            self.logger.info('Still running. %s', current_connections_string)
            self.next_log_time = self._calculate_next_log_time(loop_time)

        if prior_connection_set != current_connection_set:

            if not current_connection_set:
                self.logger.error('Connection change: No connections are active!')
            else:
                connections_deactivated = prior_connection_set - current_connection_set
                connections_activated = current_connection_set - prior_connection_set

                connections_activated_string = ''
                if connections_activated:
                    connections_activated_string = '\n  Newly activated connections: "%s"' \
                        % '", "'.join(connections_activated)

                if connections_deactivated:
                    if connections_deactivated:
                        connections_deactivated_string = \
                            '\n  Newly deactivated connections: "%s"' \
                            % '", "'.join(connections_deactivated)

                    self.logger.warning('Connection change: %s%s',
                                        connections_activated_string,
                                        connections_deactivated_string)
                else:
                    self.logger.info('Connection change: %s', connections_activated_string)

    def _calculate_next_log_time(self, loop_time):
        """Returns the time that the list of activated connections should be logged.

        loop_time: The datetime representing when the current program loop began.
        Returns the datetime that the logging should occur.
        """
        return loop_time + datetime.timedelta(seconds=self.config['periodic_status_delay'])

    def _check_for_gateway_change(self):
        """Checks the current state of the default gateway and issues a broadcast if it is
        different from the prior state.
        """

        default_gateway_state = self._get_default_gateway_state()

        if default_gateway_state \
                and default_gateway_state != self.prior_default_gateway_state:

            self.logger.info(
                'The default gateway has changed to %s via %s on interface %s.',
                default_gateway_state['address'],
                default_gateway_state['connection_id'],
                default_gateway_state['interface'])

            self.broadcaster.issue()

        self.prior_default_gateway_state = default_gateway_state

    # TODO: This should probalby consider IPv4 and IPv6 routes separately. (issue 28)
    def _get_default_gateway_state(self):
        """Retrieves information about the current primary default gateway.

        Returns a dictionary containing the gateway IP address, interface name, and
          associated connection ID. If there is no primary default gateway, None is returned.
        """
        default_gateway_state = None

        default_routes = self.ip_route.get_default_routes()
        if default_routes:
            default_gateway_state = {
                'address': None,
                'interface': None,
                'connection_id': None}
            route_attributes = dict(default_routes[0]['attrs'])
            default_gateway_state['address'] = route_attributes['RTA_GATEWAY']
            output_interface_id = route_attributes['RTA_OIF']
            interface = next((dict(interface) for interface in self.ip_route.get_links(
                ) if dict(interface)['index'] == output_interface_id), None)
            interface_attributes = dict(interface['attrs'])
            default_gateway_state['interface'] = interface_attributes['IFLA_IFNAME']

            default_gateway_state['connection_id'] = \
                self.network_helper.get_connection_for_interface(
                    default_gateway_state['interface'])
        else:
            self.logger.trace('No default routes are defined.')

        return default_gateway_state
