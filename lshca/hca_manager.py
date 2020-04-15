import os

import service_function
from config import Config
from datasource import DataSource
from raw_mlnx_bdf_device import RawMlnxBDFDevice as MlnxBDFDevice
from mlx_hca import MlnxHCA


class HCAManager(object):
    def __init__(self, config):
        if os.geteuid() != 0:
            raise OSError("You need to have root privileges to run this script")

        if type(config) is not Config:
            raise ValueError("Config type have to be Config")

        self.mlnx_hcas = []
        mlnx_bdf_list = []

        data_source = DataSource(config)

        # Same lspci cmd used in MST source in order to benefit from cache
        raw_mlnx_bdf_list = data_source.exec_shell_cmd("lspci -Dd 15b3:", use_cache=True)
        for member in raw_mlnx_bdf_list:
            bdf = service_function.extract_string_by_regex(member, "(.+) (Ethernet|Infini[Bb]and|Network)")

            if bdf != "=N/A=":
                mlnx_bdf_list.append(bdf)

        mlnx_bdf_devices = []
        for bdf in mlnx_bdf_list:
            port_count = 1

            while True:
                bdf_dev = MlnxBDFDevice(bdf, data_source, config, port_count)
                mlnx_bdf_devices.append(bdf_dev)

                if port_count >= len(bdf_dev.port_list):
                    break

                port_count += 1


        # First handle all PFs
        for bdf_dev in mlnx_bdf_devices:
            if bdf_dev.sriov in ("PF", "PF" + config.warning_sign):
                hca_found = False
                for hca in self.mlnx_hcas:
                    if bdf_dev.sys_image_guid == hca.sys_image_guid:
                        hca_found = True
                        hca.add_bdf_dev(bdf_dev)

                if not hca_found:
                    hca = MlnxHCA(bdf_dev, config)
                    hca.hca_index = len(self.mlnx_hcas) + 1
                    self.mlnx_hcas.append(hca)

        # Now handle all VFs
        for bdf_dev in mlnx_bdf_devices:
            if bdf_dev.sriov == 'VF':
                vf_parent_bdf = bdf_dev.vfParent

                # TBD: refactor to function
                for parent_bdf_dev in mlnx_bdf_devices:
                    parent_found = False
                    if vf_parent_bdf == parent_bdf_dev.bdf:
                        parent_found = True

                        hca = self._get_hca_by_sys_image_guid(parent_bdf_dev.sys_image_guid)
                        if hca is not None:
                            hca.add_bdf_dev(bdf_dev)
                        else:
                            raise Exception("VF " + str(bdf_dev) + " This device has no parent PF")

                    if parent_found:
                        break

    def _get_hca_by_sys_image_guid(self, sys_image_guid):
        for hca in self.mlnx_hcas:
            if sys_image_guid == hca.sys_image_guid:
                return hca
        return None
