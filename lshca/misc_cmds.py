# Description: Part of lshca library
#
# Author: Michael Braverman
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

import service_function

class MiscCMDs(object):
    def __init__(self, net, rdma, data_source, config):
        self.data_source = data_source
        self.net = net
        self.rdma = rdma
        self.config = config

    def get_mlnx_qos_trust(self):
        data = self.data_source.exec_shell_cmd("mlnx_qos -i " + self.net, use_cache=True)
        regex = "Priority trust state: (.*)"
        search_result = service_function.find_in_list(data, regex)
        search_result = service_function.extract_string_by_regex(search_result, regex)
        return search_result

    def get_mlnx_qos_pfc(self):
        data = self.data_source.exec_shell_cmd("mlnx_qos -i " + self.net, use_cache=True)
        regex = '^\s+enabled\s+(([0-9]\s+)+)'
        search_result = service_function.find_in_list(data, regex)
        search_result = service_function.extract_string_by_regex(search_result, regex).replace(" ", "")
        return search_result

    def get_tempr(self):
        data = self.data_source.exec_shell_cmd("mget_temp -d " + self.rdma, use_cache=True)
        regex = '^([0-9]+)\s+$'
        search_result = service_function.find_in_list(data, regex)
        search_result = service_function.extract_string_by_regex(search_result, regex).replace(" ", "")
        try:
            if int(search_result) > 90:
                return search_result + self.config.error_sign
            elif int(search_result) > 80:
                return search_result + self.config.warning_sign
            return search_result
        except ValueError:
            return "=N/A="