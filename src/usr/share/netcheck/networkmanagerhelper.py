"""NetworkManagerHelper provides a readable layer of abstraction for the
python-networkmanager class.
"""

import datetime
import logging
import time
import NetworkManager

NETWORKMANAGER_ACTIVATION_CHECK_DELAY = 0.1

class DeviceNotFoundException(Exception):
    """This exception is raised when a configured network device is not found."""

class NetworkTypeNotHandledException(Exception):
    """This exception is raised when a configured network is a type that this library does
    not handle.
    """

class NetworkManagerHelper:
    """NetworkManagerHelper abstracts away some of the messy details of the NetworkManager
    Dbus API.
    """

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
        #success = self._wait_for_connection(connection)

        return success

    def get_network_ip(self, network_id):
        pass

    def network_is_ready(self, network_id):
        """Check whether the network with the given network id is ready."""
        pass

    def _build_network_id_table(self):
        """Assemble a helpful dictionary of network objects, indexed by the connection's
        id in NetworkManager
        """
        network_id_table = {}
        for connection in NetworkManager.Settings.ListConnections():
            connection_id = connection.GetSettings()['connection']['id']
            network_id_table[connection_id] = connection

        return network_id_table

    def _build_device_interface_table(self):
        """Assemble a helpful dictionary of device objects, indexed by the device's hardware
        address.
        """
        device_interface_table = {}

        for device in NetworkManager.NetworkManager.GetDevices():
            interface = device.Interface
            device_interface_table[interface] = device

        return device_interface_table

    def _get_device_for_connection(self, connection):
        """Get the device object a connection object needs to connect with."""

        connection_interface = connection.GetSettings()['connection']['interface-name']
        network_device = self.device_interface_table[connection_interface]

        return network_device

    def _wait_for_connection(self, active_connection):
        """Wait timeout number of seconds for an active connection to be ready.
        return True if it connects within timeout, False otherwise.
        """
        success = False
        give_up = False

        time_to_give_up = time.time() + self.config['network_activation_timeout']

        self.logger.debug('Waiting for connection %s...' % active_connection.GetSettings()['connection']['id'])
        while (success is False and give_up is False):
            self.logger.debug(active_connection.State)
            if (active_connection.State == 3 or active_connection.State == 4 or
                time.time() > time_to_give_up):
                give_up = True
            time.sleep(NETWORKMANAGER_ACTIVATION_CHECK_DELAY)

        return success
