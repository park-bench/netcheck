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

__all__ = ['DeviceNotFoundException', 'UnknownConnectionIdException', 'NetworkManagerHelper']
__author__ = 'Andrew Klapp and Joel Allen Luellwitz'
__version__ = '0.8'

import logging
import time
import netaddr
import NetworkManager

NETWORKMANAGER_ACTIVATION_CHECK_DELAY = 0.1

NM_CONNECTION_ACTIVATING = "NM_CONNECTION_ACTIVATED"
NM_CONNECTION_ACTIVATED = "NM_CONNECTION_ACTIVATED"
NM_CONNECTION_DISCONNECTED = "NM_CONNECTION_DISCONNECTED"

class DeviceNotFoundException(Exception):
    """Raised when an interface name passed to NetworkManagerHelper is not found."""

# TODO: Make sure this is still used somewhere.
class UnknownConnectionIdException(Exception):
    """Raised when a connection ID is requested, but it is not known."""

class NetworkManagerHelper(object):
    """NetworkManagerHelper abstracts away some of the messy details of the NetworkManager
    D-Bus API.
    """

    def __init__(self, config):
        """Initializes the module by storing references to device objects and assembling a
        dict of connection IDs.

        config: The configuration dictionary constructed during program initialization.
        """

        self.logger = logging.getLogger(__name__)
        self.connection_activation_timeout = config['connection_activation_timeout']
        self.wired_connection_id = config['wired_connection_id']
        self.wireless_connection_ids = config['wireless_connection_ids']

        self.connection_id_to_connection_dict = self._build_connection_id_dict()

    def activate_connections_quickly(self, connection_ids):
        """ TODO: """

    def activate_connection_and_steal_device(self, connection_id,
            excluded_connection_ids = None):
        """ TODO: 
        Returns a tuple. The first value is either true or false indicating whether the
          connection was successful. The second value is a String indicating which connection
          was stolen. None is returned for the second value if no connection was stolen.
        """

    def activate_connection_with_available_device(self, connection_id):
        """Tells NetworkManager to activate a connection with the supplied connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns True if the connection is activated, False otherwise.
        """
        success = False

        # Get a list of all devices this connection can be applied to.
        available_devices = []
        # TODO: Do we need to do the proxy call after calling GetDevices?
        for device in NetworkManager.NetworkManager.GetDevices():
            # See if the connection is already activated.
            applied_connection = device.GetAppliedConnection()
            if applied_connection is not None \
                    and applied_connection.id == connection_id:
                # The connection is already activated.
                # I do hate multiple returns but this does seem the most Pythonic.
                return True
            else:
                for available_connection in device.AvailableConnections:
                    # TODO: Verify the applied connection is in the available connection
                    #   list.
                    if available_connection.id == connection_id:
                        available_devices.append(device)

        # Try to activate the connection with a random available device.
        success = False
        devices_left = len(devices)
        while success is False and not devices_left:
            random_index = random_int(0, devices_left)
            available_device = availale_devices[random_index]
            available_devices[random_index] = available_devices[devices_left - 1]
            devices_left -= 1

            try:
                networkmanager_output = NetworkManager.NetworkManager.ActivateConnection(
                    connection, network_device, '/')
                self._run_proxy_call(networkmanager_output)
                success = self._wait_for_connection(connection)

            except Exception as exception:
                self.logger.error(
                    'D-Bus call failed while activating connection "%s". %s: %s',
                    connection_id, type(exception).__name__, str(exception))

        return success

    def get_connection_ip(self, connection_id):
        """Attempts to retrieve the IP address associated with the given connection's
        gateway.  If the IP address is unable to be retrieved, None is returned.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns the IP address as a string if it can be retrieved.  Returns None otherwise.
        """

        # TODO #19: Add IPv6 support.
        ip_address = None

        if not self.connection_is_activated(connection_id):
            self.logger.warning(
                'Attempted to get IP address for connection %s, which is not connected.',
                connection_id)

        else:
            device = self._get_device_for_connection(connection_id)
            gateway_address = netaddr.IPNetwork(device.Ip4Config.Gateway)

            for address_data in device.Ip4Config.AddressData:
                address_cidr = '%s/%s' % (address_data['address'], address_data['prefix'])
                address_network = netaddr.IPNetwork(address_cidr)

                if gateway_address in address_network:
                    ip_address = address_data['address']

            if ip_address is None:
                self.logger.warning(
                    'No IP addresses for connection %s associated with gateway %s.',
                    connection_id, gateway_address)

        return ip_address

    def connection_is_activated(self, connection_id):
        """Check whether the connection with the given connection ID is activated.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns True if the connection is activated, False otherwise.
        """

        connection_is_activated = False

        connection_state = self._get_connection_state(connection_id)

        if connection_state is NM_CONNECTION_ACTIVATED:
            connection_is_activated = True

        return connection_is_activated

    def get_available_connections(self):
        """Returns a list of available connections. An available connection is defined as an
        enabled connection that is not activated that can be activated on a device where the
        device does not have an active connection.

        Returns an array of NetworkManager connection IDs.
        """
        connection_ids = Set()
        for device in NetworkManager.NetworkManager.GetDevices():
            for available_connection in device.AvailableConnections:
                available_connection_id = available_connection.id
                applied_connection = device.GetAppliedConnection
                # TODO: Verify the applied connection is in the available connection list.
                if applied_connection is not None \
                        and applied_connection.id != available_connection_id:
                    connection_ids.append(availale_connection_id)

        return connection_ids.to_array()

    def _build_connection_id_dict(self):
        """Assemble a dictionary of connection objects, indexed by the connection's ID in
        NetworkManager.

        Returns a dict, with keys being connection IDs and values being
          NetworkManager.Connection objects.
        """
        connection_id_to_connection_dict = {}

        all_connections = NetworkManager.Settings.ListConnections()
        self._run_proxy_call(all_connections)

        for connection in all_connections:
            connection_id = connection.GetSettings()['connection']['id']
            connection_id_to_connection_dict[connection_id] = connection

        return connection_id_to_connection_dict

    def _get_device_for_connection(self, connection_id):
        """Finds the device object associated with the given connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns a NetworkManager device object.  If no matching device is found, an exception
          is raised.
        """
        connection = self.connection_id_to_connection_dict[connection_id]

        connection_settings = connection.GetSettings()
        connection_interface = connection_settings['connection'].get('interface-name', None)
        connection_type = connection_settings['connection']['type']
        connection_mac_address = connection_settings[connection_type].get(
            'mac-address', None)

        matching_device = None

        for device in NetworkManager.NetworkManager.GetDevices():
            device_interface = device.Interface
            specific_device = device.SpecificDevice()
            device_mac_address = None
            if hasattr(specific_device, 'HwAddress'):
                device_mac_address = specific_device.HwAddress

            if 

        return matching_device

    def _wait_for_connection(self, connection):
        """Wait for the configured number of seconds for the specified active connection to
        finish activation.

        connection: The NetworkManager.Connection object to watch for connectivity.
        Return True if the connection is activated, False otherwise.
        """
        success = False
        give_up = False
        connection_id = connection.GetSettings()['connection']['id']
        time_to_give_up = time.time() + self.connection_activation_timeout

        self.logger.debug('Waiting for connection %s...', connection_id)
        while not success and not give_up:

            connection_state = self._get_connection_state(connection_id)

            if connection_state is NM_CONNECTION_ACTIVATED:
                self.logger.debug('Connection %s successful.', connection_id)
                success = True

            elif connection_state is NM_CONNECTION_DISCONNECTED:
                self.logger.warning('Connection %s disconnected. Trying next connection.',
                                    connection_id)
                give_up = True

            elif time.time() > time_to_give_up:
                self.logger.warning('Connection %s timed out. Trying next connection.',
                                    connection_id)
                give_up = True

            else:
                time.sleep(NETWORKMANAGER_ACTIVATION_CHECK_DELAY)

        return success

    def _get_connection_state(self, connection_id):
        """Reads the current state of the connection identified by the connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns a constant representing the current connection state.  Possible values are:
          NM_CONNECTION_ACTIVATING, NM_CONNECTION_ACTIVATED, and NM_CONNECTION_DISCONNECTED
        """
        state = NM_CONNECTION_DISCONNECTED

        active_connection = self._get_active_connection(connection_id)

        if active_connection is None:
            self.logger.warning('Connection %s is not activated.', connection_id)

        else:
            if hasattr(active_connection, 'State'):
                if active_connection.State \
                        is NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATING:
                    state = NM_CONNECTION_ACTIVATING
                if active_connection.State \
                        is NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
                    state = NM_CONNECTION_ACTIVATED

            else:
                self.logger.error('Connection %s is no longer activated.',
                                  connection_id)

        return state

    def _get_active_connection(self, connection_id):
        """Finds the active connection object for a given connection ID.

        connection_id: The displayed name of the connection in NetworkManager.
        Returns a NetworkManager.ActiveConnection object.  If no matching object exists, None
          is returned.
        """
        matched_active_connection = None

        active_connections = NetworkManager.NetworkManager.ActiveConnections
        self._run_proxy_call(active_connections)

        for active_connection in active_connections:
            if active_connection.Id == connection_id:
                self.logger.trace('Found that connection %s is active.',
                                  connection_id)
                matched_active_connection = active_connection

        return matched_active_connection

    # TODO: Make sure this is really needed.
    def _run_proxy_call(self, proxy_call):
        """If proxy_call is callable, call it.

        Sometimes if NetworkManager enounters a critical error, it will return a callable
        that will raise an exception if called.  This error information is valuable, so
        raising this exception allows this program to get access to the error details.

        proxy_call: The output of a NetworkManager D-Bus call.
        """
        if callable(proxy_call):
            proxy_call()
