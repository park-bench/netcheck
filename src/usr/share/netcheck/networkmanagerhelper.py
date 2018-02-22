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

"""NetworkManagerHelper provides a readable layer of abstraction for the
python-networkmanager class.
"""

__all__ = ['NetworkManagerHelper']
__author__ = 'Andrew Klapp and Joel Allen Luellwitz'
__version__ = '0.8'

import datetime
import logging
import time
import NetworkManager

NETWORKMANAGER_ACTIVATION_CHECK_DELAY = 0.1

NM_CONNECTION_ACTIVATING = 0
NM_CONNECTION_ACTIVE = 1
NM_CONNECTION_DISCONNECTED = 2

class NetworkManagerHelper:
    """NetworkManagerHelper abstracts away some of the messy details of the NetworkManager
    Dbus API.
    """

    def __init__(self, network_activation_timeout):

        self.network_activation_timeout = network_activation_timeout
        self.logger = logging.getLogger()

        self.network_id_table = self._build_network_id_table()
        self.device_interface_table = self._build_device_interface_table()

    def activate_network(self, network_id):
        """Tells NetworkManager to activate a network with the supplied network_id.
        Returns True if there are no errors, False otherwise.
        """
        success = False
        connection = self.network_id_table[network_id]
        network_device = self._get_device_for_connection(connection)

        networkmanager_output = NetworkManager.NetworkManager.ActivateConnection(connection, network_device, '/')
        self._run_proxy_call(networkmanager_output)
        success = self._wait_for_connection(connection)

        return success

    def get_network_ip(self, network_id):
        """Attempts to retrieve the ip address associated with the given network id. If it
        is unable to, it returns None."""
        # I decided not to throw an exception here because the intended caller would end up
        #   simply using it for flow control.
        ip_address = None

        connection = self.network_id_table[network_id]

        if self._wait_for_connection(connection):
            device = self._get_device_for_connection(connection)
            ip_address = device.Ip4Config.AddressData[0]['address']
        else:
            self.logger.warning('Attempted to get IP address for network that is not connected.')

        return ip_address

    def network_is_ready(self, network_id):
        """Check whether the network with the given network id is ready."""
        connection = self.network_id_table[network_id]
        return self._wait_for_connection(connection)

    def _build_network_id_table(self):
        """Assemble a helpful dictionary of network objects, indexed by the connection's
        id in NetworkManager.
        """
        network_id_table = {}

        all_connections = NetworkManager.Settings.ListConnections()
        self._run_proxy_call(all_connections)

        for connection in all_connections:
            connection_id = connection.GetSettings()['connection']['id']
            network_id_table[connection_id] = connection

        return network_id_table

    def _build_device_interface_table(self):
        """Assemble a helpful dictionary of device objects, indexed by the device's interface
        name.
        """
        device_interface_table = {}

        device_list = NetworkManager.NetworkManager.GetDevices()
        self._run_proxy_call(device_list)

        for device in device_list:
            interface = device.Interface
            device_interface_table[interface] = device

        return device_interface_table

    def _get_active_connection(self, network_id):
        """Returns the active connection object associated with the given network id."""

        # The active connection objects returned by NetworkManager are very short-lived and
        #   not directly accessible from the connection object.

        active_connection_list = NetworkManager.NetworkManager.ActiveConnections
        self._run_proxy_call(active_connection_list)

        for listed_active_connection in active_connection:
            if listed_active_connection.Id == network_id:
                # TODO: Change to trace later, when it won't break testing code.
                self.logger.debug('Found active connection.')
                return listed_active_connection

        return None

    def _get_connection_state(self, network_id):
        """Returns the state of the connection with the given network id."""
        state = NM_CONNECTION_DISCONNECTED

        active_connection = self._get_active_connection(network_id)

        if active_connection is None:
            self.logger.warning('Connection disconnected.')

        else:
            self.logger.debug(hasattr(active_connection, 'State'))
            if hasattr(active_connection, 'State'):
                if active_connection.State is NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATING:
                    state = NM_CONNECTION_CONNECTING
                if active_connection.State is NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
                    state = NM_CONNECTION_ACTIVE

        return state

    def _get_device_for_connection(self, connection):
        """Get the device object a connection object needs to connect with."""

        connection_interface = connection.GetSettings()['connection']['interface-name']
        network_device = self.device_interface_table[connection_interface]

        return network_device

    def _wait_for_connection(self, connection):
        """Wait timeout number of seconds for an active connection to be ready.
        return True if it connects within timeout, False otherwise.
        """
        success = False
        give_up = False
        time_to_give_up = time.time() + self.network_activation_timeout
        network_id = connection.GetSettings()['connection']['id']

        self.logger.debug('Waiting for connection %s...' % network_id)
        while (success is False and give_up is False):
            time.sleep(NETWORKMANAGER_ACTIVATION_CHECK_DELAY)

            connection_state = self._get_connection_state(network_id)

            if connection_state is NM_CONNECTION_ACTIVE:
                self.logger.debug('Connection successful.')
                success = True

            elif connection_state is NM_CONNECTION_DISCONNECTED:
                self.logger.warning('Connection disconnected, giving up.')
                give_up = True

            elif time.time() > time_to_give_up:
                self.logger.warning('Connection timed out, giving up.')
                give_up = True

        return success

    def _run_proxy_call(self, proxy_call):
        """If proxy_call is callable, call it."""
        # Sometimes, instead of raising exceptions or returning error states, NetworkManager
        #   will sometimes return a function that makes a dbus call it assumes will fail. We
        #   still want this error information, so here, we call it if we can.
        if callable(proxy_call):
            proxy_call()
