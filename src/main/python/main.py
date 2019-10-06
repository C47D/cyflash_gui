#!/usr/bin/env python3

from fbs_runtime.application_context.PySide2 import ApplicationContext
from PySide2.QtWidgets import QMainWindow

from PySide2.QtWidgets import *
from PySide2.QtCore import *
from PySide2.QtUiTools import QUiLoader

import sys
import six
import codecs
import time

from cyflash import protocol
from cyflash import bootload
from cyflash import cyacd

import serial
import serial.tools.list_ports

def auto_int(x):
    return int(x, 0)

class BootloaderError(Exception): pass

class BootloaderHost(object):
    def __init__(self, session, out, dual_app):
        self.session = session
        self.out = out
        self.dual_app = dual_app
        self.chunk_size = 25
        # self.key = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
        self.key = None
        self.row_ranges = {}

    def bootload(self, data, downgrade, newapp, psoc5):
        self.out.write('Entering bootload.\n')
        self.enter_bootloader(data)
        if self.dual_app:
            self.out.write("Getting application status.\n")
            app_area_to_flash = self.application_status()
        self.out.write("Verifying row ranges.\n")
        self.verify_row_ranges(data)
        self.out.write("Checking metadata.\n")
        self.check_metadata(data, downgrade, newapp, psoc5)
        self.out.write("Starting flash operation.\n")
        self.write_rows(data)
        if not self.session.verify_checksum():
            print('Flash checksum error')
            raise BootloaderError("Flash checksum does not verify! Aborting.")
        else:
            self.out.write("Device checksum verifies OK.\n")
        if self.dual_app:
            self.set_application_active(app_area_to_flash)
        self.out.write("Rebooting device.\n")
        self.session.exit_bootloader()

    def set_application_active(self, application_id):
        self.out.write("Setting application %d as active.\n" % application_id)
        self.session.set_application_active(application_id)

    def application_status(self):
        to_flash = None
        for app in [0, 1]:
            app_valid, app_active = self.session.application_status(app)
            self.out.write("App %d: valid: %s, active: %s\n" % (app, app_valid, app_active))
            if app_active == 0:
                to_flash = app

        if to_flash is None:
            raise BootloaderError("Failed to find inactive app to flash. Aborting.")
        self.out.write("Will flash app %d.\n" % to_flash)
        return to_flash

    def verify_row_ranges(self, data):
        for array_id, array in six.iteritems(data.arrays):
            start_row, end_row = self.session.get_flash_size(array_id)
            self.out.write("Array %d: first row %d, last row %d.\n" % (
                array_id, start_row, end_row))
            self.row_ranges[array_id] = (start_row, end_row)
            for row_number in array:
                if row_number < start_row or row_number > end_row:
                    raise BootloaderError(
                        "Row %d in array %d out of range. Aborting."
                        % (row_number, array_id))

    def enter_bootloader(self, data):
        self.out.write("Initialising bootloader.\n")
        silicon_id, silicon_rev, bootloader_version = self.session.enter_bootloader(self.key)
        self.out.write("Silicon ID 0x%.8x, revision %d.\n" % (silicon_id, silicon_rev))
        if silicon_id != data.silicon_id:
            raise ValueError("Silicon ID of device (0x%.8x) does not match firmware file (0x%.8x)"
                             % (silicon_id, data.silicon_id))
        if silicon_rev != data.silicon_rev:
            raise ValueError("Silicon revision of device (0x%.2x) does not match firmware file (0x%.2x)"
                             % (silicon_rev, data.silicon_rev))

    def check_metadata(self, data, downgrade, newapp, psoc5):
        try:
            if psoc5:
                metadata = self.session.get_psoc5_metadata(0)
            else:
                metadata = self.session.get_metadata(0)
            self.out.write("Device application_id %d, version %d.\n" % (
                metadata.app_id, metadata.app_version))
        except protocol.InvalidApp:
            self.out.write("No valid application on device.\n")
            return
        except protocol.BootloaderError as e:
            self.out.write("Cannot read metadata from device: {}\n".format(e))
            return

        # TODO: Make this less horribly hacky
        # Fetch from last row of last flash array
        metadata_row = data.arrays[max(data.arrays.keys())][self.row_ranges[max(data.arrays.keys())][1]]
        if psoc5:
            local_metadata = protocol.GetPSOC5MetadataResponse(metadata_row.data[192:192+56])
        else:
            local_metadata = protocol.GetMetadataResponse(metadata_row.data[64:120])

        if metadata.app_version > local_metadata.app_version:
            message = "Device application version is v%d.%d, but local application version is v%d.%d." % (
                metadata.app_version >> 8, metadata.app_version & 0xFF,
                local_metadata.app_version >> 8, local_metadata.app_version & 0xFF)
            if not downgrade(metadata.app_version, local_metadata.app_version):
                raise ValueError(message + " Aborting.")

        if metadata.app_id != local_metadata.app_id:
            message = "Device application ID is %d, but local application ID is %d." % (
                metadata.app_id, local_metadata.app_id)
            if not newapp(metadata.app_id, local_metadata.app_id):
                raise ValueError(message + " Aborting.")

    def write_rows(self, data):
        total = sum(len(x) for x in data.arrays.values())
        i = 0
        for array_id, array in six.iteritems(data.arrays):
            for row_number, row in array.items():
                i += 1
                self.session.program_row(array_id, row_number, row.data, self.chunk_size)
                actual_checksum = self.session.get_row_checksum(array_id, row_number)
                if actual_checksum != row.checksum:
                    raise BootloaderError(
                        "Checksum does not match in array %d row %d. Expected %.2x, got %.2x! Aborting." % (
                            array_id, row_number, row.checksum, actual_checksum))
                self.progress("Uploading data", i, total)
            self.progress()

    def progress(self, message=None, current=None, total=None):
        if not message:
            self.out.write("\n")
        else:
            self.out.write("\r%s (%d/%d)" % (message, current, total))
        self.out.flush()

