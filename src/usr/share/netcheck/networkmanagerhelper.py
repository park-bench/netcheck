
import NetworkManager

# TODO: Move these to the configuration file.
WIRED_DEVICE = 'ens3'
WIRELESS_DEVICE = 'ens8'

# Network type strings according to python-networkmanager
WIRED_NETWORK_TYPE = '802-3-ethernet'
WIRELESS_NETWORK_TYPE = '802-11-wireless'

class DeviceNotFoundException(Exception):
    """This exception is raised when a configured network device is not found."""
    pass

class NetworkTypeNotHandledException(Exception):
    """This exception is raised when a configured network is a type that this library does
    not handle.
    """
    pass

class NetworkManagerHelper:
    """NetworkManagerHelper abstracts away some of the messy details of the NetworkManager
    Dbus API.
    """

    def __init__(self, config):
        # Build mac address to device object table

        self.config = config

        # TODO: Remove these and read these values from the config file.
        self.config['wired_interface_name'] = WIRED_DEVICE
        self.config['wireless_interface_name'] = WIRELESS_DEVICE

        self.network_id_table = self._build_network_id_table()

        self.wired_device = None
        self.wireless_device = None
        self._get_device_objects()

    def activate_network(self, network_id):
        """Tells NetworkManager to activate a network with the supplied network_id.
        Returns True if there are no errors, False otherwise.
        """
        success = False
        network_device = self._get_device_for_connection(network_id)

        try:
            NetworkManager.NetworkManager.ActivateConnection(network_id, network_device, '/')
            success = True
        except Exception as detail:
            self.logger.error(detail.msg

        return success

    def get_network_ip(self, network_id):
        pass

    def check_network_status(self, network_id):
        pass

    def _build_network_id_table(self):
        network_id_table = {}
        for connection in NetworkManager.Settings.ListConnections():
            connection_id = connection.GetSettings()['connection']['id']
            network_id_table[connection_id] = connection

        return network_id_table

    def _get_device_objects(self):
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
        # The Ubuntu repositories are using an ancient version of python-networkmanager with
        #   a bug concerning the device dbus interface, and pre-defining the devices like
        #   this is a workaround.
        network_type = None

        if connection['connection']['type'] == WIRED_NETWORK_TYPE:
            network_type = self.wired_device

        elif connection['connection']['type'] == WIRELESS_NETWORK_TYPE:
            network_type = self.wireless_device

        else:
            raise NetworkTypeNotHandledException('Network type %s is not supported.' %
                connection['connection']['type'])

        return network_type

    def _wait_for_connection(self, network_id, timeout):
        """Wait timeout number of seconds for an active connection to be ready.
        return True if it connects within timeout, False otherwise.
        """
        pass
