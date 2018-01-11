
import NetworkManager

WIRED_DEVICE = 'eth0'
WIRELESS_DEVICE = 'eth1'

class DeviceNotFoundException(Exception):
    pass

class NetworkManagerHelper:
    """NetworkManagerHelper abstracts away some of the messy details of the NetworkManager
    Dbus API."""

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
        pass

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
            raise DeviceNotFoundException('Defined wired device was not found.')

        if self.wireless_device is None:
            raise DeviceNotFoundException('Defined wireless device was not found.')

    def _get_device_for_connection(self, connection):
        # The Ubuntu repositories are using an ancient version of python-networkmanager with
        #   a bug concerning the device dbus interface, and pre-defining the devices like
        #   this is a workaround.
        pass
