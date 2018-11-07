#!/bin/bash

if [ $USER != root ] ; then
 echo "Run this script with sudo or under root" 
 exit 1
fi


cd /hpc/local/
cd -

lab_mounts="/net/mtrlabfs01/vol/hpcvol/local/ppc64le/bin
/net/mtrlabfs01/vol/hpcvol/local/x86_64/bin
/net/mtrlabfs01/vol/hpcvol/local/aarch64/bin "

for dest in lab_mounts; do
  /bin/cp -f lshca.py ${dest}/lshca
done

scp lshca rdmz-head:/hpc/local/bin/lshca
