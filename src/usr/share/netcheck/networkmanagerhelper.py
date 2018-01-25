"""NetworkManagerHelper provides a readable layer of abstraction for the
python-networkmanager class.
"""

import datetime
import logging
import time
import NetworkManager

# TODO: Move these to the configuration file.
WIRED_DEVICE = 'ens3'
WIRELESS_DEVICE = 'ens8'

# Network type strings according to python-networkmanager
WIRED_NETWORK_TYPE = '802-3-ethernet'
WIRELESS_NETWORK_TYPE = '802-11-wireless'

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
        self.config['wired_interface_name'] = WIRED_DEVICE
        self.config['wireless_interface_name'] = WIRELESS_DEVICE
        self.config['network_activation_timeout'] = 15 # in seconds

        self.network_id_table = self._build_network_id_table()

        self.wired_device = None
        self.wireless_device = None
        self._get_device_objects()

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
        pass

    def check_network_status(self, network_id):
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

    def _get_device_objects(self):
        """Store the device objects that Netcheck needs to use frequently. This is part of
        a workaround for python-networkmanager being out of date in Ubuntu.
        """
        for device in NetworkManager.NetworkManager.GetDevices():
            if device.Interface == self.config['wired_interface_name']:
                self.wired_device = device
            elif device.Interface == self.config['wireless_interface_name']:
                self.wireless_device = device

        if self.wired_device is None or self.wireless_device is None:
            raise DeviceNotFoundException('Defined wired device %s was not found.' %
                self.config['wired_interface_name'])

        if self.wireless_device is None:
            raise DeviceNotFoundException('Defined wireless device %s was not found.' %
                self.config['wireless_interface_name'])

    def _get_device_for_connection(self, connection):
        """Get the device object a connection object needs to connect with. This is
        part of a workaround for python-networkmanager being out of date in Ubuntu.
        """

        network_type = connection.GetSettings()['connection']['type']
        network_device = None

        if network_type == WIRED_NETWORK_TYPE:
            network_device = self.wired_device

        elif network_type is WIRELESS_NETWORK_TYPE:
            network_device = self.wireless_device

        else:
            raise NetworkTypeNotHandledException('Network type %s is not supported.' %
                network_type)

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
