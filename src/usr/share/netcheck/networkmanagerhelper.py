"""NetworkManagerHelper provides a readable layer of abstraction for the
python-networkmanager class.
"""

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

    # TODO: We don't need a whole config dict, just the one timeout value.
    def __init__(self, config):

        self.config = config
        self.logger = logging.getLogger()

        # TODO: Remove these and read these values from the config file.
        #self.config['network_activation_timeout'] = 15 # in seconds

        self.network_id_table = self._build_network_id_table()
        self.device_interface_table = self._build_device_interface_table()

    def activate_network(self, network_id):
        """Tells NetworkManager to activate a network with the supplied network_id.
        Returns True if there are no errors, False otherwise.
        """
        success = False
        connection = self.network_id_table[network_id]
        network_device = self._get_device_for_connection(connection)

        # TODO: Make sure this is actually how NetworkManager handles errors. It will
        #   return a proxy_call object in several cases.
        NetworkManager.NetworkManager.ActivateConnection(connection, network_device, '/')
        success = self._wait_for_connection(connection)

        return success

    def get_network_ip(self, network_id):
        """Attempts to retrieve the ip address associated with the given network id. If it
        is unable to, it returns None."""
        # I decided not to throw an exception here because the intended caller would end up
        #   simply using it for flow control.
        pass

    def network_is_ready(self, network_id):
        """Check whether the network with the given network id is ready."""
        connection = self.network_id_table[network_id]
        return self._wait_for_connection(connection)

    def _build_network_id_table(self):
        """Assemble a helpful dictionary of network objects, indexed by the connection's
        id in NetworkManager.
        """
        network_id_table = {}
        for connection in NetworkManager.Settings.ListConnections():
            connection_id = connection.GetSettings()['connection']['id']
            network_id_table[connection_id] = connection

        return network_id_table

    def _build_device_interface_table(self):
        """Assemble a helpful dictionary of device objects, indexed by the device's interface
        name.
        """
        device_interface_table = {}

        for device in NetworkManager.NetworkManager.GetDevices():
            interface = device.Interface
            device_interface_table[interface] = device

        return device_interface_table

    def _get_active_connection(self, network_id):
        """Returns the active connection object associated with the given network id."""

        # The active connection objects returned by NetworkManager are very short-lived and
        #   not directly accessible from the connection object.
        for listed_active_connection in NetworkManager.NetworkManager.ActiveConnections:
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
            self.logger.warn('Connection disconnected.')

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
        time_to_give_up = time.time() + self.config['network_activation_timeout']
        network_id = connection.GetSettings()['connection']['id']

        self.logger.debug('Waiting for connection %s...' % network_id)
        while (success is False and give_up is False):
            time.sleep(NETWORKMANAGER_ACTIVATION_CHECK_DELAY)

            connection_state = self._get_connection_state(network_id)

            if connection_state is NM_CONNECTION_ACTIVE:
                self.logger.debug('Connection successful.')
                success = True

            elif connection_state is NM_CONNECTION_DISCONNECTED:
                self.logger.warn('Connection disconnected, giving up.')
                give_up = True

            elif time.time() > time_to_give_up:
                self.logger.warn('Connection timed out, giving up.')
                give_up = True

        return success
