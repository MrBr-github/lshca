![regression](https://github.com/MrBr-github/lshca/actions/workflows/run_regression.yml/badge.svg)

# LSHCA
This utility comes to provide bird's-eye view of HCAs installed.<br>
Other utilities can show deeper/better information in their small area, but LSHCA shows comprehensive information from many sources.<br>
It's mainly intended for system administrators, thus defaults configured accordingly.

# Main features
* Supported HCA features
  * Socket Direct HCA
  * Bond
  * SRIOV
* Elastic output - comes to reduce excessive information in human readable output
* Protocol/feature oriented views: IB, RoCE, Cable, Traffic, LLDP, DPU
* Machine readable output: JSON
* Doesn't requires 3rd party libraries
* Supports Python 2.7 and 3.x

# Limitations
 * requires root, this comes from lspci limitation to provide full information to non-root users

# Examples
## System view
ConnectX6 socket direct 200G and ConnectX5 100G HCAs.
<pre><code>---------------------------------------------------------------------------------------------------
Dev #1
 Desc: Mellanox Technologies MT28908 Family [ConnectX-6]
 PN: MCX654106A-HCAT  rev. A5
 PSID: MT_0000000228
 SN: MT185.......
 FW: 20.26.0282
 Tempr: 60
---------------------------------------------------------------------------------------------------
  PCI_addr   |  RDMA  | Net  | Numa | LnkStat | IpStat  | Link | Rate | LnkCapWidth | HCA_Type
---------------------------------------------------------------------------------------------------
0000:04:00.0 | mlx5_0 | ib0  |  0   |  actv   | up_ip4  |  IB  | 200  |   x16 G3    |  MT4123
0000:04:00.1 | mlx5_1 | ib1  |  0   |  down   |  down   |  IB  | 10*  |   x16 G3    |  MT4123
0000:82:00.0 | mlx5_4 | ib3  |  1   |  actv   | up_ip4  |  IB  | 200  |   x16 G3    |  MT4123
0000:82:00.1 | mlx5_5 | ib4  |  1   |  down   |  down   |  IB  | 10*  |   x16 G3    |  MT4123
---------------------------------------------------------------------------------------------------
Dev #2
 Desc: Mellanox Technologies MT27800 Family [ConnectX-5]
 PN: MCX556A-ECAT  rev. A3
 PSID: MT_0000000008
 SN: MT17........
 FW: 16.27.1016
 Tempr: 47
---------------------------------------------------------------------------------------------------
  PCI_addr   |  RDMA  | Net  | Numa | IpStat  | Link | Rate | LnkCapWidth | LnkStaWidth | HCA_Type
---------------------------------------------------------------------------------------------------
0000:81:00.0 | mlx5_2 | ib2  |  1   | up_ip4  |  IB  | 100  |   x16 G3    |   x8 >!<    |  MT4119
0000:81:00.1 | mlx5_3 | p2p2 |  1   | up_ip46 | Eth  | 100  |   x16 G3    |   x8 >!<    |  MT4119
---------------------------------------------------------------------------------------------------
</code></pre>

## IB view
<pre><code>----------------------------------------------------------------------------------------------------------------------------------------------------------
Dev #1
 Desc: Mellanox Technologies MT28908 Family [ConnectX-6]
 PN: MCX653105A-ECAT  rev. A6
 PSID: MT_0000000222
 SN: MT19......
 FW: 20.28.1002
----------------------------------------------------------------------------------------------------------------------------------------------------------
 RDMA  | Net | Numa | IpStat  | VrtHCA | PLid |      PGuid       |    IbNetPref     |      SMGuid      |      SwGuid      |         SwDescription
----------------------------------------------------------------------------------------------------------------------------------------------------------
mlx5_0 | ib0 |  0   | up_ip4  |  Phys  |  22  | b8599f0300d1f222 | fe80000000000000 | 248a0703003f1856 | b8599f0300e9062e | Quantum Mellanox Technologies
----------------------------------------------------------------------------------------------------------------------------------------------------------
</code></pre>



For more information about LSHCA see [wiki](https://github.com/MrBr-github/lshca/wiki) and extended help `lshca -hh`
