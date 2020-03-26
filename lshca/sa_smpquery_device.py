import service_function


class SaSmpQueryDevice(object):
    def __init__(self, rdma, port, plid, smlid, data_source, config):
        self.sw_guid = ""
        self.sw_description = ""
        self.sm_guid = ""
        self.config = config

        if self.config.sa_smp_query_device_enabled:
            if "SMGuid" not in self.config.output_order:
                self.config.output_order.append("SMGuid")
            if "SwGuid" not in self.config.output_order:
                self.config.output_order.append("SwGuid")
            if "SwDescription" not in self.config.output_order:
                self.config.output_order.append("SwDescription")

            self.data = data_source.exec_shell_cmd("smpquery -C " + rdma + " -P " + port + " NI -D  0,1")
            self.sw_guid = self.get_info_from_sa_smp_query_data(".*SystemGuid.*", "\.+(.*)")
            self.sw_guid = service_function.extract_string_by_regex(self.sw_guid, "0x(.*)")

            self.data = data_source.exec_shell_cmd("smpquery -C " + rdma + " -P " + port + " ND -D  0,1")
            self.sw_description = self.get_info_from_sa_smp_query_data(".*Node *Description.*", "\.+(.*)")

            self.data = data_source.exec_shell_cmd("saquery SMIR -C " + rdma + " -P " + port + " " + smlid)
            self.sm_guid = self.get_info_from_sa_smp_query_data(".*GUID.*", "\.+(.*)")
            self.sm_guid = service_function.extract_string_by_regex(self.sm_guid, "0x(.*)")

    def get_info_from_sa_smp_query_data(self, search_regex, output_regex):
        search_result = service_function.find_in_list(self.data, search_regex)
        search_result = service_function.extract_string_by_regex(search_result, output_regex)
        return str(search_result).strip()
