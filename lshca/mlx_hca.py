# Description: Part of lshca library
#
# Author: Michael Braverman
# Project repo: https://github.com/MrBr-github/lshca
# License: This utility provided under GNU GPLv3 license

class MlnxHCA(object):
    def __init__(self, bdf_dev, config):
        self.bdf_devices = []
        self.config = config

        if bdf_dev.sriov in ("PF", "PF" + self.config.warning_sign):
            self.bdf_devices.append(bdf_dev)
        else:
            raise ValueError("MlnxHCA object can be initialised ONLY with PF bdfDev")

        self.sn = bdf_dev.sn
        self.pn = bdf_dev.pn
        self.fw = bdf_dev.fw
        self.psid = bdf_dev.psid
        self.sys_image_guid = bdf_dev.sys_image_guid
        self.description = bdf_dev.description
        self.tempr = bdf_dev.tempr
        self._hca_index = None

    def __repr__(self):
        output = ""
        for bdf_dev in self.bdf_devices:
            output = output + str(bdf_dev)
        return output

    @property
    def hca_index(self):
        return "#" + str(self._hca_index)

    @hca_index.setter
    def hca_index(self, index):
        self._hca_index = index

    def add_bdf_dev(self, new_bdf_dev):
        if new_bdf_dev.sriov == "VF" and new_bdf_dev.vfParent != "-":
            for i, bdf_dev in enumerate(self.bdf_devices):
                if bdf_dev.bdf == new_bdf_dev.vfParent:
                    self.bdf_devices.insert(i + 1, new_bdf_dev)
        else:
            self.bdf_devices.append(new_bdf_dev)

    def output_info(self):
        output = {"SN": self.sn,
                  "PN": self.pn,
                  "FW": self.fw,
                  "PSID": self.psid,
                  "Desc": self.description,
                  "Tempr": self.tempr,
                  "Dev": self.hca_index,
                  "bdf_devices": []}
        for bdf_dev in self.bdf_devices:
            output["bdf_devices"].append(bdf_dev.output_info())
        return output