class AppContext(ApplicationContext):
    
    def run(self):
        self.app.setStyle('Fusion')

        self.ser = None
    
        # Load the UI file
        ui_file = appctxt.get_resource("mainwindow.ui")
        loaded_file = QFile(ui_file)
        loaded_file.open(QFile.ReadOnly)
        loader = QUiLoader()
        self.window = loader.load(loaded_file)

        # Signals and Slots
        self.window.list_com_pushButton.clicked.connect(self.on_list_ports)
        self.window.port_open_pushButton.clicked.connect(self.on_open_port)
        self.window.port_close_pushButton.clicked.connect(self.on_close_port)
       
        self.window.open_file_pushButton.clicked.connect(self.on_open_file)
        self.window.boot_inicio_pushButton.clicked.connect(self.on_bootloader)

        # Buttons, checkboxes, etc default states
        # This could be done on the QtDesigner file but we're using it
        # just for UI layout
        self.window.port_open_pushButton.setEnabled(False)
        self.window.port_close_pushButton.setEnabled(True)

        self.window.device_comboBox.setEnabled(False)
        self.window.boot_inicio_pushButton.setEnabled(False)

        self.on_list_ports()

        self.window.show()
        return self.app.exec_()

    def ports_list(self):
        return serial.tools.list_ports.comports()

    def seek_permission(self, argument):
        if argument is not None:
            return lambda remote, local: argument
    
    @Slot()
    def on_open_file(self):
        desktop_path = QStandardPaths.standardLocations(QStandardPaths.DesktopLocation)[0]

        filename = QFileDialog.getOpenFileName(self.window, 'Open cyacd file', desktop_path, "Image Files (*.cyacd)" )

        self.cyacd_file = filename[0]

        # short_filename = QFileInfo(self.cyacd_file).filename()
        print('You choosed the cyacd file named {}'.format(self.cyacd_file))
        self.window.lineEdit_file_path.setText(self.cyacd_file)

        return True

    # TODO: Add checkbox on GUI to choose checksum algo
    def make_session(self):
        self.ser.flushInput() # need to clear any garbage off the serial port
        self.ser.flushOutput()
        # 
        transport = protocol.SerialTransport(self.ser, True)
        
        try:
            checksum_func = protocol.sum_2complement_checksum
        except KeyError:
            raise BootloaderError("Invalid checksum type")
        
        #
        session = protocol.BootloaderSession(transport, checksum_func)
        
        return session

    @Slot()
    def on_bootloader(self):
        with open(self.cyacd_file, 'r') as app:
            data = cyacd.BootloaderData.read(app)
            # 
            session = self.make_session()
            # TODO How to get BootloaderHost output in a logging instance
            bl = BootloaderHost(session, sys.stdout, False)

            try:
                # TODO: last parameter is psoc5, check key
                bl.bootload(data, True, True, True)
            except (protocol.BootloaderError, BootloderError) as e:
                print('Unhandled error: {}'.format(e))
                return 1

        return 0

    @Slot()
    def on_list_ports(self):
        self.window.port_list_comboBox.clear()

        available_ports = self.ports_list()

        if not available_ports:
            print('Couldn\'t find serial ports')
            return 0
        
        for port in available_ports:
            self.window.port_list_comboBox.addItem(port.device)

        self.window.port_open_pushButton.setEnabled(True)
        return 1

    @Slot()
    def on_open_port(self):
        
        # Make sure we're trying to open a valid serial port
        serial_count = self.window.port_list_comboBox.count()
        if serial_count is 0:
            print('No serial ports listed')
            return

        serial_port_device = self.window.port_list_comboBox.currentText()
        serial_baudrate = self.window.baudrate_comboBox.currentText()
        serial_baudrate = int(serial_baudrate, base=10)

        # TODO: Handle exceptions
        timeout = self.window.bootloaderTimeout_lineEdit.text()
        timeout = int(timeout, base=10)
        print('Serial port: {}, baudrate: {}, timeout: {}'.format(serial_port_device, serial_baudrate, timeout))
        self.ser = serial.Serial(serial_port_device, serial_baudrate, timeout = timeout)

        if self.ser.is_open:
            print('Port {} opened'.format(serial_port_device))

            # Disable serial port buttons
            self.window.port_list_comboBox.setEnabled(False)
            self.window.port_open_pushButton.setEnabled(False)
            self.window.port_close_pushButton.setEnabled(True)
            self.window.list_com_pushButton.setEnabled(False)
            self.window.open_file_pushButton.setEnabled(True)
            self.window.boot_inicio_pushButton.setEnabled(True)
        else:
            print('Port {} not opened'.format(serial_port_device))

    @Slot()
    def on_close_port(self):
        if self.ser.is_open:
            self.ser.close()
            print('Port closed')
        else:
            print('Port already closed')

if __name__ == '__main__':
    appctxt = AppContext()
    exit_code = appctxt.run()
    sys.exit(exit_code)
