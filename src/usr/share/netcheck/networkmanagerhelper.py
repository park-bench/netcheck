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

import logging
import time
import NetworkManager

NETWORKMANAGER_ACTIVATION_CHECK_DELAY = 0.1

NM_CONNECTION_ACTIVATING = 0
NM_CONNECTION_ACTIVATED = 1
NM_CONNECTION_DISCONNECTED = 2

class DeviceNotFoundException(Exception):
    """Raised when an interface name passed to NetworkManagerHelper is not found."""

class NetworkManagerHelper:
    """NetworkManagerHelper abstracts away some of the messy details of the NetworkManager
    D-Bus API.
    """

    def __init__(self, config):
        """Initializes the module by choosing devices and assembling a table of connection
        IDs.

        config: The configuration dictionary built in netcheck-daemon.
        """

        self.logger = logging.getLogger(__name__)
        self.network_activation_timeout = config['network_activation_timeout']
        self.wired_network_name = config['wired_network_name']

        self.connection_id_to_connection_dict = self._build_connection_id_table()
        self._get_device_objects(config['wired_interface_name'],
                                 config['wifi_interface_name'])

    def activate_network(self, connection_id):
        """Tells NetworkManager to activate a network with the supplied connection_id.
        Returns True if there are no errors, False otherwise.

        connection_id: The displayed name of the connection in NetworkManager.
        """
        success = False
        connection = self.connection_id_to_connection_dict[connection_id]
        network_device = self._get_device_for_connection(connection)

        networkmanager_output = NetworkManager.NetworkManager.ActivateConnection(
            connection, network_device, '/')
        self._run_proxy_call(networkmanager_output)
        success = self._wait_for_connection(connection)

        return success

    def get_connection_ip(self, connection_id):
        """Attempts to retrieve the IP address associated with the given network id. If the
        IP address is unable to be retrieved, None is returned.

        connection_id: The displayed name of the connection in NetworkManager.
        """
        # I decided not to throw an exception here because the intended caller would end up
        #   simply using it for flow control.
        ip_address = None

        connection = self.connection_id_to_connection_dict[connection_id]

        if self.network_is_ready(connection):
            device = self._get_device_for_connection(connection)
            ip_address = device.Ip4Config.AddressData[0]['address']
        else:
            self.logger.warning(
                'Attempted to get IP address for network %s, which is not connected.',
                connection_id)

        return ip_address

    def network_is_ready(self, connection_id):
        """Check whether the network with the given network id is ready.

        connection_id: The displayed name of the connection in NetworkManager.
        """

        connection_is_ready = False

        connection = self.connection_id_to_connection_dict[connection_id]
        connection_state = self._get_connection_state(connection)

        if connection_state is NM_CONNECTION_ACTIVATED:
            connection_is_ready = True

        return connection_is_ready

    def _build_connection_id_table(self):
        """Assemble a helpful dictionary of network objects, indexed by the connection's
        id in NetworkManager.
        """
        connection_id_to_connection_dict = {}

        all_connections = NetworkManager.Settings.ListConnections()
        self._run_proxy_call(all_connections)

        for connection in all_connections:
            connection_id = connection.GetSettings()['connection']['id']
            connection_id_to_connection_dict[connection_id] = connection

        return connection_id_to_connection_dict

    def _get_active_connection(self, connection_id):
        """Returns the active connection object associated with the given network id.

        connection_id: The displayed name of the connection in NetworkManager.
        """

        active_connections = NetworkManager.NetworkManager.ActiveConnections
        self._run_proxy_call(active_connections)

        for active_connection in active_connections:
            if active_connection.Id == connection_id:
                self.logger.trace('Found active connection.')
                return active_connection

        return None

    def _get_connection_state(self, connection_id):
        """Returns the state of the connection with the given network id.

        connection_id: The displayed name of the connection in NetworkManager.
        """
        state = NM_CONNECTION_DISCONNECTED

        active_connection = self._get_active_connection(connection_id)

        if active_connection is None:
            self.logger.warning('Connection %s disconnected.', connection_id)

        else:
            if hasattr(active_connection, 'State'):
                if active_connection.State \
                        is NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATING:
                    state = NM_CONNECTION_ACTIVATING
                if active_connection.State \
                        is NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
                    state = NM_CONNECTION_ACTIVATED

        return state

    def _create_device_objects(self, wired_interface_name, wifi_interface_name):
        """Store references to the device objects that are used frequently.

        wired_interface_name: The name of the wired network interface, e.g. eth0, enp0s1.
        wifi_interface_name: The name of the wifi network interface, e.g. wlan0, wlp0s1.
        """

        for device in NetworkManager.NetworkManager.GetDevices():
            if device.Interface == wired_interface_name:
                self.wired_device = device

            if device.Interface == wifi_interface_name:
                self.wireless_device = device

        if self.wired_device is None:
            raise DeviceNotFoundException('Configured wired device %s was not found.' %
                wired_interface_name)

        if self.wireless_device is None:
            raise DeviceNotFoundException('Configured wireless device %s was not found.' %
                wifi_interface_name)

    def _get_device_for_connection(self, connection):
        """Returns the device object a connection object needs to connect with.

        connection: The NetworkManager.Connection object for which to find the device.
        """

        network_device = self.wireless_device

        connection_id = connection.GetSettings()['connection']['id']
        if connection_id == self.wired_network_name:
            network_device = self.wired_device

        return network_device

    def _wait_for_connection(self, connection):
        """Wait for the configured number of seconds for an active connection to be ready.
        return True if it connects in that time, False otherwise.

        connection: The NetworkManager.Connection object to watch for connectivity.
        """
        success = False
        give_up = False
        time_to_give_up = time.time() + self.network_activation_timeout
        connection_id = connection.GetSettings()['connection']['id']

        self.logger.debug('Waiting for connection %s...', connection_id)
        while (success is False and give_up is False):
            time.sleep(NETWORKMANAGER_ACTIVATION_CHECK_DELAY)

            connection_state = self._get_connection_state(connection_id)

            if connection_state is NM_CONNECTION_ACTIVATED:
                self.logger.debug('Connection %s successful.', connection_id)
                success = True

            elif connection_state is NM_CONNECTION_DISCONNECTED:
                self.logger.warning('Connection %s disconnected. Giving up.', connection_id)
                give_up = True

            elif time.time() > time_to_give_up:
                self.logger.warning('Connection %s timed out. Giving up.', connection_id)
                give_up = True

        return success

    def _run_proxy_call(self, proxy_call):
        """If proxy_call is callable, call it. This typically means that there was a
        critical D-Bus error and an exception will most likely be raised.

        proxy_call: The output of a NetworkManager D-Bus call.
        """
        # Sometimes, instead of raising exceptions or returning error states, NetworkManager
        #   will return a function that makes a D-Bus call it assumes will fail. We still
        #   want this error information, so here, we call it if we can. This method will
        #   probably raise an exception if it is called.
        if callable(proxy_call):
            proxy_call()
