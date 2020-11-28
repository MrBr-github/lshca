# Description: Part of lshca library
#
# Author: Michael Braverman
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

import sys
if sys.version_info.major == 3:
    from . import service_function
else:
    import service_function


class PCIDevice(object):
    def __init__(self, bdf, data_source, config):
        self.bdf = bdf
        self.config = config
        self.bdWithoutF = self.bdf.split(".", 1)[0]
        self.data = data_source.exec_shell_cmd("lspci -vvvD -s" + bdf, use_cache=True)
        # Handling following string, taking reset of string after HCA type
        # 0000:01:00.0 Infiniband controller: Mellanox Technologies MT27700 Family [ConnectX-4]
        self.description = self.get_info_from_lspci_data("^[0-9].*", str(self.bdf) + ".*:(.+)")
        self.sn = self.get_info_from_lspci_data("\[SN\].*", ".*:(.+)")
        self._pn = self.get_info_from_lspci_data("\[PN\].*", ".*:(.+)")
        self.revision = self.get_info_from_lspci_data("\[EC\].*", ".*:(.+)")
        self.lnkCapWidth = self.get_info_from_lspci_data("LnkCap:.*Width.*", ".*Width (x[0-9]+)")
        self.lnkStaWidth = self.get_info_from_lspci_data("LnkSta:.*Width.*", ".*Width (x[0-9]+)")
        self.pciGen = self.get_info_from_lspci_data(".*[Pp][Cc][Ii][Ee] *[Gg][Ee][Nn].*",
                                                    ".*[Pp][Cc][Ii][Ee] *[Gg][Ee][Nn]([0-9]) +")

        if self.lnkCapWidth != self.lnkStaWidth and self.config.show_warnings_and_errors is True:
            self.lnkStaWidth = str(self.lnkStaWidth) + self.config.error_sign

        self.lnkCapWidth = str(self.lnkCapWidth) + " G" + str(self.pciGen)

    def __repr__(self):
        delim = " "
        return "PCI device:" + delim + \
               self.bdf + delim + \
               self.sn + delim + \
               self.pn + delim + \
               "\"" + self.description + "\""

    @property
    def pn(self):
        if self.revision != "=N/A=":
            return self._pn + "  rev. " + self.revision
        else:
            return self._pn

    def get_info_from_lspci_data(self, search_regex, output_regex):
        search_result = service_function.find_in_list(self.data, search_regex)
        search_result = service_function.extract_string_by_regex(search_result, output_regex)
        return str(search_result).strip()
