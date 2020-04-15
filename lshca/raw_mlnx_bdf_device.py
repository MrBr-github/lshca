import re

from sysfs_device import SYSFSDevice
from pci_device import PCIDevice
from mst_device import MSTDevice
from misc_cmds import MiscCMDs
from sa_smpquery_device import SaSmpQueryDevice


class RawMlnxBDFDevice(object):
    def __init__(self, bdf, data_source, config, port=1):
        self.bdf = bdf
        self.config = config
        self.slaveBDFDevices = []

        self.sysFSDevice = SYSFSDevice(self.bdf, data_source, self.config, port)
        self.fw = self.sysFSDevice.fw
        self.hca_type = self.sysFSDevice.hca_type
        self.ib_net_prefix = self.sysFSDevice.ib_net_prefix
        self.link_layer = self.sysFSDevice.link_layer
        self.ip_state = self.sysFSDevice.ip_state
        self.pguid = self.sysFSDevice.pguid
        self.port = self.sysFSDevice.port
        self.port_list = self.sysFSDevice.port_list
        self.port_rate = self.sysFSDevice.port_rate
        self.plid = self.sysFSDevice.plid
        self.net = self.sysFSDevice.net
        self.numa = self.sysFSDevice.numa
        self.rdma = self.sysFSDevice.rdma
        self.smlid = self.sysFSDevice.smlid
        self.lnk_state = self.sysFSDevice.lnk_state
        self.virt_hca = self.sysFSDevice.virt_hca
        self.vfParent = self.sysFSDevice.vfParent
        self.sys_image_guid = self.sysFSDevice.sys_image_guid
        self.psid = self.sysFSDevice.psid

        self.pciDevice = PCIDevice(self.bdf, data_source, self.config)
        self.description = self.pciDevice.description
        if self.sriov != "VF":
            self.lnkCapWidth = self.pciDevice.lnkCapWidth
            self.lnkStaWidth = self.pciDevice.lnkStaWidth
        else:
            self.lnkCapWidth = ""
            self.lnkStaWidth = ""
        self.pn = self.pciDevice.pn
        self.sn = self.pciDevice.sn

        self.mstDevice = MSTDevice(self.bdf, data_source, self.config)
        self.mst_device = self.mstDevice.mst_device

        self.miscDevice = MiscCMDs(self.net, self.rdma, data_source, self.config)
        self.tempr = self.miscDevice.get_tempr()

        self.sasmpQueryDevice = SaSmpQueryDevice(self.rdma, self.port, self.plid, self.smlid,
                                                 data_source, self.config)
        self.sw_guid = self.sasmpQueryDevice.sw_guid
        self.sw_description = self.sasmpQueryDevice.sw_description
        self.sm_guid = self.sasmpQueryDevice.sm_guid

    def __repr__(self):
        return self.sysFSDevice.__repr__() + "\n" + self.pciDevice.__repr__() + "\n" + \
               self.mstDevice.__repr__() + "\n"

    # Not in use, consider removal
    def add_slave_bdf_device(self, slave_bdf_device):
        self.slaveBDFDevices.append(slave_bdf_device)

    # Not in use, consider removal
    def get_slave_bdf_devices(self):
        return self.slaveBDFDevices

    @property
    def sriov(self):
        if self.config.show_warnings_and_errors is True and self.sysFSDevice.sriov == "PF" and \
                re.match(r".*[Vv]irtual [Ff]unction.*", self.pciDevice.description):
            return self.sysFSDevice.sriov + self.config.warning_sign
        else:
            return self.sysFSDevice.sriov

    @property
    def roce_status(self):
        if self.link_layer != "Eth":
            return "N/A"

        if self.sysFSDevice.gtclass == self.config._lossless_roce_expected_gtclass and \
                self.sysFSDevice.tcp_ecn == self.config._lossless_roce_expected_tcp_ecn and \
                self.sysFSDevice.rdma_cm_tos == self.config._lossless_roce_expected_rdma_cm_tos and \
                self.miscDevice.get_mlnx_qos_trust() == self.config._lossless_roce_expected_trust and \
                self.miscDevice.get_mlnx_qos_pfc() == self.config._lossless_roce_expected_pfc:
            return "Lossless"
        else:
            return "Lossy"

    def output_info(self):
        if self.sriov in ("PF", "PF" + self.config.warning_sign):
            sriov = self.sriov + "  "
        else:
            sriov = "  " + self.sriov
        output = {"SRIOV": sriov,
                  "Numa": self.numa,
                  "PCI_addr": self.bdf,
                  "Parent_addr": self.vfParent,
                  "RDMA": self.rdma,
                  "Net": self.net,
                  "HCA_Type": self.hca_type,
                  "LnkStat": self.lnk_state,
                  "Rate": self.port_rate,
                  "Port": self.port,
                  "Link": self.link_layer,
                  "MST_device": self.mst_device,
                  "LnkCapWidth": self.lnkCapWidth,
                  "LnkStaWidth": self.lnkStaWidth,
                  "PLid": self.plid,
                  "PGuid": self.pguid,
                  "IbNetPref": self.ib_net_prefix,
                  "SMGuid": self.sm_guid,
                  "SwGuid": self.sw_guid,
                  "SwDescription": self.sw_description,
                  "VrtHCA": self.virt_hca,
                  "IpStat": self.ip_state,
                  "RoCEstat": self.roce_status}
        return output
