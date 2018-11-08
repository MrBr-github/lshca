#!/bin/bash -xvEe

if [ $USER != root ] ; then
 echo "Run this script with sudo or under root"
 exit 1
fi

tmp_dir=$(mktemp -d)
cp lshca.py ${tmp_dir}/lshca
chmod ugo+x ${tmp_dir}/lshca

cd /hpc/local/

lab_mounts="/net/mtrlabfs01/vol/hpcvol/local/ppc64le/bin
/net/mtrlabfs01/vol/hpcvol/local/x86_64/bin
/net/mtrlabfs01/vol/hpcvol/local/aarch64/bin "

for dest in ${lab_mounts}; do
  /bin/cp -f ${tmp_dir}/lshca ${dest}/lshca
done

scp ${tmp_dir}/lshca rdmz-head:/hpc/local/bin/lshca

if [ "x${tmp_dir}" != "x" ] ; then
    rm -rf ${tmp_dir}
fi