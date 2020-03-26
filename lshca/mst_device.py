import service_function

from __future__ import print_function
import sys


class MSTDevice(object):
    def __init__(self, bdf, data_source, config):
        self.bdf = bdf
        self.config = config
        self.mst_device = ""
        self.mst_raw_data = "No MST data"
        self.bdf_short_format = True
        mst_init_running = False

        if self.config.mst_device_enabled:
            if "MST_device" not in self.config.output_order:
                self.config.output_order.append("MST_device")

            result = data_source.exec_shell_cmd("which mst &> /dev/null ; echo $?", use_cache=True)
            if result == ["0"]:
                mst_installed = True
            else:
                mst_installed = False

            if mst_installed:
                result = data_source.exec_shell_cmd("mst status | grep -c 'MST PCI configuration module loaded'",
                                                    use_cache=True)
                if result != ["0"]:
                    mst_init_running = True

                if not mst_init_running:
                    data_source.exec_shell_cmd("mst start", use_cache=True)

                self.mst_raw_data = data_source.exec_shell_cmd("mst status -v", use_cache=True)
                self.got_raw_data = True

                if not mst_init_running:
                    data_source.exec_shell_cmd("mst stop", use_cache=True)

                # Same lspci cmd used in HCAManager in order to benefit from cache
                lspci_raw_data = data_source.exec_shell_cmd("lspci -Dd 15b3:", use_cache=True)
                for line in lspci_raw_data:
                    pci_domain = service_function.extract_string_by_regex(line, "([0-9]{4}):.*")
                    if pci_domain != "0000":
                        self.bdf_short_format = False

                if self.bdf_short_format:
                    self.bdf = service_function.extract_string_by_regex(self.bdf, "[0-9]{4}:(.*)")

                for line in self.mst_raw_data:
                    data_line = service_function.extract_string_by_regex(line, "(.*" + self.bdf + ".*)")
                    if data_line != "=N/A=":
                        mst_device = service_function.extract_string_by_regex(data_line, ".* (/dev/mst/[^\s]+) .*")
                        self.mst_device = mst_device
            else:
                print("\n\nError: MST tool is missing\n\n", file=sys.stderr)
                # Disable further use.access to mst device
                self.config.mst_device_enabled = False

    def __repr__(self):
        return self.mst_raw_data
