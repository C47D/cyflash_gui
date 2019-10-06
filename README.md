# GUI wrapper for cyflash

See [cyflash](https://github.com/arachnidlabs/cyflash) for the original cyflash project.

To hack on it:
- Clone this repo: `git clone https://github.com/C47D/cyflash_gui.git`
- Get into the `cyflash_gui` directory and run `fbs run`.
- To generate installers see [here](https://github.com/mherrmann/fbs-tutorial#creating-an-installer).

To build it you'll need the following python packages:
- six
- cyflash
- pyserial
- PySide2 (tested with version 5.12.0, so install it like so: `pip install PySide2==5.12.0`)
- fbs
