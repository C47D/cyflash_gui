#!/usr/bin/env python3

from fbs_runtime.application_context.PySide2 import ApplicationContext
from PySide2.QtWidgets import QMainWindow

from PySide2.QtWidgets import *
from PySide2.QtCore import *
from PySide2.QtUiTools import QUiLoader

import sys

from cyflash import protocol
from cyflash import bootload
from cyflash import cyacd

import serial
import serial.tools.list_ports

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

        self.window.list_com_pushButton.clicked.connect(self.on_list_ports)
        self.window.port_open_pushButton.clicked.connect(self.on_open_port)
        self.window.port_close_pushButton.clicked.connect(self.on_close_port)
       
        self.window.open_file_pushButton.clicked.connect(self.on_open_file)
        self.window.boot_inicio_pushButton.clicked.connect(self.on_bootloader)

        self.window.port_close_pushButton.setEnabled(True)

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
        transport = protocol.SerialTransport(ser, True)
        
        try:
            checksum_func = protocol.crc16_chesksum
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
            session = make_session()
            bl = BootloaderHost(session, sys.stdout)

            try:
                bl.bootload(data, True, True, args.psoc5)
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
        return 1

    @Slot()
    def on_open_port(self):
        serial_port_device = self.window.port_list_comboBox.currentText()
        serial_baudrate = self.window.baudrate_comboBox.currentText()
        serial_baudrate = int(serial_baudrate, base=10)

        # TODO: Handle exceptions
        self.ser = serial.Serial(serial_port_device, serial_baudrate)

        if self.ser.is_open:
            print('Port {} opened'.format(serial_port_device))

            # Disable serial port buttons
            self.window.port_list_comboBox.setEnabled(False)
            self.window.port_open_pushButton.setEnabled(False)
            self.window.port_close_pushButton.setEnabled(True)
            self.window.list_com_pushButton.setEnabled(False)
            self.window.open_file_pushButton.setEnabled(True)

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
