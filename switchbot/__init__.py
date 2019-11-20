"""Library to handle connection with Switchbot"""
import time

import binascii
import logging

import bluepy

DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_TIMEOUT = .2

SERVICE_UUID = "cba20d00-224d-11e6-9fb8-0002a5d5c51b"
HANDLE = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
INFO_HANDLE = "cba20003-224d-11e6-9fb8-0002a5d5c51b"

PRESS_KEY = "570100"
ON_KEY = "570101"
OFF_KEY = "570102"

KEY_PREFIX = "5701"
KEY_PASSWORD_PREFIX = "5711"
INFO_PREFIX = "5712"

ON_KEY_SUFFIX = "01"
OFF_KEY_SUFFIX = "02"
PRESS_KEY_SUFFIX = "00"

BATTERY_CHECK_TIMEOUT_SECONDS = 3600.0  # only get batt at most every 60 mins
BLE_NOTIFICATION_WAIT_TIME_SECONDS = 3.0

_LOGGER = logging.getLogger(__name__)


class Switchbot:
    """Representation of a Switchbot."""

    def __init__(self, mac, retry_count=DEFAULT_RETRY_COUNT, password=None) -> None:
        self._mac = mac
        self._device = None
        self._retry_count = retry_count
        _LOGGER.debug("Switchbot password:%s", password)
        self._password_encoded = self._passwordcrc(password)
        self._lastBattRefresh = 0
        self._battery_percent = None

    def _connect(self) -> None:
        if self._device is not None:
            return
        try:
            _LOGGER.debug("Connecting to Switchbot...")
            self._device = bluepy.btle.Peripheral(self._mac,
                                                  bluepy.btle.ADDR_TYPE_RANDOM)
            _LOGGER.debug("Connected to Switchbot.")
        except bluepy.btle.BTLEException:
            _LOGGER.debug("Failed connecting to Switchbot.", exc_info=True)
            self._device = None
            raise

    def _disconnect(self) -> None:
        if self._device is None:
            return
        _LOGGER.debug("Disconnecting")
        try:
            self._device.disconnect()
        except bluepy.btle.BTLEException:
            _LOGGER.warning("Error disconnecting from Switchbot.", exc_info=True)
        finally:
            self._device = None

    def _writekey(self, key) -> bool:
        _LOGGER.debug("Prepare to send")
        hand_service = self._device.getServiceByUUID(SERVICE_UUID)
        hand = hand_service.getCharacteristics(HANDLE)[0]
        _LOGGER.debug("Sending command, %s", key)
        write_result = hand.write(binascii.a2b_hex(key), withResponse=True)
        if not write_result:
            _LOGGER.error("Sent command but didn't get a response from Switchbot confirming command was sent. "
                          "Please check the Switchbot.")
        else:
            _LOGGER.info("Successfully sent command to Switchbot (MAC: %s).", self._mac)
        return write_result

    @staticmethod
    def _passwordcrc(password) -> str:
        if password is None or password == "":
            return ""
        return '%x' % (binascii.crc32(password.encode('ascii')) & 0xffffffff)

    def _commandkey(self, key) -> str:
        key = ""
        key_suffix = PRESS_KEY_SUFFIX
        if key == ON_KEY:
            key_suffix = ON_KEY_SUFFIX
        elif key == OFF_KEY:
            key_suffix = OFF_KEY_SUFFIX
        if self._password_encoded is not None:
            key = KEY_PASSWORD_PREFIX + self._password_encoded + key_suffix
        else:
            key = KEY_PREFIX + key_suffix
        return key

    def _getBatteryPercent_FWVersion(self):
        now = time.time()
        if self._lastBattRefresh + BATTERY_CHECK_TIMEOUT_SECONDS >= now:
            return
        self._device.setDelegate(SwitchBotSettingsNotificationDelegate(self))
        handler = bluepy.btle.Characteristic(self._device, "0014", 20, None, 20)
        handler.write(binascii.a2b_hex("0100"))
        self._writekey(INFO_PREFIX + self._password_encoded)

        if self._device.waitForNotifications(BLE_NOTIFICATION_WAIT_TIME_SECONDS):
            _LOGGER.info("Switchbot got batt notification!")
            self._lastBattRefresh = time.time()
        time.sleep(1)
        _LOGGER.info("DONE Waiting...")

        # hand_service = self._device.getServiceByUUID(SERVICE_UUID)
        # hand = hand_service.getCharacteristics(INFO_HANDLE)[0]
        # chars = self._device.getCharacteristics()  # (startHnd=1, endHnd=16)
        # for p in chars:
        #     _LOGGER.info("Got Char %s HANDLE: %s", p, p.getHandle())
        #     if p.getHandle() == 19 or p.getHandle() == 20:
        #         _LOGGER.info("Switchbot Writing handle 14")
        #         p.write(binascii.a2b_hex("0100"))
        # svcs = self._device.getServices()
        # for s in svcs:
        #     _LOGGER.info("Got SVC %s chars: %s", s, s.getCharacteristics())
        #     for c in s.getCharacteristics():
        #         _LOGGER.info("Got SVC %s CHAR: %s HANDLE: %s", s, c, c.getHandle())
        # send_success = hand.write(binascii.a2b_hex("0100"), withResponse=True)
        # handleNotification() was called

    def _sendcommand(self, key, retry) -> bool:
        send_success = False
        command = self._commandkey(key)
        _LOGGER.warning("Sending command to switchbot %s", command)
        try:
            self._connect()
            self._getBatteryPercent_FWVersion()
            send_success = self._writekey(command)
        except bluepy.btle.BTLEException:
            _LOGGER.warning("Error talking to Switchbot.", exc_info=True)
        finally:
            self._disconnect()
        if send_success:
            return send_success
        if retry < 1:
            _LOGGER.error("Switchbot communication failed. Stopping trying.", exc_info=True)
            return False
        _LOGGER.warning("Cannot connect to Switchbot. Retrying (remaining: %d)...", retry)
        time.sleep(DEFAULT_RETRY_TIMEOUT)
        return self._sendcommand(key, retry - 1)

    def turn_on(self) -> bool:
        """Turn device on."""
        return self._sendcommand(ON_KEY, self._retry_count)

    def turn_off(self) -> bool:
        """Turn device off."""
        return self._sendcommand(OFF_KEY, self._retry_count)

    def press(self) -> bool:
        """Press command to device."""
        return self._sendcommand(PRESS_KEY, self._retry_count)


class SwitchBotSettingsNotificationDelegate(bluepy.btle.DefaultDelegate):
    def __init__(self, params):
        bluepy.btle.DefaultDelegate.__init__(self)
        _LOGGER.info("Setup switchbot delegate: %s", params)
        self._driver = params

    def handleNotification(self, cHandle, data):
        _LOGGER.info("********* Switchbot notification ************* - [Handle: %s] Data: %s", cHandle, data )
        _LOGGER.info("********* Switchbot notification ************* - [Handle: %s] Data: %s", cHandle, data.hex() )
        batt = data[1] #int.from_bytes(data[1], byteorder='big')
        firmware_version = data[2] / 10.0
        _LOGGER.debug("Got SwitchBot battery: %d FW Version: %f", batt, firmware_version)
        self._driver._battery_percent = batt
